# Cost Optimization Plans for AI-Subs

This document outlines various strategies to reduce Google Cloud costs for the AI-Subs backend.

## Current Status (January 2026)

- **Spend**: ~€36 in first 11 days (~€100/month projected)
- **Main cost driver**: Cloud Run with NVIDIA L4 GPU (~€0.85/hour)
- **Usage**: 5-15 videos/month, scale-to-zero enabled
- **Applied fix**: `FASTWHISPER_DEVICE=cuda` (GPU now used for Whisper)

## Plan A: GPU-Enabled Local Processing (IMPLEMENTED)

**Status**: Active

**What changed**:
```bash
gcloud run services update ai-subs-backend \
  --update-env-vars="FASTWHISPER_DEVICE=cuda"
```

**Cost impact**:
- Before: ~€36/month (GPU idle during CPU Whisper)
- After: ~€20-25/month (GPU fully utilized, faster processing)
- Savings: ~€15/month

---

## Plan B: External Transcription APIs

**Status**: Ready to implement if more savings needed

### Option 1: Groq Whisper API

**Pros**:
- Already have `GROQ_API_KEY` configured
- 10-15x faster than real-time
- No GPU needed

**Cons**:
- $0.05/minute of audio
- 20 hours of video = ~$60/month

**Implementation**:

1. Create `backend/services/external_transcription_service.py`:
```python
import os
from groq import Groq

class GroqTranscriptionService:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    async def transcribe(self, audio_path: str, language: str = None):
        with open(audio_path, "rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
                language=language,
                response_format="verbose_json"
            )
        return response
```

2. Update `backend/config.py`:
```python
TRANSCRIPTION_PROVIDER: str = os.getenv("TRANSCRIPTION_PROVIDER", "local")  # local, groq, assemblyai
```

3. Update `backend/routers/transcription.py` to route based on provider

---

### Option 2: AssemblyAI (Recommended for Full Migration)

**Pros**:
- $0.01/minute (cheapest)
- Includes speaker diarization (replaces Pyannote)
- Eliminates GPU requirement entirely

**Cons**:
- New API key needed
- Different response format

**Cost comparison** (20 hours/month):
- Current GPU: ~€25/month
- AssemblyAI: ~$12/month (~€11)
- **Savings: ~€14/month**

**Implementation**:

1. Add to `backend/requirements.txt`:
```
assemblyai>=0.20.0
```

2. Create `backend/services/assemblyai_service.py`:
```python
import assemblyai as aai
import os

class AssemblyAIService:
    def __init__(self):
        aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

    async def transcribe_with_diarization(self, audio_url: str):
        config = aai.TranscriptionConfig(
            speaker_labels=True,
            language_detection=True
        )
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_url, config=config)

        return {
            "text": transcript.text,
            "segments": [
                {
                    "start": u.start / 1000,
                    "end": u.end / 1000,
                    "text": u.text,
                    "speaker": u.speaker
                }
                for u in transcript.utterances
            ]
        }
```

3. Add secret to GCP:
```bash
echo -n "YOUR_ASSEMBLYAI_KEY" | gcloud secrets create assemblyai-api-key \
  --data-file=- --project=ai-subs-poc

gcloud run services update ai-subs-backend \
  --set-secrets="ASSEMBLYAI_API_KEY=assemblyai-api-key:latest" \
  --region=us-central1 --project=ai-subs-poc
```

---

### Option 3: OpenAI Whisper API

**Pros**:
- High accuracy
- Well-documented
- Already have `openai` package installed

**Cons**:
- $0.02/minute (middle ground)
- No built-in diarization

**Implementation**:
```python
from openai import OpenAI

client = OpenAI()

def transcribe_with_openai(audio_path: str):
    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json"
        )
    return response
```

---

## Plan C: Remove GPU Entirely

**Status**: Ready if switching to external APIs

**Requirements**:
- Use AssemblyAI for both transcription AND diarization
- Or accept slower CPU-based diarization

**Changes to `backend/deploy.sh`**:
```bash
# Remove these lines:
# --gpu=1 \
# --gpu-type=nvidia-l4 \
# --no-gpu-zonal-redundancy \

# Change resources:
--memory=8Gi \
--cpu=2 \
```

**Changes to `backend/Dockerfile`**:
```dockerfile
# Change FROM line:
FROM python:3.11-slim

# Remove CUDA dependencies
# Remove model pre-downloads (or keep only needed ones)
```

**Expected costs**:
- Cloud Run (no GPU): ~€15-20/month
- AssemblyAI: ~€11/month
- **Total: ~€25-30/month**

---

## Plan D: Serverless Architecture (Long-term)

**Status**: Future consideration

**Concept**: Replace Cloud Run with Cloud Functions for even lower costs.

**Architecture**:
```
User Upload → GCS → Cloud Tasks → Cloud Function (transcription API call) → Supabase
```

**Benefits**:
- Pay only per invocation
- No minimum instance costs
- Automatic scaling

**Estimated costs**:
- Cloud Functions: ~€5/month
- External APIs: ~€11/month
- Storage/DB: ~€10/month
- **Total: ~€25/month**

---

## Cost Comparison Summary

| Plan | Monthly Cost | Processing Speed | Complexity |
|------|--------------|------------------|------------|
| A: GPU Local (current) | ~€20-25 | Fast (GPU) | Already done |
| B1: Groq API | ~€25-35 | Fastest | Medium |
| B2: AssemblyAI | ~€25-30 | Fast | Medium |
| B3: OpenAI API | ~€30-40 | Fast | Medium |
| C: No GPU + AssemblyAI | ~€25-30 | Fast | High |
| D: Serverless | ~€25 | Fast | Very High |

---

## Quick Reference Commands

### Check current config:
```bash
gcloud run services describe ai-subs-backend \
  --region=us-central1 --project=ai-subs-poc \
  --format="yaml(spec.template.spec.containers[0].env)"
```

### Update environment variable:
```bash
gcloud run services update ai-subs-backend \
  --region=us-central1 --project=ai-subs-poc \
  --update-env-vars="VARIABLE=value"
```

### View recent logs:
```bash
gcloud run services logs read ai-subs-backend \
  --region=us-central1 --project=ai-subs-poc --limit=50
```

### Check Cloud Run costs:
```bash
# Open billing console
open "https://console.cloud.google.com/billing/linkedaccount?project=ai-subs-poc"
```

---

## Decision Tree

```
Are costs acceptable (~€20-25/month)?
├── Yes → Keep Plan A (GPU local)
└── No → Do you process >20 hours/month?
    ├── Yes → Plan B2 (AssemblyAI) - best value
    └── No → Plan B1 (Groq) - fastest
```

---

*Last updated: January 2026*
