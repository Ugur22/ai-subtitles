# Speaker Recognition Guide

This guide explains how to use the automatic speaker recognition system in AI-Subs.

## Overview

The system uses **pyannote.audio** to:
1. **Enroll speakers** - Create voice prints from audio samples
2. **Identify speakers** - Automatically recognize speakers in new videos

## Prerequisites

### 1. Install Dependencies
```bash
cd backend
pip install scipy>=1.11.0
```

### 2. Get Hugging Face Access Token

The pyannote.audio embedding model requires accepting their terms:

1. Create account at https://huggingface.co
2. Accept model conditions at: https://huggingface.co/pyannote/embedding
3. Create access token at: https://huggingface.co/settings/tokens
4. Add to `.env` file:
   ```
   HUGGINGFACE_TOKEN=your_token_here
   ```

## How It Works

### Voice Enrollment Process
```
Audio Sample → Extract Embedding → Store as Voice Print
```

- **Embedding**: A 512-dimensional vector representing voice characteristics
- **Voice Print**: The stored embedding for a known speaker
- **Matching**: Comparing embeddings using cosine similarity

### Speaker Identification Process
```
Unknown Audio → Extract Embedding → Compare with Database → Identify Speaker
```

## Usage

### Method 1: API (Programmatic)

#### 1. Enroll a Speaker

**Option A: Upload Audio File**
```bash
curl -X POST "http://localhost:8000/api/speaker/enroll" \
  -F "speaker_name=John" \
  -F "audio_file=@john_voice.wav"
```

**Option B: Use Existing Video Segment**
```bash
curl -X POST "http://localhost:8000/api/speaker/enroll" \
  -F "speaker_name=Anna" \
  -F "video_hash=abc123" \
  -F "start_time=10.5" \
  -F "end_time=15.2"
```

#### 2. List Enrolled Speakers
```bash
curl "http://localhost:8000/api/speaker/list"
```

Response:
```json
{
  "speakers": [
    {
      "name": "John",
      "samples_count": 1,
      "embedding_shape": [512]
    },
    {
      "name": "Anna",
      "samples_count": 2,
      "embedding_shape": [512]
    }
  ],
  "count": 2
}
```

#### 3. Identify a Speaker
```bash
curl -X POST "http://localhost:8000/api/speaker/identify" \
  -F "video_hash=abc123" \
  -F "start_time=25.0" \
  -F "end_time=30.0" \
  -F "threshold=0.7"
```

Response:
```json
{
  "speaker": "John",
  "confidence": 0.85,
  "threshold": 0.7,
  "identified": true
}
```

#### 4. Auto-Identify All Speakers in a Video
```bash
curl -X POST "http://localhost:8000/api/transcription/abc123/auto_identify_speakers?threshold=0.7"
```

Response:
```json
{
  "success": true,
  "total_segments": 50,
  "identified_segments": 45,
  "message": "Identified 45/50 segments"
}
```

#### 5. Remove a Speaker
```bash
curl -X DELETE "http://localhost:8000/api/speaker/John"
```

### Method 2: Python Script

```python
from speaker_recognition import SpeakerRecognitionSystem

# Initialize
sr_system = SpeakerRecognitionSystem()

# Enroll a speaker
sr_system.enroll_speaker("John", "path/to/john_voice.wav")

# Or enroll from specific segment
sr_system.enroll_speaker("Anna", "path/to/video.mp4", start_time=10.5, end_time=15.2)

# List enrolled speakers
speakers = sr_system.list_speakers()
print(f"Enrolled speakers: {speakers}")

# Identify a speaker
speaker, confidence = sr_system.identify_speaker(
    "path/to/unknown_voice.wav",
    threshold=0.7
)

if speaker:
    print(f"Identified: {speaker} (confidence: {confidence:.2f})")
else:
    print("No match found")
```

## Workflow Example

### Scenario: Weekly Podcast with 2 Hosts

**Step 1: Enroll Hosts (One-time)**
```bash
# Upload Episode 1
# After transcription, identify a segment for each host

# Enroll John (segments 0-5 are John)
curl -X POST "http://localhost:8000/api/speaker/enroll" \
  -F "speaker_name=John" \
  -F "video_hash=episode1_hash" \
  -F "start_time=0.0" \
  -F "end_time=5.0"

# Enroll Anna (segments 15-20 are Anna)
curl -X POST "http://localhost:8000/api/speaker/enroll" \
  -F "speaker_name=Anna" \
  -F "video_hash=episode1_hash" \
  -F "start_time=45.0" \
  -F "end_time=50.0"
```

**Step 2: Auto-Identify Future Episodes**
```bash
# Upload Episode 2
# After transcription completes, auto-identify

curl -X POST "http://localhost:8000/api/transcription/episode2_hash/auto_identify_speakers?threshold=0.7"
```

Result: All segments automatically labeled as "John" or "Anna"!

## Parameters & Tuning

### Threshold (Similarity Score)

- **Range**: 0.0 to 1.0
- **Default**: 0.7
- **Meaning**: Minimum similarity required for identification

**Recommended values:**
- `0.9` - Very strict (low false positives, may miss some matches)
- `0.7` - Balanced (recommended)
- `0.5` - Lenient (more matches, higher false positives)

### Enrollment Tips

