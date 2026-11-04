# Architecture

Detailed architecture documentation for AI-Subs. For resource names, secrets, scheduler jobs and quotas see [GCP_OPERATIONS.md](GCP_OPERATIONS.md); `backend/deploy.sh` is the source of truth for deployed resources.

## System Overview

The API runs on a cheap CPU Cloud Run service. Anything heavy (transcription, diarization, embeddings) runs in a separate GPU Cloud Run Job that the API triggers per upload.

```mermaid
flowchart LR
    subgraph Client["Browser · Netlify"]
        UI("React UI<br/>axios · cookie auth")
        RT("Supabase Realtime<br/>client")
    end

    subgraph Service["API · Cloud Run · CPU"]
        MW("Middleware<br/>auth · CSRF · quota · rate limit")
        Routers("Routers<br/>jobs · upload · chat · speaker<br/>video · face tags · chapters<br/>keys · billing · admin")
        Disp("Job dispatcher")
    end

    subgraph Worker["GPU worker · Cloud Run Job · L4"]
        BW("worker_main.py<br/>BackgroundWorker")
        WH("faster-whisper<br/>large-v3")
        PY("pyannote<br/>chunked diarization")
        EMB("Sentence Transformers<br/>text + caption embeddings")
        CL("CLIP<br/>image embeddings")
        PN("PANNs + wav2vec2<br/>audio events · emotion")
        MT("MarianMT<br/>translation")
    end

    subgraph Data["Data"]
        PG[("Supabase Postgres<br/>pgvector")]
        SBRT("Supabase Realtime")
        GCS[("Cloud Storage<br/>media · screenshots")]
    end

    LLM("LLM providers<br/>Grok (default) · Groq · OpenAI<br/>Anthropic · DeepSeek · Ollama")
    Sched(["Cloud Scheduler"])

    UI --> MW --> Routers
    UI -. signed URL upload .-> GCS
    Routers <--> PG
    Routers --> Disp -->|run_job| BW
    BW --> WH & PY & EMB & CL & PN & MT
    BW <--> GCS
    BW -->|results| PG
    PG --> SBRT -.->|live progress| RT
    Routers -->|RAG chat| LLM
    Sched -->|check-stale · URL refresh| Routers

    classDef app fill:#0f2a3d,stroke:#38a3d8,color:#e6f4fb,stroke-width:1.5px
    classDef gpu fill:#3d2a10,stroke:#f0a030,color:#fdf0dc,stroke-width:1.5px
    classDef data fill:#2c1f45,stroke:#a56cf0,color:#f1e8fd,stroke-width:1.5px
    classDef ai fill:#1f3314,stroke:#7cc043,color:#eaf7dc,stroke-width:1.5px
    classDef misc fill:#2b2f36,stroke:#8b95a5,color:#eef0f3,stroke-width:1.5px

    class UI,RT,MW,Routers,Disp app
    class BW,WH,PY,EMB,CL,PN,MT gpu
    class PG,SBRT,GCS data
    class LLM ai
    class Sched misc
    style Client fill:none,stroke:#38a3d8,stroke-dasharray:4 3
    style Service fill:none,stroke:#38a3d8,stroke-dasharray:4 3
    style Worker fill:none,stroke:#f0a030,stroke-dasharray:4 3
    style Data fill:none,stroke:#a56cf0,stroke-dasharray:4 3
```

## Background Job Flow

How a video is processed:

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant GCS as Cloud Storage
    participant API as FastAPI (CPU service)
    participant SB as Supabase
    participant W as Worker (GPU Cloud Run Job)

    U->>FE: Upload video
    FE->>API: Request signed upload URL
    API-->>FE: Signed GCS URL
    FE->>GCS: Direct upload (bypasses Cloud Run request size limit)

    FE->>API: POST /api/jobs/submit
    API->>SB: Insert job (pending)
    API->>W: run_job (worker_main, job_id)
    API-->>FE: Job ID

    FE->>SB: Subscribe to job updates (Realtime)

    W->>SB: Mark processing, send heartbeats
    W->>GCS: Read media
    W->>W: Transcribe, diarize, screenshots,<br/>embeddings, translation, audio analysis
    W->>GCS: Write screenshots
    W->>SB: Write results + embeddings, mark completed
    SB-->>FE: Realtime: completed

    FE->>API: GET /api/jobs/{id}
    API-->>FE: Full results
