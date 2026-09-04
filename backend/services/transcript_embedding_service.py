"""
Transcript & Audio-Event Embedding Service using Supabase pgvector
Handles persistent storage of text embeddings for transcript chunks and audio events
"""

import time
import httpx
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer
from config import settings
from services.supabase_service import supabase

# bge-small-en-v1.5 is retrieval-tuned and expects this instruction prefix on
# the query side only -- passages/chunks being indexed are encoded as-is.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class TranscriptEmbeddingService:
    """Service for storing and searching transcript-chunk and audio-event embeddings in Supabase"""

    def __init__(self):
        """Initialize the transcript embedding service"""
        self._embedding_model = None

    @property
    def embedding_model(self) -> SentenceTransformer:
        """
        Lazy load text embedding model shared by transcript chunks and audio events

        Returns:
            sentence-transformers model configured via settings.TEXT_EMBEDDING_MODEL
        """
        if self._embedding_model is None:
            print(f"[TranscriptEmbedding] Loading text embedding model ({settings.TEXT_EMBEDDING_MODEL})...")
            self._embedding_model = SentenceTransformer(settings.TEXT_EMBEDDING_MODEL)
            print("[TranscriptEmbedding] Text embedding model loaded successfully")
        return self._embedding_model

    def _upsert_with_retry(
        self,
        client,
        table: str,
        on_conflict: str,
        records: List[Dict],
        batch_num: int,
        total_batches: int,
        max_retries: int = 3,
    ) -> None:
        # Supabase sits behind Cloudflare which closes idle sockets after ~60s. httpx's
        # pooled connection can be dead by the time we write the next batch. Catch the
        # transport errors, force the pool to rebuild, and retry with backoff.
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                client.table(table).upsert(records, on_conflict=on_conflict).execute()
                print(
                    f"[TranscriptEmbedding] Inserted {table} batch {batch_num}/{total_batches} "
                    f"({len(records)} rows)"
                )
                return
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as e:
                last_err = e
                try:
                    session = getattr(client.postgrest, 'session', None)
                    if session is not None:
                        session.close()
                except Exception:
                    pass
                backoff = 0.5 * (2 ** attempt)
                print(
                    f"[TranscriptEmbedding] Retry {attempt + 1}/{max_retries} for {table} batch "
                    f"{batch_num} after {type(e).__name__}: {e}. Sleeping {backoff}s"
                )
                time.sleep(backoff)
        raise last_err if last_err else RuntimeError(f"{table} batch upsert failed")

    # ------------------------------------------------------------------
    # Transcript chunks
    # ------------------------------------------------------------------

    def transcript_chunks_exist(self, video_hash: str, user_id: str) -> bool:
        """Check if transcript chunks are indexed for a video"""
        try:
            client = supabase()
            result = client.table('transcript_embeddings').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).limit(1).execute()
            return (result.count or 0) > 0
        except Exception as e:
            raise RuntimeError(f"Transcript chunk availability check failed: {e}") from e

    def index_transcript_chunks(
        self,
        video_hash: str,
        segments: List[Dict],
        user_id: str,
        chunk_size: int = 3,
        force_reindex: bool = False,
    ) -> int:
        """
        Index transcription segments into Supabase using MiniLM embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments
            user_id: Owner ID for tenant isolation
            chunk_size: Number of segments to combine into one chunk (default: 3)
            force_reindex: If True, bypass the already-indexed skip and re-upsert

        Returns:
            Number of chunks indexed
        """
        if not segments:
            print("[TranscriptEmbedding] No segments to index")
            return 0
        if not user_id:
            raise ValueError("user_id is required for owner-scoped transcript indexing")

        client = supabase()

        if not force_reindex:
            existing = client.table('transcript_embeddings').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).limit(1).execute()
            if existing.data:
                count = existing.count or len(existing.data)
                print(f"[TranscriptEmbedding] Video {video_hash} already has {count} indexed chunks")
                return count

        # Upsert on (user_id, video_hash, chunk_index) overwrites rows in place, so we
        # intentionally do NOT pre-delete on force_reindex — mirrors image_embedding_service's
        # image indexing: partial progress is never destroyed if an insert fails partway
        # through. force_reindex only bypasses the early-return "already indexed" check above.

        chunks: List[str] = []
        chunk_records: List[Dict] = []

        for chunk_index, i in enumerate(range(0, len(segments), chunk_size)):
            chunk_segments = segments[i:i + chunk_size]

            texts = []
            for seg in chunk_segments:
                text = seg.get('translation') or seg.get('text', '')
                if text and text.strip():
                    texts.append(text.strip())

            if not texts:
                continue

            combined_text = " ".join(texts)
            first_segment = chunk_segments[0]
            last_segment = chunk_segments[-1]

            chunks.append(combined_text)
            chunk_records.append({
                'user_id': user_id,
                'video_hash': video_hash,
                'chunk_index': chunk_index,
                'start_time': first_segment.get('start', 0.0),
                'end_time': last_segment.get('end', 0.0),
                'start_timestamp': first_segment.get('start_time', '00:00:00'),
                'end_timestamp': last_segment.get('end_time', '00:00:00'),
                'speaker': first_segment.get('speaker', 'SPEAKER_00'),
                'segment_count': len(chunk_segments),
                'chunk_text': combined_text,
            })

        if not chunks:
            print("[TranscriptEmbedding] No valid chunks to index")
            return 0

        print(f"[TranscriptEmbedding] Encoding {len(chunks)} chunks with MiniLM for video {video_hash}...")
        embeddings = self.embedding_model.encode(
            chunks,
            convert_to_numpy=True,
        ).tolist()

        records = [
            {**record, 'embedding': embedding}
            for record, embedding in zip(chunk_records, embeddings)
        ]

        insert_batch_size = 50
        total_batches = (len(records) + insert_batch_size - 1) // insert_batch_size
        indexed_count = 0
        for i in range(0, len(records), insert_batch_size):
            batch = records[i:i + insert_batch_size]
            batch_num = i // insert_batch_size + 1
            try:
                self._upsert_with_retry(
                    client,
                    'transcript_embeddings',
                    'user_id,video_hash,chunk_index',
                    batch,
                    batch_num,
                    total_batches,
                )
                indexed_count += len(batch)
            except Exception as e:
                print(
                    f"[TranscriptEmbedding] Chunk batch {batch_num}/{total_batches} permanently "
                    f"failed after retries: {e}"
                )

        print(
            f"[TranscriptEmbedding] Successfully indexed {indexed_count}/{len(records)} "
            f"chunks for video {video_hash}"
        )
        return indexed_count

    def search_transcript_chunks(
        self,
        video_hash: str,
        query: str,
        user_id: str,
        n_results: int = 5,
    ) -> List[Dict]:
        """
        Search for relevant transcript chunks using semantic similarity

        Args:
            video_hash: Unique hash of the video
            query: Search query
            user_id: Owner ID for tenant isolation
            n_results: Number of results to return

        Returns:
            List of relevant chunks shaped like {"text", "metadata", "similarity"}
        """
        if not user_id:
            return []

        client = supabase()
        query_embedding = self.embedding_model.encode(
            [_BGE_QUERY_PREFIX + query],
            convert_to_numpy=True,
        ).tolist()[0]

        try:
            result = client.rpc(
                'search_transcript_chunks_by_embedding',
                {
                    'p_user_id': user_id,
                    'query_embedding': query_embedding,
                    'target_video_hash': video_hash,
                    'match_count': n_results,
                }
            ).execute()
        except Exception as e:
            raise RuntimeError(f"Transcript chunk search failed: {e}") from e

        formatted_results = []
        for item in result.data or []:
            formatted_results.append({
                'text': item['chunk_text'],
                'metadata': {
                    'video_hash': item['video_hash'],
                    'start': item['start_time'],
                    'end': item['end_time'],
                    'start_time': item['start_timestamp'],
                    'end_time': item['end_timestamp'],
                    'speaker': item['speaker'],
                    'segment_count': item['segment_count'],
                },
                'similarity': item['similarity'],
            })
        return formatted_results

    # ------------------------------------------------------------------
    # Audio events
    # ------------------------------------------------------------------

    def audio_events_exist(self, video_hash: str, user_id: str) -> bool:
        """Check if audio events are indexed for a video AND have data"""
        if not user_id:
            return False
        try:
            client = supabase()
            result = client.table('audio_event_embeddings').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).limit(1).execute()
            return (result.count or 0) > 0
        except Exception as e:
            raise RuntimeError(f"Audio event availability check failed: {e}") from e

    def index_audio_events(
        self,
        video_hash: str,
        segments: List[Dict],
        user_id: str,
        force_reindex: bool = False,
    ) -> int:
        """
        Index audio events from transcription segments into Supabase

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with audio_events or audio_analysis
            user_id: Owner ID for tenant isolation
            force_reindex: If True, bypass the already-indexed skip and re-upsert

        Returns:
            Number of audio events indexed
        """
        if not segments:
            print("[TranscriptEmbedding] No segments to index")
            return 0
        if not user_id:
            raise ValueError("user_id is required for owner-scoped audio event indexing")

        client = supabase()

        if not force_reindex:
            existing = client.table('audio_event_embeddings').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).limit(1).execute()
            if existing.data:
                count = existing.count or len(existing.data)
                print(f"[TranscriptEmbedding] Video {video_hash} already has {count} indexed audio events")
                return count

        audio_data = []
        segments_with_audio = 0

        for seg in segments:
            audio_events = seg.get('audio_events')
            audio_analysis = seg.get('audio_analysis')

            if not (audio_events or audio_analysis):
                continue

            segments_with_audio += 1
            event_descriptions = []
            primary_event = None
            speech_emotion = None
            has_speech = False

            if audio_events:
                sorted_events = sorted(
                    audio_events,
                    key=lambda x: x.get('confidence', 0),
                    reverse=True,
                )
                for event in sorted_events:
                    event_type = event.get('event_type', 'unknown')
                    confidence = event.get('confidence', 0)
                    if confidence > 0.1:
                        event_descriptions.append(f"{event_type} ({confidence*100:.0f}%)")
                if sorted_events:
                    primary_event = sorted_events[0].get('event_type', 'unknown')

            if audio_analysis:
                has_speech = audio_analysis.get('has_speech', False)
                speech_emotion_data = audio_analysis.get('speech_emotion')
                if speech_emotion_data and isinstance(speech_emotion_data, dict):
                    speech_emotion = speech_emotion_data.get('emotion', 'unknown')
                    emotion_confidence = speech_emotion_data.get('confidence', 0)
                    event_descriptions.append(f"emotion: {speech_emotion} ({emotion_confidence*100:.0f}%)")
                else:
                    speech_emotion = None

            if has_speech and not event_descriptions:
                event_descriptions.append("speech")
                if not primary_event:
                    primary_event = "speech"

            if not event_descriptions:
                continue

            description_text = ", ".join(event_descriptions)
            audio_data.append({
                'text': description_text,
                'segment_id': seg.get('id', ''),
                'start': seg.get('start', 0.0),
                'end': seg.get('end', 0.0),
                'speaker': seg.get('speaker', 'SPEAKER_00'),
                'has_speech': has_speech,
                'primary_event': primary_event or 'unknown',
                'speech_emotion': speech_emotion or 'unknown',
            })

        print(
            f"[TranscriptEmbedding] Audio analysis: {segments_with_audio} segments have audio "
            f"events, {len(audio_data)} valid events to index"
        )

        if not audio_data:
            print("[TranscriptEmbedding] No valid audio events found in segments")
            return 0

        texts = [item['text'] for item in audio_data]
        print(f"[TranscriptEmbedding] Encoding {len(texts)} audio event descriptions...")
        embeddings = self.embedding_model.encode(
            texts,
            convert_to_numpy=True,
        ).tolist()

        records = []
        for item, embedding in zip(audio_data, embeddings):
            records.append({
                'user_id': user_id,
                'video_hash': video_hash,
                'segment_id': str(item['segment_id']),
                'start_time': item['start'],
                'end_time': item['end'],
                'speaker': item['speaker'],
                'has_speech': item['has_speech'],
                'primary_event': item['primary_event'],
                'speech_emotion': item['speech_emotion'],
                'description': item['text'],
                'embedding': embedding,
            })

        insert_batch_size = 50
        total_batches = (len(records) + insert_batch_size - 1) // insert_batch_size
        indexed_count = 0
        for i in range(0, len(records), insert_batch_size):
            batch = records[i:i + insert_batch_size]
            batch_num = i // insert_batch_size + 1
            try:
                self._upsert_with_retry(
                    client,
                    'audio_event_embeddings',
                    'user_id,video_hash,segment_id',
                    batch,
                    batch_num,
                    total_batches,
                )
                indexed_count += len(batch)
            except Exception as e:
                print(
                    f"[TranscriptEmbedding] Audio batch {batch_num}/{total_batches} permanently "
                    f"failed after retries: {e}"
                )

        print(
            f"[TranscriptEmbedding] Successfully indexed {indexed_count}/{len(records)} "
            f"audio events for video {video_hash}"
        )
        return indexed_count

    def search_audio_events(
        self,
        video_hash: str,
        query: str,
        user_id: str,
        n_results: int = 5,
    ) -> List[Dict]:
        """
        Search for relevant audio events using semantic similarity

        Args:
            video_hash: Unique hash of the video
            query: Search query (e.g., "laughter", "applause", "sad emotion")
            user_id: Owner ID for tenant isolation
            n_results: Number of results to return

        Returns:
            List of relevant audio events shaped like {"description", "metadata", "similarity"}
        """
        if not user_id:
            return []

        client = supabase()
        query_embedding = self.embedding_model.encode(
            [_BGE_QUERY_PREFIX + query],
            convert_to_numpy=True,
        ).tolist()[0]

        try:
            result = client.rpc(
                'search_audio_events_by_embedding',
                {
                    'p_user_id': user_id,
                    'query_embedding': query_embedding,
                    'target_video_hash': video_hash,
                    'match_count': n_results,
                }
            ).execute()
        except Exception as e:
            raise RuntimeError(f"Audio event search failed: {e}") from e

        formatted_results = []
        for item in result.data or []:
            formatted_results.append({
                'description': item['description'],
                'metadata': {
                    'video_hash': item['video_hash'],
                    'segment_id': item['segment_id'],
                    'start': item['start_time'],
                    'end': item['end_time'],
                    'speaker': item['speaker'],
                    'has_speech': item['has_speech'],
                    'primary_event': item['primary_event'],
                    'speech_emotion': item['speech_emotion'],
                },
                'similarity': item['similarity'],
            })
        return formatted_results

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------

    def update_speaker_name(
        self,
        video_hash: str,
        user_id: str,
        old_speaker: str,
        new_speaker: str,
    ) -> Dict[str, int]:
        """
        Update speaker name in transcript-chunk and audio-event rows.

        Args:
            video_hash: Unique hash of the video
            user_id: Owner ID for tenant isolation
            old_speaker: Original speaker name/label to replace
            new_speaker: New speaker name

        Returns:
            Dict with updated transcript and audio-event counts.
        """
        results = {"text_updated": 0, "audio_updated": 0}
        client = supabase()

        try:
            response = client.table('transcript_embeddings').update(
                {'speaker': new_speaker}
            ).eq('user_id', user_id).eq('video_hash', video_hash).eq(
                'speaker', old_speaker
            ).execute()
            results['text_updated'] = len(response.data or [])
            if results['text_updated']:
                print(
                    f"[TranscriptEmbedding] Updated {results['text_updated']} text chunks "
                    f"from '{old_speaker}' to '{new_speaker}'"
                )
        except Exception as e:
            print(f"[TranscriptEmbedding] Error updating transcript_embeddings: {e}")

        try:
            response = client.table('audio_event_embeddings').update(
                {'speaker': new_speaker}
            ).eq('user_id', user_id).eq('video_hash', video_hash).eq(
                'speaker', old_speaker
            ).execute()
            results['audio_updated'] = len(response.data or [])
            if results['audio_updated']:
                print(
                    f"[TranscriptEmbedding] Updated {results['audio_updated']} audio events "
                    f"from '{old_speaker}' to '{new_speaker}'"
                )
        except Exception as e:
            print(f"[TranscriptEmbedding] Error updating audio_event_embeddings: {e}")

        return results


# Global instance
transcript_embedding_service = TranscriptEmbeddingService()
