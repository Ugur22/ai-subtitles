"""
Speaker Diarization Module using pyannote.audio

This module provides speaker diarization functionality to identify
different speakers in audio/video files.
"""

import os
import torch

# Fix for PyTorch 2.6+ which changed weights_only default to True
# This is required because pyannote uses lightning_fabric which calls torch.load()
# with the default weights_only=True, but pyannote models contain pickled objects
os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")

# Monkey-patch torch.load to use weights_only=False for pyannote compatibility
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs['weights_only'] = False  # Force override - lightning_fabric passes it explicitly
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

from pyannote.audio import Pipeline, Model
from pyannote.audio.pipelines.utils import get_devices
from pyannote.core import Segment
from typing import List, Dict, Tuple, Optional
import numpy as np
import tempfile
import subprocess


class SpeakerDiarizer:
    """
    Handle speaker diarization using pyannote.audio
    """

    def __init__(self, use_auth_token: str = None):
        """
        Initialize the speaker diarization pipeline

        Args:
            use_auth_token: Hugging Face authentication token (required for pyannote models)
                          Get it from: https://huggingface.co/settings/tokens
                          Accept pyannote conditions at: https://huggingface.co/pyannote/speaker-diarization
        """
        self.pipeline = None
        self.use_auth_token = use_auth_token

    def load_pipeline(self):
        """Load the diarization pipeline (lazy loading)"""
        if self.pipeline is None:
            print("Loading speaker diarization pipeline...")
            try:
                # Load the latest pyannote speaker diarization model
                self.pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=self.use_auth_token
                )

                # Use GPU if available
                # Check for CUDA (NVIDIA) first
                if torch.cuda.is_available():
                    device = torch.device("cuda")
                    print("Using CUDA (NVIDIA) for speaker diarization")
                # Check for MPS (Apple Silicon M1/M2/M3)
                elif torch.backends.mps.is_available():
                    device = torch.device("mps")
                    print("Using MPS (Apple Silicon) for speaker diarization")
                else:
                    device = torch.device("cpu")
                    print("Using CPU for speaker diarization")
                    
                self.pipeline.to(device)
                print(f"Speaker diarization pipeline loaded on {device}")
            except Exception as e:
                print(f"Error loading speaker diarization pipeline: {str(e)}")
                print("Make sure you have:")
                print("1. A Hugging Face token: https://huggingface.co/settings/tokens")
                print("2. Accepted pyannote conditions: https://huggingface.co/pyannote/speaker-diarization")
                raise

    def diarize(self, audio_path: str, num_speakers: int = None, min_speakers: int = None, max_speakers: int = None) -> List[Dict]:
        """
        Perform speaker diarization on an audio file

        Args:
            audio_path: Path to the audio file
            num_speakers: Exact number of speakers (optional, if known)
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)

        Returns:
            List of diarization segments with speaker labels and timestamps
            Format: [{"start": 0.5, "end": 3.2, "speaker": "SPEAKER_00"}, ...]
        """
        if self.pipeline is None:
            self.load_pipeline()

        print(f"Performing speaker diarization on: {audio_path}")

        # Prepare diarization parameters
        diarization_params = {}
        if num_speakers is not None:
            diarization_params["num_speakers"] = num_speakers
        else:
            if min_speakers is not None:
                diarization_params["min_speakers"] = min_speakers
            if max_speakers is not None:
                diarization_params["max_speakers"] = max_speakers

        # Run diarization
        try:
            diarization = self.pipeline(audio_path, **diarization_params)
        except Exception as e:
            print(f"Error during diarization: {str(e)}")
            raise

        # Convert diarization result to list of segments
        speaker_segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speaker_segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })

        print(f"Diarization complete. Found {len(set(seg['speaker'] for seg in speaker_segments))} speakers in {len(speaker_segments)} segments")

        return speaker_segments

    def assign_speakers_to_transcription(
        self,
        transcription_segments: List[Dict],
        speaker_segments: List[Dict]
    ) -> List[Dict]:
        """
        Assign speaker labels to transcription segments based on time overlap

        Args:
            transcription_segments: List of transcription segments with 'start' and 'end' times
            speaker_segments: List of speaker diarization segments with 'start', 'end', and 'speaker'

        Returns:
            Transcription segments with added 'speaker' field
        """
        print(f"Assigning speakers to {len(transcription_segments)} transcription segments...")

        for trans_seg in transcription_segments:
            # Get the start and end times of the transcription segment
            trans_start = trans_seg.get('start', 0.0)
            trans_end = trans_seg.get('end', 0.0)
            trans_mid = (trans_start + trans_end) / 2

            # Find the speaker segment with maximum overlap
            best_speaker = "UNKNOWN"
            max_overlap = 0

            for spk_seg in speaker_segments:
                spk_start = spk_seg['start']
                spk_end = spk_seg['end']

                # Calculate overlap
                overlap_start = max(trans_start, spk_start)
                overlap_end = min(trans_end, spk_end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = spk_seg['speaker']

                # Alternative: Check if midpoint falls within speaker segment
                # This can be faster and often more accurate
                if spk_start <= trans_mid <= spk_end:
                    best_speaker = spk_seg['speaker']
                    break

            # Assign the speaker to the transcription segment
            trans_seg['speaker'] = best_speaker

        # Count speakers
        unique_speakers = set(seg.get('speaker', 'UNKNOWN') for seg in transcription_segments)
        print(f"Speaker assignment complete. Identified {len(unique_speakers)} unique speakers")

        return transcription_segments


def format_speaker_label(speaker: str, custom_names: Dict[str, str] = None) -> str:
    """
    Format speaker label for display

    Args:
        speaker: Raw speaker label (e.g., "SPEAKER_00")
        custom_names: Optional dict mapping speaker IDs to custom names (e.g., {"SPEAKER_00": "John"})

    Returns:
        Formatted speaker label
    """
    if custom_names and speaker in custom_names:
        return custom_names[speaker]

    # Convert SPEAKER_00 to Speaker 1, SPEAKER_01 to Speaker 2, etc.
    if speaker.startswith("SPEAKER_"):
        try:
            speaker_num = int(speaker.split("_")[1]) + 1
            return f"Speaker {speaker_num}"
        except (IndexError, ValueError):
            pass

    return speaker


class ChunkedSpeakerDiarizer:
    """
    Handles speaker diarization for long videos using chunked processing
    with cross-chunk speaker matching via embedding similarity.

    This approach processes audio in manageable chunks (15-30 min) to avoid
    O(n²) clustering complexity, then unifies speaker labels across chunks
    using speaker embeddings.
    """

    def __init__(self, chunk_duration: int = 900, similarity_threshold: float = 0.7, use_auth_token: str = None):
        """
        Initialize chunked diarization system.

        Args:
            chunk_duration: Target duration for each diarization chunk in seconds (default: 900 = 15 min)
            similarity_threshold: Cosine similarity threshold for matching speakers across chunks (default: 0.7)
            use_auth_token: Hugging Face authentication token for pyannote models
        """
        self.chunk_duration = chunk_duration
        self.similarity_threshold = similarity_threshold
        self.use_auth_token = use_auth_token
        self.pipeline = None
        self.embedding_model = None
        self.device = None

    def load_pipeline(self):
        """Load the diarization pipeline (lazy loading, embedding model loaded separately for memory efficiency)"""
        if self.pipeline is None:
            from utils.memory_utils import log_gpu_memory

            print("[ChunkedDiarizer] Loading speaker diarization pipeline for chunked processing...")
            log_gpu_memory("ChunkedDiarizer:BeforePipeline")

            try:
                # Load diarization pipeline
                self.pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=self.use_auth_token
                )

                # Use GPU if available
                if torch.cuda.is_available():
                    self.device = torch.device("cuda")
                    print("[ChunkedDiarizer] Using CUDA (NVIDIA) for chunked diarization")
                elif torch.backends.mps.is_available():
                    self.device = torch.device("mps")
                    print("[ChunkedDiarizer] Using MPS (Apple Silicon) for chunked diarization")
                else:
                    self.device = torch.device("cpu")
                    print("[ChunkedDiarizer] Using CPU for chunked diarization")

                self.pipeline.to(self.device)

                log_gpu_memory("ChunkedDiarizer:PipelineLoaded")
                print(f"[ChunkedDiarizer] Diarization pipeline loaded on {self.device}")
            except Exception as e:
                print(f"[ChunkedDiarizer] Error loading chunked diarization pipeline: {str(e)}")
                raise

    def load_embedding_model(self):
        """Load embedding model on demand (separate from pipeline for memory efficiency)."""
        if self.embedding_model is None:
            from utils.memory_utils import log_gpu_memory

            print("[ChunkedDiarizer] Loading speaker embedding model...")
            log_gpu_memory("ChunkedDiarizer:BeforeEmbedding")

            self.embedding_model = Model.from_pretrained(
                "pyannote/embedding",
                use_auth_token=self.use_auth_token
            )

            # Ensure device is set (in case embedding model is loaded before pipeline)
            if self.device is None:
                if torch.cuda.is_available():
                    self.device = torch.device("cuda")
                elif torch.backends.mps.is_available():
                    self.device = torch.device("mps")
                else:
                    self.device = torch.device("cpu")

            self.embedding_model.to(self.device)

            log_gpu_memory("ChunkedDiarizer:EmbeddingLoaded")
            print("[ChunkedDiarizer] Speaker embedding model loaded")

    def unload_embedding_model(self):
        """Unload embedding model to free GPU memory."""
        if self.embedding_model is not None:
            from utils.memory_utils import clear_gpu_memory

            print("[ChunkedDiarizer] Unloading embedding model...")
            del self.embedding_model
            self.embedding_model = None
            clear_gpu_memory("ChunkedDiarizer:EmbeddingUnloaded")

    def unload_pipeline(self):
        """Unload entire pipeline to free GPU memory."""
        from utils.memory_utils import clear_gpu_memory

        print("[ChunkedDiarizer] Unloading diarization pipeline...")

        if self.embedding_model is not None:
            del self.embedding_model
            self.embedding_model = None

        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None

        clear_gpu_memory("ChunkedDiarizer:FullUnload")
        print("[ChunkedDiarizer] Diarization pipeline fully unloaded")

    def diarize_chunked(
        self,
        audio_chunks: List[str],
        chunk_duration: int = 300,
        num_speakers: int = None,
        min_speakers: int = None,
        max_speakers: int = None
    ) -> List[Dict]:
        """
        Diarize audio in chunks and unify speaker labels across chunks.

        Uses phased memory management:
        1. Phase 1: Diarize all chunks (pipeline only)
        2. Phase 2: Unload pipeline to free GPU memory
        3. Phase 3: Load embedding model
        4. Phase 4: Extract embeddings from all chunks
        5. Phase 5: Unload embedding model
        6. Phase 6: Match speakers (CPU only)

        Args:
            audio_chunks: List of paths to audio chunk files (typically 5-min chunks)
            chunk_duration: Duration of each input audio chunk in seconds (default: 300)
            num_speakers: Exact number of speakers (optional, applied to each chunk)
            min_speakers: Minimum number of speakers (optional, applied to each chunk)
            max_speakers: Maximum number of speakers (optional, applied to each chunk)

        Returns:
            List of speaker segments with unified global labels
            Format: [{"start": 0.5, "end": 3.2, "speaker": "SPEAKER_00"}, ...]
        """
        from utils.memory_utils import clear_gpu_memory

        # Ensure pipeline is loaded
        if self.pipeline is None:
            self.load_pipeline()

        print(f"[ChunkedDiarizer] Starting chunked diarization for {len(audio_chunks)} audio chunks")
        print(f"[ChunkedDiarizer] Target diarization chunk duration: {self.chunk_duration}s, input chunk duration: {chunk_duration}s")

        # Group small chunks into larger diarization groups
        diarization_groups = self._group_chunks(audio_chunks, chunk_duration)
        print(f"[ChunkedDiarizer] Created {len(diarization_groups)} diarization groups")

        # PHASE 1: Diarize all groups (pipeline only, no embeddings)
        print("\n=== PHASE 1: Diarizing all chunks ===")
        chunk_results = []
        for i, group in enumerate(diarization_groups):
            print(f"\n[Chunk {i+1}/{len(diarization_groups)}] Diarizing group with {len(group['chunks'])} audio files...")
            result = self._diarize_group_segments_only(
                group['chunks'],
                group['time_offset'],
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers
            )
            chunk_results.append(result)

            # Clear GPU cache after each chunk to prevent fragmentation
            clear_gpu_memory(f"Chunk{i+1}Complete")

        # PHASE 2: Unload pipeline to free GPU memory
        print("\n=== PHASE 2: Unloading diarization pipeline ===")
        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None
            clear_gpu_memory("PipelineUnloaded")

        # PHASE 3: Load embedding model
        print("\n=== PHASE 3: Loading embedding model ===")
        self.load_embedding_model()

        # PHASE 4: Extract embeddings from all chunks
        print("\n=== PHASE 4: Extracting embeddings from all chunks ===")
        try:
            for i, result in enumerate(chunk_results):
                print(f"\n[Chunk {i+1}/{len(chunk_results)}] Extracting embeddings for {len(set(s['speaker'] for s in result['segments']))} speakers...")
                speaker_embeddings = self._extract_speaker_embeddings(result['audio_path'], result['segments'])
                result['speaker_embeddings'] = speaker_embeddings

                # Clear GPU cache after each chunk
                clear_gpu_memory(f"EmbeddingChunk{i+1}Complete")

                # Clean up temporary audio file immediately after embedding extraction
                if result.get('is_temp', False):
                    try:
                        import os
                        os.unlink(result['audio_path'])
                        print(f"  Cleaned up temp file: {result['audio_path']}")
                    except Exception as e:
                        print(f"  Warning: Could not delete temp file {result['audio_path']}: {e}")
        finally:
            # Ensure we clean up any remaining temp files even if extraction fails
            for result in chunk_results:
                if result.get('is_temp', False):
                    try:
                        import os
                        if os.path.exists(result['audio_path']):
                            os.unlink(result['audio_path'])
                    except Exception:
                        pass

        # PHASE 5: Unload embedding model
        print("\n=== PHASE 5: Unloading embedding model ===")
        self.unload_embedding_model()

        # PHASE 6: Match speakers across chunks (CPU only)
        print("\n=== PHASE 6: Matching speakers across chunks (CPU) ===")
        chunk_to_global_map, global_speaker_count = self._match_speakers(chunk_results)

        # Build unified segment list with global speaker labels
        print(f"[ChunkedDiarizer] Unifying segments with {global_speaker_count} global speakers...")
        unified_segments = self._unify_segments(chunk_results, chunk_to_global_map)

        print(f"\n[ChunkedDiarizer] Chunked diarization complete. Total segments: {len(unified_segments)}, Unique speakers: {global_speaker_count}")
        return unified_segments

    def _group_chunks(self, audio_chunks: List[str], chunk_duration: int) -> List[Dict]:
        """
        Group small audio chunks into larger diarization groups.

        Args:
            audio_chunks: List of paths to audio chunk files
            chunk_duration: Duration of each input chunk in seconds

        Returns:
            List of groups, each containing chunk paths and time offset
            Format: [{"chunks": [...], "time_offset": 0}, ...]
        """
        groups = []
        chunks_per_group = max(1, int(self.chunk_duration / chunk_duration))

        for i in range(0, len(audio_chunks), chunks_per_group):
            group_chunks = audio_chunks[i:i + chunks_per_group]
            time_offset = i * chunk_duration
            groups.append({
                "chunks": group_chunks,
                "time_offset": time_offset
            })

        return groups

    def _diarize_group_segments_only(
        self,
        chunk_paths: List[str],
        time_offset: float,
        num_speakers: int = None,
        min_speakers: int = None,
        max_speakers: int = None
    ) -> Dict:
        """
        Concatenate audio chunks and perform diarization on the group (segments only, no embeddings).

        This method performs diarization and returns segments along with the audio path
        for later embedding extraction. This enables phased memory management where
        the pipeline can be unloaded before loading the embedding model.

        Args:
            chunk_paths: List of paths to audio files in this group
            time_offset: Time offset in seconds for this group (start time in full video)
            num_speakers: Exact number of speakers (optional)
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)

        Returns:
            Dict containing diarization segments and audio path for embedding extraction
        """
        # If single chunk, use it directly
        if len(chunk_paths) == 1:
            concat_audio_path = chunk_paths[0]
            temp_file = None
            is_temp = False
        else:
            # Concatenate chunks using ffmpeg
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            concat_audio_path = temp_file.name
            temp_file.close()
            is_temp = True

            print(f"  Concatenating {len(chunk_paths)} chunks...")
            self._concatenate_audio_files(chunk_paths, concat_audio_path)

        # Prepare diarization parameters
        diarization_params = {}
        if num_speakers is not None:
            diarization_params["num_speakers"] = num_speakers
        else:
            if min_speakers is not None:
                diarization_params["min_speakers"] = min_speakers
            if max_speakers is not None:
                diarization_params["max_speakers"] = max_speakers

        # Run diarization
        print(f"  Running diarization...")
        diarization = self.pipeline(concat_audio_path, **diarization_params)

        # Convert to segments list
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start + time_offset,  # Adjust for global timeline
                "end": turn.end + time_offset,
                "speaker": speaker,
                "local_start": turn.start,  # Keep local time for embedding extraction
                "local_end": turn.end
            })

        print(f"  Diarization complete: {len(segments)} segments, {len(set(s['speaker'] for s in segments))} speakers")

        return {
            "time_offset": time_offset,
            "segments": segments,
            "audio_path": concat_audio_path,
            "is_temp": is_temp,
            "speaker_embeddings": {}  # Will be filled later in Phase 4
        }

    def _diarize_group(
        self,
        chunk_paths: List[str],
        time_offset: float,
        num_speakers: int = None,
        min_speakers: int = None,
        max_speakers: int = None
    ) -> Dict:
        """
        Concatenate audio chunks and perform diarization on the group.

        Args:
            chunk_paths: List of paths to audio files in this group
            time_offset: Time offset in seconds for this group (start time in full video)
            num_speakers: Exact number of speakers (optional)
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)

        Returns:
            Dict containing diarization segments and speaker embeddings
        """
        # If single chunk, use it directly
        if len(chunk_paths) == 1:
            concat_audio_path = chunk_paths[0]
            temp_file = None
        else:
            # Concatenate chunks using ffmpeg
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            concat_audio_path = temp_file.name
            temp_file.close()

            print(f"  Concatenating {len(chunk_paths)} chunks...")
            self._concatenate_audio_files(chunk_paths, concat_audio_path)

        try:
            # Prepare diarization parameters
            diarization_params = {}
            if num_speakers is not None:
                diarization_params["num_speakers"] = num_speakers
            else:
                if min_speakers is not None:
                    diarization_params["min_speakers"] = min_speakers
                if max_speakers is not None:
                    diarization_params["max_speakers"] = max_speakers

            # Run diarization
            print(f"  Running diarization...")
            diarization = self.pipeline(concat_audio_path, **diarization_params)

            # Convert to segments list
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start + time_offset,  # Adjust for global timeline
                    "end": turn.end + time_offset,
                    "speaker": speaker,
                    "local_start": turn.start,  # Keep local time for embedding extraction
                    "local_end": turn.end
                })

            # Extract embeddings for each speaker
            print(f"  Extracting embeddings for {len(set(s['speaker'] for s in segments))} speakers...")
            speaker_embeddings = self._extract_speaker_embeddings(concat_audio_path, segments)

            return {
                "time_offset": time_offset,
                "segments": segments,
                "speaker_embeddings": speaker_embeddings
            }
        finally:
            # Clean up temporary concatenated file
            if temp_file is not None:
                try:
                    import os
                    os.unlink(concat_audio_path)
                except Exception as e:
                    print(f"  Warning: Could not delete temp file {concat_audio_path}: {e}")

    def _concatenate_audio_files(self, audio_files: List[str], output_path: str):
        """
        Concatenate multiple audio files using ffmpeg.

        Args:
            audio_files: List of audio file paths to concatenate
            output_path: Output path for concatenated audio
        """
        # Create a temporary file list for ffmpeg concat demuxer
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for audio_file in audio_files:
                # Escape single quotes and use absolute path
                escaped_path = audio_file.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
            list_file = f.name

        try:
            # Use ffmpeg concat demuxer
            cmd = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', list_file,
                '-c', 'copy',
                output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        finally:
            # Clean up list file
            try:
                import os
                os.unlink(list_file)
            except Exception:
                pass

    def _extract_speaker_embeddings(self, audio_path: str, segments: List[Dict]) -> Dict[str, np.ndarray]:
        """
        Extract representative embeddings for each speaker.

        For robustness, we compute embeddings from multiple segments per speaker
        and average them.

        Args:
            audio_path: Path to audio file
            segments: List of diarization segments with local_start/local_end times

        Returns:
            Dict mapping speaker labels to embeddings
        """
        speaker_embeddings = {}

        # Group segments by speaker
        speaker_to_segments = {}
        for seg in segments:
            speaker = seg['speaker']
            if speaker not in speaker_to_segments:
                speaker_to_segments[speaker] = []
            speaker_to_segments[speaker].append(seg)

        # Extract embeddings for each speaker
        for speaker, speaker_segments in speaker_to_segments.items():
            # Sort by duration (longest first) to get best quality segments
            speaker_segments_sorted = sorted(
                speaker_segments,
                key=lambda s: s['local_end'] - s['local_start'],
                reverse=True
            )

            # Use up to 5 segments for robust embedding (or all if fewer)
            # Reduced from 10 to 5 to save GPU memory during embedding extraction
            segments_to_use = speaker_segments_sorted[:min(5, len(speaker_segments_sorted))]

            # Skip very short segments (< 0.5 seconds)
            segments_to_use = [
                s for s in segments_to_use
                if (s['local_end'] - s['local_start']) >= 0.5
            ]

            if not segments_to_use:
                # Fall back to longest segment even if short
                segments_to_use = [speaker_segments_sorted[0]]

            # Extract embeddings
            embeddings = []
            for seg in segments_to_use:
                try:
                    # Create a pyannote Segment object for extraction
                    segment = Segment(start=seg['local_start'], end=seg['local_end'])

                    # Extract embedding using pyannote embedding model
                    # The model expects a dict with 'audio' key containing the file path
                    result = self.embedding_model({
                        'audio': audio_path,
                        'segment': segment
                    })

                    # Pyannote returns a dict with 'embeddings' key
                    if isinstance(result, dict):
                        embedding = result.get('embeddings', result.get('embedding'))
                    else:
                        embedding = result

                    # Convert to numpy array if needed
                    if embedding is None:
                        print(f"  Warning: No embedding in result for {speaker}")
                        continue
                    if torch.is_tensor(embedding):
                        embedding = embedding.cpu().detach().numpy()

                    # Handle case where embedding is 2D (batch dim)
                    if embedding.ndim == 2:
                        embedding = embedding.squeeze(0)

                    embeddings.append(embedding)
                except Exception as e:
                    print(f"  Warning: Could not extract embedding for {speaker} segment {seg['local_start']}-{seg['local_end']}: {e}")
                    continue

            if embeddings:
                # Average all embeddings for this speaker
                avg_embedding = np.mean(embeddings, axis=0)
                # Normalize to unit length for cosine similarity
                avg_embedding = avg_embedding / (np.linalg.norm(avg_embedding) + 1e-8)
                speaker_embeddings[speaker] = avg_embedding
            else:
                print(f"  Warning: No valid embeddings extracted for {speaker}")

        return speaker_embeddings

    def _match_speakers(self, chunk_results: List[Dict]) -> Tuple[List[Dict[str, str]], int]:
        """
        Match speakers across chunks using embedding similarity.

        Args:
            chunk_results: List of chunk results with embeddings

        Returns:
            Tuple of (chunk_to_global_map, global_speaker_count)
            - chunk_to_global_map: List of dicts mapping local to global speaker labels for each chunk
            - global_speaker_count: Total number of unique speakers found
        """
        global_speakers = {}  # global_id -> {"embedding": ndarray, "count": int}
        chunk_to_global_map = []

        for chunk_idx, chunk_result in enumerate(chunk_results):
            local_to_global = {}
            speaker_embeddings = chunk_result['speaker_embeddings']

            for local_speaker, local_embedding in speaker_embeddings.items():
                # Find best matching global speaker
                best_match = None
                best_similarity = self.similarity_threshold

                for global_id, global_data in global_speakers.items():
                    global_embedding = global_data['embedding']

                    # Cosine similarity (embeddings already normalized)
                    similarity = np.dot(local_embedding, global_embedding)

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = global_id

                if best_match:
                    # Existing speaker - map to global ID
                    local_to_global[local_speaker] = best_match

                    # Update global embedding as running average
                    count = global_speakers[best_match]['count']
                    current_avg = global_speakers[best_match]['embedding']
                    new_avg = (current_avg * count + local_embedding) / (count + 1)
                    # Re-normalize
                    new_avg = new_avg / (np.linalg.norm(new_avg) + 1e-8)
                    global_speakers[best_match]['embedding'] = new_avg
                    global_speakers[best_match]['count'] = count + 1

                    print(f"  Chunk {chunk_idx}: {local_speaker} -> {best_match} (similarity: {best_similarity:.3f})")
                else:
                    # New speaker - create global ID
                    new_global_id = f"SPEAKER_{len(global_speakers):02d}"
                    global_speakers[new_global_id] = {
                        'embedding': local_embedding,
                        'count': 1
                    }
                    local_to_global[local_speaker] = new_global_id

                    print(f"  Chunk {chunk_idx}: {local_speaker} -> {new_global_id} (new speaker)")

            chunk_to_global_map.append(local_to_global)

        return chunk_to_global_map, len(global_speakers)

    def _unify_segments(self, chunk_results: List[Dict], chunk_to_global_map: List[Dict[str, str]]) -> List[Dict]:
        """
        Apply global speaker labels to all segments.

        Args:
            chunk_results: List of chunk results with segments
            chunk_to_global_map: List of local->global speaker mappings per chunk

        Returns:
            Unified list of segments with global speaker labels
        """
        unified_segments = []

        for chunk_idx, chunk_result in enumerate(chunk_results):
            mapping = chunk_to_global_map[chunk_idx]

            for seg in chunk_result['segments']:
                local_speaker = seg['speaker']
                global_speaker = mapping.get(local_speaker, local_speaker)

                # Create unified segment (remove local timing)
                unified_segment = {
                    "start": seg['start'],
                    "end": seg['end'],
                    "speaker": global_speaker
                }
                unified_segments.append(unified_segment)

        # Sort by start time
        unified_segments.sort(key=lambda s: s['start'])

        return unified_segments

    def assign_speakers_to_transcription(
        self,
        transcription_segments: List[Dict],
        speaker_segments: List[Dict]
    ) -> List[Dict]:
        """
        Assign speaker labels to transcription segments based on time overlap.

        This method reuses the same algorithm as SpeakerDiarizer for consistency.
        Can be called after diarize_chunked() to assign speakers to transcription.

        Args:
            transcription_segments: List of transcription segments with 'start' and 'end' times
            speaker_segments: List of speaker diarization segments with 'start', 'end', and 'speaker'

        Returns:
            Transcription segments with added 'speaker' field
        """
        print(f"Assigning speakers to {len(transcription_segments)} transcription segments...")

        for trans_seg in transcription_segments:
            # Get the start and end times of the transcription segment
            trans_start = trans_seg.get('start', 0.0)
            trans_end = trans_seg.get('end', 0.0)
            trans_mid = (trans_start + trans_end) / 2

            # Find the speaker segment with maximum overlap
            best_speaker = "UNKNOWN"
            max_overlap = 0

            for spk_seg in speaker_segments:
                spk_start = spk_seg['start']
                spk_end = spk_seg['end']

                # Calculate overlap
                overlap_start = max(trans_start, spk_start)
                overlap_end = min(trans_end, spk_end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = spk_seg['speaker']

                # Alternative: Check if midpoint falls within speaker segment
                # This can be faster and often more accurate
                if spk_start <= trans_mid <= spk_end:
                    best_speaker = spk_seg['speaker']
                    break

            # Assign the speaker to the transcription segment
            trans_seg['speaker'] = best_speaker

        # Count speakers
        unique_speakers = set(seg.get('speaker', 'UNKNOWN') for seg in transcription_segments)
        print(f"Speaker assignment complete. Identified {len(unique_speakers)} unique speakers")

        return transcription_segments
