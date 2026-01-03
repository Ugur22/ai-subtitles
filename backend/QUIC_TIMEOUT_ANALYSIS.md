# QUIC Protocol Timeout Analysis

## Error Observed
```
ERR_QUIC_PROTOCOL_ERROR.QUIC_TOO_MANY_RTOS 200 (OK)
TypeError: network error
```

## Root Cause

The **transcription completed successfully** on the backend (logs show it finished), but the SSE (Server-Sent Events) streaming connection between frontend and Cloud Run timed out due to **QUIC protocol retransmission timeouts**.

QUIC requires periodic data to keep connections alive. When no SSE events are sent for extended periods (60-120+ seconds), the connection drops.

---

## Problem Areas in `/routers/transcription.py`

### 1. Whisper Transcription (Lines 1902-1905)
```python
segments, info = get_local_whisper_model().transcribe(
    chunk_path,
    **transcribe_params
)
```
- **Duration**: 2-10+ minutes per 5-minute audio chunk
- **Heartbeats**: None during processing
- **Impact**: HIGH - Main bottleneck

### 2. Translation (Line 1980)
```python
formatted_segments = translate_segments(formatted_segments, normalized_lang)
```
- **Duration**: 1-5 minutes for hundreds of segments
- **Heartbeats**: None
- **Impact**: MEDIUM

### 3. Speaker Diarization (Lines 2095-2101)
```python
formatted_segments = add_speaker_labels(
    audio_path=diarization_audio,
    segments=formatted_segments,
    ...
)
```
- **Duration**: 2-5 minutes
- **Heartbeats**: None
- **Impact**: MEDIUM

### 4. Audio Analysis (Lines 2120-2128)
```python
formatted_segments = AudioAnalysisService.analyze_segments(...)
formatted_segments = AudioAnalysisService.analyze_silent_segments(...)
```
- **Duration**: 1-3 minutes
- **Heartbeats**: None
- **Impact**: MEDIUM

### 5. Gap Detection (Lines 2147-2153)
```python
formatted_segments = create_silent_segments_for_gaps(
    segments=formatted_segments,
    ...
)
```
- **Duration**: 1-5 minutes (95 gaps detected in your video)
- **Heartbeats**: None
- **Impact**: MEDIUM

---

## Timeline of Your Failed Request

| Time | Stage | Heartbeats |
|------|-------|------------|
| 17:35:00 | Start | Yes |
| 17:35-17:45 | Whisper transcription | **NO** (10 min gap) |
| 17:45-17:48 | Translation + diarization | **NO** (3 min gap) |
| 17:48-17:49 | Gap detection (95 gaps) | Some batched |
| 17:49:48 | **Completed successfully** | N/A |

The connection dropped during one of the long gaps without heartbeats.

---

## Solution Options

### Option A: Background Heartbeat Thread (Recommended)
Run long operations in a thread pool, yield heartbeats every 10-15 seconds while waiting.

**Pros**:
- No changes to service functions
- Clean separation of concerns
- Single place to maintain

**Cons**:
- Slightly more complex threading code

**Implementation**:
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2)

async def run_with_heartbeats(func, emit_func, stage, base_progress, message):
    """Run a blocking function while yielding heartbeats."""
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(executor, func)

    heartbeat_count = 0
    while not future.done():
        await asyncio.sleep(10)  # Heartbeat every 10 seconds
        heartbeat_count += 1
        yield emit_func(stage, base_progress, f"{message} ({heartbeat_count * 10}s)")

    return future.result()
```

### Option B: Granular Progress in Services
Add progress callbacks to each service function.

**Pros**:
- More accurate progress reporting
- Natural integration

**Cons**:
- Requires modifying many files
- Invasive changes to service layer

### Option C: Increase Cloud Run Timeout + HTTP/1.1
Force HTTP/1.1 instead of QUIC, increase timeouts.

**Pros**:
- No code changes
- Quick fix

**Cons**:
- Doesn't fix root cause
- May still timeout on very long videos
- Worse performance than QUIC

**Implementation**: Add to Cloud Run service:
```yaml
annotations:
  run.googleapis.com/ingress: all
  # Force HTTP/1.1
metadata:
  annotations:
    run.googleapis.com/http2: "false"
```

### Option D: Polling Architecture (Major Refactor)
Change from SSE streaming to polling-based status checks.

**Pros**:
- No timeout issues
- Works with any connection type

**Cons**:
- Major frontend + backend refactor
- Worse UX (delayed updates)
- More complex state management

---

## Recommendation

**Option A (Background Heartbeat Thread)** is the best balance of:
- Minimal code changes (only in `transcription.py`)
- Reliable heartbeats every 10-15 seconds
- No changes to service layer
- Maintains real-time SSE updates

The fix would wrap these 5 long-running operations in the heartbeat helper, ensuring the connection never goes silent for more than 15 seconds.

---

## Quick Test

To verify the issue, you can check if shorter videos (< 2 minutes) work fine, since they don't trigger the long processing gaps.
