# AI-Subs — Existing Features

A reference of what the platform does today, grouped by area, with the key files.
Versions are the pins in `backend/requirements.txt` / `backend/constraints.txt` and
`frontend/package.json`; check those files when upgrading.

## Core pipeline
Video/audio upload → audio chunking → transcription → diarization → translation →
screenshots → analysis → summaries/chapters. Runs as async jobs on Cloud Run workers.
- Entry/endpoints: `backend/routers/transcription.py`
- Worker + queue: `backend/services/background_worker.py`, `services/job_queue_service.py`, `worker_main.py`

## AI / ML capabilities
| Capability | What it does | Package / model | Key file |
|---|---|---|---|
| Transcription | 99+ languages, auto-detect; `large-v3` (Accurate) or `large-v3-turbo` (Fast) per upload, `small` on CPU locally | faster-whisper 1.2.1 (CTranslate2 4.9.0) | `whisper_models.py`, `dependencies.py` |
| Speaker diarization | Who-spoke-when, auto speaker count, chunked for long files with cross-chunk speaker linking | pyannote.audio 4.0.7, `pyannote/speaker-diarization-community-1`; linking `pyannote/wespeaker-voxceleb-resnet34-LM` | `speaker_diarization.py` |
| Speaker recognition | Voice-print enrollment + identification | pyannote.audio 4.0.7, `pyannote/embedding` | `speaker_recognition.py` |
| Translation | Non-English → English | transformers 4.38.2, MarianMT `Helsinki-NLP/opus-mt-{lang}-en` | `services/translation_service.py` |
| Summarization | Section-based summaries with screenshots | transformers 4.38.2, `facebook/bart-large-cnn` | `services/summarization_service.py` |
| Chapters | Semantic topic-shift detection + LLM titles | sentence-transformers 3.1.1, `BAAI/bge-small-en-v1.5` | `routers/chapters.py` |
| Audio analysis | Events (laughter/applause/music/…) + energy | panns-inference (`Cnn14_mAP=0.431`), librosa 0.11.0 | `audio_analyzer.py`, `services/audio_analysis_service.py` |
| Text embeddings | Transcript retrieval for chat (semantic + lexical) | sentence-transformers 3.1.1, `BAAI/bge-small-en-v1.5` | `services/transcript_embedding_service.py`, `services/chat/text_retrieval.py` |
| Visual index | Scene embeddings + vision-model captions over screenshots | sentence-transformers `clip-ViT-B-32`; captions via xAI `grok-4.3` | `services/image_embedding_service.py`, `services/chat/visual_retrieval.py` |
| Face detection/tagging | Detect faces, tag them to speaker names, index presence across the video | insightface ≥0.7.3 (`buffalo_l`, ArcFace), onnxruntime 1.23.2 | `services/face_service.py` |

Runtime: torch / torchaudio 2.8.0, numpy 2.2.6.

Chapters and Summarization are behind the Flagsmith flags `chapters` and `summary`, off by default. Flags are listed in `KNOWN_FLAGS` (`services/feature_flags.py`, flagsmith 6.3.0); the backend is the only Flagsmith client and caches values (`FLAG_CACHE_SECONDS`), the browser reads them from `GET /api/features` and hides flagged tabs until they load, and flagged routes return 404 while off.

## LLM chat (RAG)
Streaming chat grounded in a video: multi-modal retrieval (text + CLIP visual + captions +
face identity + audio events + speaker context), follow-up resolution, person comparison,
cross-provider vision fallback.
- `backend/routers/chat.py`, `backend/services/chat/`, `backend/llm_providers.py`
- Providers: xAI/Grok (default), Groq, OpenAI, Anthropic, DeepSeek, Ollama.
  Default models are in `backend/config.py` (`*_MODEL`). All providers are called over HTTP with httpx (`llm_providers.py`).

## Outputs
- Subtitles: SRT + VTT, original or translated (`services/subtitle_service.py`)
- Per-segment, dense and silent-gap screenshots (ffmpeg → GCS signed URLs)
- JSON segments (text, translation, speaker, timings, screenshot_url, audio event fields)
- Summaries and chapters (flagged)
- Persisted embeddings: Supabase pgvector (text, CLIP images, ArcFace faces)

## Frontend (user-facing)
React 19, TypeScript 5.7, Vite 6, Tailwind CSS 3, TanStack Query 5, Supabase JS 2 (Realtime); tests with Vitest 3.
- Upload & transcribe (drag-drop, language and model select, resumable GCS upload) — `features/transcription/`
- Transcript view + edit speaker names, filter by speaker, jump-to-time, subtitle download — `TranscriptSegmentList.tsx`, `SubtitleControls.tsx`
- Speaker enrollment + auto-identify — `SpeakerEnrollModal.tsx`, `AutoIdentifyConfirmDialog.tsx`
- Job library: status sections, load/delete/cancel/retry, share links, pagination — `features/jobs/`
- Chat panel with streaming, markdown, timestamp links, sources and person comparison — `features/chat/`
- Summaries + chapters panels (flagged) — `features/summary/`, `features/chapters/`
- Face tagging overlay — `features/face-tagging/`
- Settings (API keys, profile, account), pricing page, Admin dashboard — `components/settings/`, `components/pages/`, `components/admin/`

## Auth, plans & data
Backend: FastAPI 0.104.1, uvicorn 0.24.0, pydantic 2.5.2, supabase-py ≥2.0, stripe ≥10.0.
- Supabase Auth (email/password, JWT cookie), invite-code registration, email verify, password reset — `routers/auth_new.py`, `middleware/auth.py`
- Roles: regular user vs admin (admins bypass quotas)
- Plans: free / pro / studio; monthly transcription + per-file duration + concurrency caps, chat on paid plans — `middleware/quota.py` (`PLAN_LIMITS`), `routers/billing.py`
- Usage metering: `services/usage_meter.py` (`user_usage_monthly` table)
- Stripe billing: checkout, portal, webhooks — `routers/billing.py`
- Tables: `jobs`, `user_profiles`, `user_api_keys` (encrypted), `image_embeddings`, `image_face_presence`, `face_tags`, `invite_codes`, usage/rate-limit/verification tables — `backend/sql/`
- Per-user isolation via RLS.

## Storage
- GCS buckets (`uploads/`, `processed/`, `screenshots/`), 30-day lifecycle, V4 signed URLs (7-day cap) refreshed by a daily cron — `services/gcs_service.py`, `gcs-lifecycle.json`

## Known gaps
No teams or shared workspaces (only read-only share links), no real-time/live transcription,
translation is English-only, no burned-in subtitle video export, no URL/YouTube import.