**How much audio is needed?**
- Minimum: 3-5 seconds of clear speech
- Recommended: 10-30 seconds
- Multiple enrollments: Improves accuracy

**Best practices:**
1. Use clear, noise-free audio
2. Enroll with speech (not silence or music)
3. Enroll multiple times for better accuracy
4. Use different speaking styles if possible

Example - Multiple enrollments:
```bash
# First enrollment
curl -X POST "http://localhost:8000/api/speaker/enroll" \
  -F "speaker_name=John" \
  -F "video_hash=video1" \
  -F "start_time=10.0" \
  -F "end_time=15.0"

# Second enrollment (improves accuracy)
curl -X POST "http://localhost:8000/api/speaker/enroll" \
  -F "speaker_name=John" \
  -F "video_hash=video1" \
  -F "start_time=45.0" \
  -F "end_time=50.0"
```

The system automatically averages the embeddings for better accuracy.

## Technical Details

### Voice Embeddings

**What is an embedding?**
- A 512-dimensional vector representing voice characteristics
- Captures: pitch, tone, timbre, speaking patterns
- Similar voices → similar embeddings

**Example:**
```python
# John's voice embedding (simplified)
[0.23, -0.15, 0.67, ..., 0.42]  # 512 numbers

# Anna's voice embedding (simplified)
[0.89, 0.34, -0.21, ..., 0.11]  # 512 numbers

# Unknown voice (actually John)
[0.24, -0.14, 0.68, ..., 0.41]  # Very similar to John!
```

### Similarity Calculation

Uses **cosine similarity**:
```python
from scipy.spatial.distance import cosine

similarity = 1 - cosine(embedding1, embedding2)

# similarity = 1.0 → Identical
# similarity = 0.0 → Completely different
```

### Database Storage

Speaker voice prints are stored in `speaker_database.json`:

```json
{
  "John": {
    "embedding": [0.23, -0.15, 0.67, ...],
    "samples_count": 2
  },
  "Anna": {
    "embedding": [0.89, 0.34, -0.21, ...],
    "samples_count": 1
  }
}
```

## Troubleshooting

### "Error loading embedding model"

**Solution:**
1. Accept model terms at https://huggingface.co/pyannote/embedding
2. Add `HUGGINGFACE_TOKEN` to `.env`
3. Restart backend

### Low Identification Accuracy

**Try:**
1. Lower threshold (e.g., 0.6 instead of 0.7)
2. Enroll with more/longer audio samples
3. Ensure enrollment audio is clear and noise-free
4. Check that speakers have distinct voices

### "No speakers enrolled"

**Solution:**
Enroll at least one speaker before calling auto-identify.

### Multiple enrollments not improving accuracy

This is normal if:
- Samples are very similar (same segment repeated)
- Speaker's voice is very consistent

Multiple diverse samples help more than multiple similar samples.

## Privacy & Security

### Data Storage
- Voice prints stored locally in `speaker_database.json`
- No data sent to external servers (except Hugging Face model download)

### Privacy Considerations
- Voice prints are biometric data
- Get consent before enrolling speakers
- Delete speakers when no longer needed

### Deleting Data
```bash
# Remove specific speaker
curl -X DELETE "http://localhost:8000/api/speaker/John"

# Or delete entire database
rm speaker_database.json
```

## Performance

### Speed
- Enrollment: ~1-2 seconds per sample
- Identification: ~0.5-1 second per segment
- Auto-identify 100 segments: ~1-2 minutes

### Accuracy
- Same conditions (good audio): 85-95%
- Different conditions: 70-85%
- Noisy audio: 50-70%

### Limitations
- Requires clear speech (not whispers, singing, etc.)
- Affected by background noise
- May struggle with very similar voices
- Phone quality audio may reduce accuracy

## Integration with UI

You can build a UI for this! Example features:

1. **Enrollment Button** - "Enroll this speaker"
   - User clicks segment
   - Names the speaker
   - Calls `/api/speaker/enroll`

2. **Auto-Identify Button** - "Auto-identify speakers"
   - Calls `/api/transcription/{hash}/auto_identify_speakers`
   - Shows progress/results

3. **Speaker Management** - View/delete enrolled speakers
   - Lists all speakers
   - Shows sample counts
   - Delete option

## Advanced Usage

### Custom Threshold Per Speaker

```python
# In auto_identify_speakers, you can customize:

# Be strict for John (he has a common voice)
if best_speaker == "John":
    threshold = 0.85
# Be lenient for Anna (she has a distinctive voice)
elif best_speaker == "Anna":
    threshold = 0.65
```

### Re-enrollment

To update a speaker's voice print:
```python
# Option 1: Just enroll again (it averages)
sr_system.enroll_speaker("John", "new_sample.wav")

# Option 2: Remove and re-enroll
sr_system.remove_speaker("John")
sr_system.enroll_speaker("John", "new_sample.wav")
```

## Summary

✅ **What you get:**
- Automatic speaker identification
- One-time enrollment
- Works across all future videos
- Privacy-friendly (local storage)

✅ **Best for:**
- Regular speakers (podcasts, meetings)
- Clear audio
- Distinct voices

❌ **Not ideal for:**
- One-time speakers
- Noisy environments
- Very similar voices
- Real-time processing (adds latency)

**Your current manual approach is still valuable** - use this as an enhancement for regular speakers!