```

The worker exits with a `gpu_unavailable` failure if CUDA is missing, instead of silently falling back to CPU.

**Stale-job recovery.** Cloud Scheduler calls `POST /api/jobs/check-stale` every 5 minutes. Jobs in `processing` with no heartbeat for 90s, or `pending` for over 600s, are recovered through the same dispatch path as a manual retry.

## Multi-Modal RAG Chat

How chat builds context from the transcript, screenshots and audio events:

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as FastAPI
    participant SB as Supabase (pgvector)
    participant LLM as LLM Provider

    U->>FE: "What did the person in blue say about the project?"
    FE->>API: POST /api/chat/

    API->>SB: Text retrieval (semantic + lexical)
    SB-->>API: Transcript segments
    opt Visual question
        API->>SB: Visual search (CLIP / caption embeddings)
        SB-->>API: Matching screenshots
    end
    opt Audio question
        API->>SB: Audio event search
        SB-->>API: Sound events
    end

    API->>API: Merge and build multi-modal context
    API->>LLM: Query with context (user's own key if set)
    LLM-->>API: Generated response

    API-->>FE: Answer + sources + screenshots
    FE-->>U: Display response
```

Retrieval lives in `backend/routers/chat.py` (`_retrieve_text_context`, `_retrieve_visual_context`, `_retrieve_audio_context`). Every search is scoped to the owner of the video.

## Speaker Recognition Flow

Diarization (pyannote, in the worker) labels speakers generically (`SPEAKER_00`, ...). Users can enroll a voice under a name, and later segments are matched against saved voiceprints:

```mermaid
flowchart LR
    subgraph Enrollment["Speaker Enrollment"]
        A[Audio sample] --> B[Extract 512-d voice embedding]
        B --> C[(speaker_voiceprints<br/>Supabase pgvector)]
    end

    subgraph Recognition["Speaker Identification"]
        D[Audio segment] --> E[Extract embedding]
        E --> F[search_speaker_voiceprints_by_embedding<br/>cosine similarity, per user]
        F --> G{Similarity >= threshold<br/>default 0.7?}
        G -->|Yes| H[Assign speaker name]
        G -->|No| I[Keep generic label]
    end

    C -.-> F
```

Voiceprints are stored in Supabase rather than on local disk, because Cloud Run's filesystem is wiped on scale-to-zero (migration `011`). The code is `backend/speaker_recognition.py`, exposed by `routers/speaker.py`.

## Search Indexes

All vectors live in Supabase pgvector and are scoped to their owner (migrations `009`, `010`, `017`).

| Index | Content | Dimensions |
|-------|---------|-----------|
| Transcript | Segment embeddings (`BAAI/bge-small-en-v1.5`) | 384 |
| Image | Screenshot embeddings (CLIP `clip-ViT-B-32`) | CLIP |
| Caption | Vision-model captions, embedded per sentence | 384 |
| Audio events | PANNs events with timestamps | 384 |
| Face tags | Tagged faces and per-image face presence | 512 |
| Voiceprints | Enrolled speaker embeddings | 512 |

Schemas are in `backend/sql/` and `backend/sql/migrations/`.

## Local Mode

`LOCAL_MODE=true` swaps only the storage and dispatch layers: `LocalStorageService` replaces GCS, and `LocalDetachedJobDispatcher` runs `worker_main` as a local subprocess instead of a Cloud Run Job. Supabase is always real. `LOCAL_MODE` cannot be combined with `ENABLE_GCS_UPLOADS`.

## Deployment Stack

| Component | Service | Purpose |
|-----------|---------|---------|
| Frontend | Netlify | Static React build, deployed from main; calls the backend directly via `VITE_API_URL` |
| API | Cloud Run service `ai-subs-backend` (CPU) | FastAPI: auth, jobs, upload URLs, search, chat |
| Worker | Cloud Run Job `ai-subs-worker` (1x L4 GPU) | Transcription, diarization, embeddings |
| Database | Supabase Postgres | Jobs, users, transcripts, pgvector indexes |
| Realtime | Supabase Realtime | Live job progress in the browser |
| Storage | Google Cloud Storage | Videos and screenshots |
| Scheduling | Cloud Scheduler | `check-stale` (5 min), screenshot URL refresh (daily) |

## Data Flow

### Transcription Flow

1. **Upload**: File uploaded directly to GCS via signed URL
2. **Job Creation**: Supabase record created with `pending` status, worker job dispatched
3. **Processing**: The GPU worker reads the media from GCS and runs faster-whisper
4. **Diarization**: Chunked pyannote identifies speakers
5. **Storage**: Results and job status saved to Supabase
6. **Notification**: Realtime update sent to the frontend via Supabase

### Search Indexing Flow

All steps run in the worker as part of the job:

1. **Text**: Transcript segments embedded with Sentence Transformers → pgvector
2. **Visual**: Screenshots extracted → CLIP embeddings and vision captions (embedded per sentence) → pgvector
3. **Audio**: PANNs analyzes audio events → stored with timestamps
4. **Faces**: Face tags and presence are handled through `routers/face_tags.py`

### Chat Query Flow

1. **Query**: User question received
2. **Search**: Text retrieval, plus visual and audio retrieval when the question calls for them
3. **Context**: Results merged into one context block
4. **Generation**: The configured LLM provider generates a response
5. **Response**: Answer returned with source references
