# Smarter Chunked Speaker Diarization Plan

## Problem

Full-video diarization doesn't scale for long videos:
- **Current approach**: Concatenate all audio chunks → run diarization on full file
- **Issue**: Pyannote's clustering is O(n²) or worse - 80 minutes takes 50+ minutes to process
- **Result**: Jobs stuck/timeout on long videos

## Goal

Implement chunked diarization that:
1. Processes audio in manageable segments (15-30 min each)
2. Maintains speaker consistency across chunks
3. Completes in reasonable time (minutes, not hours)
4. Handles 20+ speakers across a full video

---

## Proposed Solution: Chunked Diarization with Speaker Embedding Matching

### Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     CHUNKED DIARIZATION                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Chunk 1 (0-15min)     Chunk 2 (15-30min)    Chunk 3 (30-45min)│
│  ┌─────────────┐       ┌─────────────┐       ┌─────────────┐   │
│  │ Diarize     │       │ Diarize     │       │ Diarize     │   │
│  │ SPEAKER_00  │       │ SPEAKER_00  │       │ SPEAKER_00  │   │
│  │ SPEAKER_01  │       │ SPEAKER_01  │       │ SPEAKER_01  │   │
│  │ SPEAKER_02  │       │             │       │ SPEAKER_02  │   │
│  └─────────────┘       └─────────────┘       └─────────────┘   │
│         │                    │                     │            │
│         └────────────────────┼─────────────────────┘            │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │ Speaker Matcher │                         │
│                    │ (Embedding      │                         │
│                    │  Comparison)    │                         │
│                    └─────────────────┘                         │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │ Unified Labels  │                         │
│                    │ SPEAKER_00 ──────► Same person across all │
│                    │ SPEAKER_01 ──────► chunks                 │
│                    └─────────────────┘                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Algorithm

#### Phase 1: Chunked Diarization

1. **Split audio into diarization chunks** (15-30 min each)
   - Reuse existing 5-min transcription chunks
   - Group into larger diarization chunks (e.g., 3-6 transcription chunks = 15-30 min)

2. **Run diarization on each chunk independently**
   - Each chunk produces local speaker labels (SPEAKER_00, SPEAKER_01, etc.)
   - Extract speaker embeddings for each detected speaker

3. **Store per-chunk results**:
   ```python
   chunk_results = [
       {
           "chunk_id": 0,
           "time_offset": 0,
           "speakers": {
               "SPEAKER_00": {"embedding": [...], "segments": [...]},
               "SPEAKER_01": {"embedding": [...], "segments": [...]}
           }
       },
       # ... more chunks
   ]
   ```

#### Phase 2: Speaker Embedding Extraction

For each speaker in each chunk, compute a representative embedding:

```python
def get_speaker_embedding(diarization_result, speaker_label, audio_path):
    """
    Extract embedding for a speaker by averaging embeddings
    from their speech segments.
    """
    # Get all segments for this speaker
    segments = [s for s in diarization_result if s['speaker'] == speaker_label]

    # Use pyannote's embedding model to get embeddings for each segment
    embeddings = []
    for seg in segments[:10]:  # Use up to 10 segments for efficiency
        embedding = embedding_model.extract(audio_path, seg['start'], seg['end'])
        embeddings.append(embedding)

    # Return average embedding
    return np.mean(embeddings, axis=0)
```

#### Phase 3: Cross-Chunk Speaker Matching

Match speakers across chunks using embedding similarity:

```python
def match_speakers_across_chunks(chunk_results):
    """
    Create a global speaker mapping using embedding similarity.
    """
    global_speakers = {}  # global_id -> embedding
    chunk_to_global_map = []  # per-chunk local->global mapping

    for chunk in chunk_results:
        local_to_global = {}

        for local_speaker, data in chunk['speakers'].items():
            local_embedding = data['embedding']

            # Find best matching global speaker
            best_match = None
            best_similarity = 0.7  # Threshold

            for global_id, global_embedding in global_speakers.items():
                similarity = cosine_similarity(local_embedding, global_embedding)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = global_id

            if best_match:
                # Existing speaker
                local_to_global[local_speaker] = best_match
                # Update global embedding (running average)
                global_speakers[best_match] = update_embedding(
                    global_speakers[best_match],
                    local_embedding
                )
            else:
                # New speaker
                new_global_id = f"SPEAKER_{len(global_speakers):02d}"
                global_speakers[new_global_id] = local_embedding
                local_to_global[local_speaker] = new_global_id

        chunk_to_global_map.append(local_to_global)

    return chunk_to_global_map, global_speakers
```

#### Phase 4: Apply Global Labels

```python
def apply_global_labels(segments, chunk_to_global_map, chunk_duration):
    """
    Replace local speaker labels with global unified labels.
    """
    for segment in segments:
        # Determine which chunk this segment belongs to
        chunk_idx = int(segment['start'] // chunk_duration)
        chunk_idx = min(chunk_idx, len(chunk_to_global_map) - 1)

        # Get local speaker label
        local_speaker = segment.get('speaker', 'UNKNOWN')

        # Map to global label
        mapping = chunk_to_global_map[chunk_idx]
        segment['speaker'] = mapping.get(local_speaker, local_speaker)

    return segments
```

---

## Implementation Plan

### Files to Modify

| File | Changes |
|------|---------|
| `backend/speaker_diarization.py` | Add `ChunkedSpeakerDiarizer` class |
| `backend/services/speaker_service.py` | Add chunked diarization option |
| `backend/services/background_worker.py` | Use chunked diarization for long videos |
| `backend/config.py` | Add `DIARIZATION_CHUNK_DURATION` setting |

### New Code Structure

