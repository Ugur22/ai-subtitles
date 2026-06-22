# AI-Subs — Existing Features

A reference of what the platform does today, grouped by area, with the key files.

## Core pipeline
Video/audio upload → audio chunking → transcription → diarization → translation →
screenshots → analysis → summaries/chapters. Runs as async jobs on Cloud Run workers.
- Entry/endpoints: `backend/routers/transcription.py`
- Worker + queue: `backend/services/background_worker.py`, `services/job_queue_service.py`, `worker_main.py`

## AI / ML capabilities
| Capability | What it does | Key file |
|---|---|---|
| Transcription | Faster-Whisper, 99+ languages, auto-detect | `dependencies.py`, `routers/transcription.py` |
| Speaker diarization | pyannote 3.1, who-spoke-when, auto speaker count | `speaker_diarization.py` |
| Translation | MarianMT (Helsinki-NLP), non-English → English | `services/translation_service.py` |
| Summarization | BART, section-based summaries with screenshots | `services/summarization_service.py` |
| Chapters | Semantic topic-shift detection + LLM titles | `routers/chapters.py` |
| Audio analysis* | PANNs events (laughter/applause/…) + wav2vec2 emotion + energy | `audio_analyzer.py` |
| Text search | Semantic (MiniLM) + lexical, neighbor expansion | `vector_store.py` |
| Visual search | CLIP scene embeddings over screenshots | `services/image_embedding_service.py` |
| Face detection/tagging | InsightFace (ArcFace), tag faces to speaker names | `services/face_service.py` |
| Speaker recognition* | Voice-print enrollment + identification | `speaker_recognition.py` |
\* behind feature flags / partially wired.

## LLM chat (RAG)
Streaming chat grounded in a video: multi-modal retrieval (text + CLIP visual + face
identity + speaker context), follow-up resolution, cross-provider vision fallback.
- `backend/routers/chat.py`, `backend/llm_providers.py`
- Providers: Groq (default), xAI/Grok, OpenAI, Anthropic, DeepSeek, Ollama.

## Outputs
- Subtitles: SRT + VTT (`services/subtitle_service.py`)
- Per-segment + silent-gap screenshots (ffmpeg → GCS signed URLs)
- JSON segments (text, translation, speaker, timings, screenshot_url, audio/emotion fields)
- Summaries and chapters
- Persisted embeddings: ChromaDB (text), pgvector (CLIP images, ArcFace faces)

## Frontend (user-facing)
- Upload & transcribe (drag-drop, language select, background/local) — `features/transcription/`
- Transcript view + edit speaker names, filter by speaker, jump-to-time, SRT download — `TranscriptSegmentList.tsx`, `SubtitleControls.tsx`
- Job library: status sections, load/delete/cancel, pagination — `features/jobs/JobPanel.tsx`
- Search: text (semantic toggle) + visual tabs — `features/search/`
- Chat panel with streaming + markdown + timestamp links — `features/chat/ChatPanel.tsx`
- Summaries + chapters panels — `features/summary/`, `features/chapters/`
- Speaker management + enrollment, face tagging overlay — `features/speakers/`, `features/face-tagging/`
- Settings (API keys, profile, account), Admin dashboard — `components/settings/`, `components/admin/`

## Auth, plans & data
- Supabase Auth (email/password, JWT cookie), invite-code registration, email verify, password reset — `routers/auth_new.py`, `middleware/auth.py`
- Roles: regular user vs admin (admins bypass quotas)
- Plans: free / pro / studio; monthly transcription + per-file duration + concurrency caps — `middleware/quota.py`, `routers/billing.py`
- Usage metering: `services/usage_meter.py` (`user_usage_monthly` table)
- Stripe billing: checkout, portal, webhooks — `routers/billing.py`
- Tables: `jobs`, `user_profiles`, `user_api_keys` (encrypted), `image_embeddings`, `image_face_presence`, `face_tags`, `invite_codes`, usage/rate-limit/verification tables — `backend/sql/`
- Per-user isolation via RLS.

## Storage
- GCS buckets (`uploads/`, `processed/`, `screenshots/`), 30-day lifecycle, V4 signed URLs (7-day cap) refreshed by a daily cron — `services/gcs_service.py`, `gcs-lifecycle.json`

## Known gaps
No sharing/teams, no real-time/live transcription, translation is English-only,
no burned-in subtitle video export, no URL/YouTube import, analytics panel is stubbed.
