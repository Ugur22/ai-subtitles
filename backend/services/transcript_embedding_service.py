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

# Named configurations let retrieval experiments coexist without changing the production chunk size.
DEFAULT_INDEX_CONFIG = "chunk_size_3"
INDEX_CONFIGS: Dict[str, int] = {
    "chunk_size_2": 2,
    "chunk_size_3": 3,
    "chunk_size_5": 5,
}


def prepare_embedding_query(query: str, model_name: Optional[str] = None) -> str:
    model_name = model_name or settings.TEXT_EMBEDDING_MODEL
    if model_name == "BAAI/bge-small-en-v1.5":
        return _BGE_QUERY_PREFIX + query
    return query


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

    def _replace_index(self, client, kind: str, video_hash: str, user_id: str,
                       records: List[Dict], index_config: str = DEFAULT_INDEX_CONFIG) -> int:
        params = {
            'p_user_id': user_id,
            'target_video_hash': video_hash,
            'p_embedding_model': settings.TEXT_EMBEDDING_MODEL,
            'p_rows': records,
        }
        if kind == 'transcript':
            params['target_index_config'] = index_config
        for attempt in range(3):
            try:
                client.rpc(f'replace_{kind}_embedding_index', params).execute()
                return len(records)
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError):
                if attempt == 2:
                    raise
                time.sleep(0.5 * (2 ** attempt))
        return 0

    # ------------------------------------------------------------------
    # Transcript chunks
    # ------------------------------------------------------------------

    def transcript_chunks_exist(self, video_hash: str, user_id: str, index_config: str = DEFAULT_INDEX_CONFIG) -> bool:
        """Check if transcript chunks are indexed for a video"""
        try:
            client = supabase()
            result = client.table('transcript_embeddings_v2').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).eq('embedding_model', settings.TEXT_EMBEDDING_MODEL).eq('index_config', index_config).limit(1).execute()
            return (result.count or 0) > 0
        except Exception as e:
            raise RuntimeError(f"Transcript chunk availability check failed: {e}") from e

    def index_transcript_chunks(
        self,
        video_hash: str,
        segments: List[Dict],
        user_id: str,
        chunk_size: int = 3,
        index_config: str = DEFAULT_INDEX_CONFIG,
        force_reindex: bool = False,
    ) -> int:
        """
        Index transcription segments under the configured model and chunk configuration

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments
            user_id: Owner ID for tenant isolation
            chunk_size: Number of segments to combine into one chunk (default: 3)
            index_config: Named indexing configuration this index belongs to
                (default: "chunk_size_3", the production baseline). Distinct
                configs are stored side by side and never overwrite each other.
            force_reindex: If True, atomically replace this model/config index

        Returns:
            Number of chunks indexed
        """
        if index_config not in INDEX_CONFIGS:
            raise ValueError(f"Unknown index configuration: {index_config}")
        if chunk_size != INDEX_CONFIGS[index_config]:
            raise ValueError("chunk_size must match index_config")
        if not segments and not force_reindex:
            print("[TranscriptEmbedding] No segments to index")
            return 0
        if not user_id:
            raise ValueError("user_id is required for owner-scoped transcript indexing")

        client = supabase()

        if not force_reindex:
            existing = client.table('transcript_embeddings_v2').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).eq('embedding_model', settings.TEXT_EMBEDDING_MODEL).eq(
                'index_config', index_config
            ).limit(1).execute()
            if existing.data:
                count = existing.count or len(existing.data)
                print(
                    f"[TranscriptEmbedding] Video {video_hash} already has {count} indexed chunks "
                    f"for index_config={index_config}"
                )
                return count

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
                'index_config': index_config,
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
            if force_reindex:
                return self._replace_index(client, 'transcript', video_hash, user_id, [], index_config)
            return 0

        print(f"[TranscriptEmbedding] Encoding {len(chunks)} chunks with {settings.TEXT_EMBEDDING_MODEL} for video {video_hash}...")
        embeddings = self.embedding_model.encode(
            chunks,
            convert_to_numpy=True,
        ).tolist()

        records = [
            {**record, 'embedding': embedding}
            for record, embedding in zip(chunk_records, embeddings)
        ]

        return self._replace_index(client, 'transcript', video_hash, user_id, records, index_config)

    def search_transcript_chunks(
        self,
        video_hash: str,
        query: str,
        user_id: str,
        n_results: int = 5,
        index_config: str = DEFAULT_INDEX_CONFIG,
    ) -> List[Dict]:
        """
        Search for relevant transcript chunks using semantic similarity

        Args:
            video_hash: Unique hash of the video
            query: Search query
            user_id: Owner ID for tenant isolation
            n_results: Number of results to return
            index_config: Named indexing configuration to search within
                (default: "chunk_size_3", the production baseline). Chunks
                from other configs are never returned.

        Returns:
            List of relevant chunks shaped like {"text", "metadata", "similarity"}
        """
        if not user_id:
            return []

        client = supabase()
        query_embedding = self.embedding_model.encode(
            [prepare_embedding_query(query)],
            convert_to_numpy=True,
        ).tolist()[0]

        try:
            result = client.rpc(
                'search_transcript_chunks_by_embedding_v2',
                {
                    'p_user_id': user_id,
                    'p_embedding_model': settings.TEXT_EMBEDDING_MODEL,
                    'query_embedding': query_embedding,
                    'target_video_hash': video_hash,
                    'match_count': n_results,
                    'target_index_config': index_config,
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
            result = client.table('audio_event_embeddings_v2').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).eq('embedding_model', settings.TEXT_EMBEDDING_MODEL).limit(1).execute()
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
            force_reindex: If True, atomically replace this model/config index

        Returns:
            Number of audio events indexed
        """
        if not segments and not force_reindex:
            print("[TranscriptEmbedding] No segments to index")
            return 0
        if not user_id:
            raise ValueError("user_id is required for owner-scoped audio event indexing")

        client = supabase()

        if not force_reindex:
            existing = client.table('audio_event_embeddings_v2').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).eq('embedding_model', settings.TEXT_EMBEDDING_MODEL).limit(1).execute()
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
            if force_reindex:
                return self._replace_index(client, 'audio', video_hash, user_id, [])
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

        return self._replace_index(client, 'audio', video_hash, user_id, records)

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
            [prepare_embedding_query(query)],
            convert_to_numpy=True,
        ).tolist()[0]

        try:
            result = client.rpc(
                'search_audio_events_by_embedding_v2',
                {
                    'p_user_id': user_id,
                    'p_embedding_model': settings.TEXT_EMBEDDING_MODEL,
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

        for key, tables in (
            ('text_updated', ('transcript_embeddings', 'transcript_embeddings_v2')),
            ('audio_updated', ('audio_event_embeddings', 'audio_event_embeddings_v2')),
        ):
            for table in tables:
                try:
                    response = client.table(table).update({'speaker': new_speaker}).eq(
                        'user_id', user_id
                    ).eq('video_hash', video_hash).eq('speaker', old_speaker).execute()
                    results[key] += len(response.data or [])
                except Exception as e:
                    print(f"[TranscriptEmbedding] Speaker update failed for {table}: {e}")

        return results


# Global instance
transcript_embedding_service = TranscriptEmbeddingService()
