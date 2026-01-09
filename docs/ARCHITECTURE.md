# Architecture

Detailed architecture documentation for AI-Subs.

## System Overview

```mermaid
flowchart TB
    subgraph Frontend["Frontend (React + TypeScript)"]
        UI[UI Components]
        VP[Video Player]
        API[API Client]
        RT[Supabase Realtime]
    end

    subgraph Cloud["Cloud Services"]
        GCS[(GCS Bucket)]
        SB[(Supabase)]
        FS[(Firestore)]
    end

    subgraph Backend["Backend (FastAPI on Cloud Run)"]
        subgraph Routers["API Routers"]
            TR[Transcription]
            SR[Speaker]
            CR[Chat]
            VR[Video]
            UR[Upload]
            JR[Jobs]
        end

        subgraph Services["Services Layer"]
            AS[Audio Service]
            VS[Video Service]
            SS[Speaker Service]
            GS[GCS Service]
            JS[Job Queue]
            AAS[Audio Analysis]
        end

        VDB[(ChromaDB)]
    end

    subgraph ML["ML Models"]
        WH[Faster Whisper]
        PY[Pyannote Audio]
        EMB[Sentence Transformers]
        CL[CLIP]
        PN[PANNs]
    end

    subgraph LLM["LLM Providers"]
        OL[Ollama]
        GRQ[Groq]
        OA[OpenAI]
        AN[Anthropic]
        GRK[Grok]
    end

    UI --> API
    VP --> API
    RT <--> SB
    API <--> TR & SR & CR & VR & UR & JR

    UR --> GS --> GCS
    JR --> JS --> SB
    TR --> AS --> WH
    SR --> SS --> PY
    CR --> VDB --> EMB & CL
    CR --> LLM
    VR --> VS
    AAS --> PN

    TR --> FS
    JR --> SB
```

## Background Job Flow

How large files are processed asynchronously:

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant GCS as Cloud Storage
    participant API as FastAPI
    participant SB as Supabase
    participant WH as Whisper

    U->>FE: Upload Large Video
    FE->>API: GET /api/upload/signed-url
    API-->>FE: Signed GCS URL
    FE->>GCS: Direct Upload (bypasses 32MB limit)
    GCS-->>FE: Upload Complete

    FE->>API: POST /api/jobs/submit
    API->>SB: Create Job (pending)
    API-->>FE: Job ID

    loop Poll Status
        FE->>SB: Subscribe to job updates
        SB-->>FE: Status: processing
    end

    API->>GCS: Stream Audio
    API->>WH: Transcribe
    WH-->>API: Segments
    API->>SB: Update Job (completed)
    SB-->>FE: Status: completed

    FE->>API: GET /api/jobs/{id}
    API-->>FE: Full Results
```

## Multi-Modal RAG Chat

How the chat system combines text, images, and audio for context-aware answers:

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as FastAPI
    participant VDB as ChromaDB
    participant LLM as LLM Provider

    U->>FE: "What did the person in blue say about the project?"
    FE->>API: POST /api/chat/

    par Parallel Search
        API->>VDB: Text Semantic Search
        VDB-->>API: Relevant Transcript Segments
    and
        API->>VDB: Visual Search (CLIP)
        VDB-->>API: Matching Screenshots
    and
        API->>VDB: Audio Event Search
        VDB-->>API: Sound Events
    end

    API->>API: Merge & Rank Results
    API->>API: Build Multi-Modal Context
    API->>LLM: Query with Context
    LLM-->>API: Generated Response

    API-->>FE: Answer + Sources + Screenshots
    FE-->>U: Display Response
```

## Speaker Recognition Flow

How speakers are enrolled and identified:

```mermaid
flowchart LR
    subgraph Enrollment["Speaker Enrollment"]
        A[Upload Audio] --> B[Extract Embedding]
        B --> C[Store in Database]
    end

    subgraph Recognition["Speaker Identification"]
        D[New Audio Segment] --> E[Extract Embedding]
        E --> F[Compare with Known Speakers]
        F --> G{Match Found?}
        G -->|Yes| H[Assign Speaker Name]
        G -->|No| I[Keep Generic Label]
    end

    C -.-> F
```

## Deployment Stack

| Component | Service | Purpose |
|-----------|---------|---------|
| Frontend | Netlify | Automatic deploys from main branch |
| Backend | Google Cloud Run | Containerized FastAPI with GPU |
| Database | Firestore | Transcription metadata storage |
| Job Queue | Supabase | Background processing & real-time |
| Storage | Google Cloud Storage | Video and screenshot files |
| Vector DB | ChromaDB | Semantic search embeddings |

## Data Flow

### Transcription Flow

1. **Upload**: File uploaded directly to GCS via signed URL
2. **Job Creation**: Supabase record created with `pending` status
3. **Processing**: Backend streams audio from GCS, runs Whisper
4. **Diarization**: Pyannote identifies speakers (if enabled)
5. **Storage**: Results saved to Firestore, job updated in Supabase
6. **Notification**: Real-time update sent to frontend via Supabase

### Search Indexing Flow

1. **Text**: Transcript segments embedded with Sentence Transformers → ChromaDB
2. **Visual**: Screenshots extracted with MoviePy → CLIP embeddings → ChromaDB
3. **Audio**: PANNs analyzes audio events → Stored with timestamps

### Chat Query Flow

1. **Query**: User question received
2. **Search**: Parallel search across text, visual, and audio indices
3. **Context**: Top results merged and ranked
4. **Generation**: LLM generates response with context
5. **Response**: Answer returned with source references