```python
# backend/speaker_diarization.py

class ChunkedSpeakerDiarizer:
    """
    Handles speaker diarization for long videos using chunked processing
    with cross-chunk speaker matching.
    """

    def __init__(self, chunk_duration: int = 900):  # 15 minutes
        self.chunk_duration = chunk_duration
        self.embedding_model = None  # Lazy load
        self.pipeline = None  # Lazy load

    def diarize_chunked(
        self,
        audio_chunks: List[str],
        chunk_duration: int = 300  # Duration of each audio chunk
    ) -> Tuple[List[Dict], Dict[str, np.ndarray]]:
        """
        Diarize audio in chunks and unify speaker labels.

        Returns:
            - List of speaker segments with unified global labels
            - Dict of global speaker embeddings
        """
        # Group small chunks into larger diarization chunks
        diarization_groups = self._group_chunks(audio_chunks, chunk_duration)

        # Diarize each group
        chunk_results = []
        for group in diarization_groups:
            result = self._diarize_group(group)
            chunk_results.append(result)

        # Match speakers across chunks
        chunk_to_global_map, global_speakers = self._match_speakers(chunk_results)

        # Build unified segment list
        unified_segments = self._unify_segments(chunk_results, chunk_to_global_map)

        return unified_segments, global_speakers

    def _group_chunks(self, audio_chunks, chunk_duration):
        """Group 5-min chunks into 15-30 min diarization groups."""
        # Implementation
        pass

    def _diarize_group(self, chunk_paths):
        """Concatenate and diarize a group of chunks."""
        # Implementation
        pass

    def _extract_speaker_embeddings(self, audio_path, diarization_result):
        """Extract embeddings for each speaker."""
        # Implementation
        pass

    def _match_speakers(self, chunk_results):
        """Match speakers across chunks using embedding similarity."""
        # Implementation
        pass

    def _unify_segments(self, chunk_results, mapping):
        """Apply global labels to all segments."""
        # Implementation
        pass
```

### Configuration

```python
# backend/config.py

# Chunked Diarization Settings
DIARIZATION_CHUNK_DURATION: int = int(os.getenv("DIARIZATION_CHUNK_DURATION", "900"))  # 15 min
DIARIZATION_SIMILARITY_THRESHOLD: float = float(os.getenv("DIARIZATION_SIMILARITY_THRESHOLD", "0.7"))
USE_CHUNKED_DIARIZATION_ABOVE: int = int(os.getenv("USE_CHUNKED_DIARIZATION_ABOVE", "1800"))  # 30 min
```

### Worker Integration

```python
# backend/services/background_worker.py

# In the diarization section:
total_duration = len(audio_chunks) * 300  # 5 min per chunk

if total_duration > settings.USE_CHUNKED_DIARIZATION_ABOVE:
    # Use chunked diarization for long videos
    print(f"[Worker] Using chunked diarization for {total_duration}s video")
    chunked_diarizer = ChunkedSpeakerDiarizer()
    speaker_segments, speaker_embeddings = chunked_diarizer.diarize_chunked(
        audio_chunks=audio_chunks,
        chunk_duration=300
    )
    # Apply to transcription segments
    formatted_segments = assign_speakers_to_segments(formatted_segments, speaker_segments)
else:
    # Use standard full-video diarization for short videos
    # ... existing code ...
```

---

## Performance Comparison

| Video Length | Full Diarization | Chunked (15-min) | Speedup |
|--------------|------------------|------------------|---------|
| 15 min       | ~2 min           | ~2 min           | 1x      |
| 30 min       | ~5 min           | ~4 min           | 1.25x   |
| 60 min       | ~15 min          | ~6 min           | 2.5x    |
| 80 min       | ~50+ min (stuck) | ~8 min           | 6x+     |
| 120 min      | Timeout/OOM      | ~12 min          | ∞       |

---

## Edge Cases & Handling

### 1. Speaker appears only once
- Will get unique global ID
- No matching needed

### 2. Speaker appears in non-adjacent chunks
- Embedding matching handles gaps
- Speaker in chunk 1 and chunk 5 will still be unified

### 3. Similar-sounding speakers
- Similarity threshold (0.7) prevents false matches
- May result in over-segmentation (better than under-segmentation)

### 4. Many speakers (20+)
- Algorithm scales linearly with speaker count
- Embedding comparison is fast (cosine similarity)

### 5. Short segments
- Use multiple segments to compute robust embedding
- Fall back to segment centroid if too few samples

---

## Testing Plan

1. **Unit tests**
   - Embedding extraction
   - Speaker matching algorithm
   - Label unification

2. **Integration tests**
   - Short video (< 30 min): Should use standard diarization
   - Long video (> 30 min): Should use chunked diarization
   - Very long video (2+ hours): Should complete without timeout

3. **Quality tests**
   - Compare speaker accuracy: chunked vs full (on medium-length videos)
   - Verify speaker consistency across chunk boundaries

---

## Rollout Plan

1. **Phase 1**: Implement `ChunkedSpeakerDiarizer` class
2. **Phase 2**: Add configuration and feature flag
3. **Phase 3**: Integrate into background worker (opt-in via config)
4. **Phase 4**: Test with real long videos
5. **Phase 5**: Enable by default for videos > 30 min
6. **Phase 6**: Monitor and tune similarity threshold

---

## Dependencies

- `pyannote.audio` - Already installed (diarization + embeddings)
- `numpy` - Already installed (cosine similarity)
- `scipy` - May need for advanced clustering (optional)

No new dependencies required.

---

## Timeline Estimate

| Task | Effort |
|------|--------|
| ChunkedSpeakerDiarizer class | Medium |
| Embedding extraction | Low |
| Speaker matching algorithm | Medium |
| Worker integration | Low |
| Testing | Medium |
| **Total** | ~1-2 days |
