# Frontend Architecture

## 1. Technology Stack

### Core
- **React 19.0** with TypeScript
- **Vite 6.1** for build tooling and HMR
- **TailwindCSS 3.3** for utility-first styling
- **React Query 5.x** for API state management

### Real-time & API
- **Axios** for HTTP requests
- **Supabase Client** for real-time job updates
- **Server-Sent Events (SSE)** for streaming transcription

### Media
- **FFmpeg.wasm** for browser-based video processing
- **React Player** for video playback

### UI Components
- **Headless UI** for accessible components
- **Heroicons** for icons
- **React Spring** for animations
- **React Markdown** for markdown rendering

### Deployment
- **Netlify** for hosting (automatic deploys from main branch)
- **Docker + Nginx** as alternative

## 2. Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── common/                     # Shared/reusable components
│   │   │   └── ImageModal.tsx          # Modal for image display
│   │   └── features/                   # Feature-specific components
│   │       ├── transcription/          # Main transcription feature
│   │       │   ├── TranscriptionUpload.tsx  # Orchestrator (1500+ lines)
│   │       │   ├── UploadZone.tsx
│   │       │   ├── ProcessingOverlay.tsx
│   │       │   ├── TranscriptSegmentList.tsx
│   │       │   ├── CustomProgressBar.tsx
│   │       │   ├── SubtitleControls.tsx
│   │       │   ├── JumpToTimeModal.tsx
│   │       │   └── SavedTranscriptionsPanel.tsx
│   │       ├── chat/                   # RAG chat interface
│   │       │   └── ChatPanel.tsx
│   │       ├── search/                 # Semantic & visual search
│   │       │   └── SearchPanel.tsx
│   │       ├── summary/                # AI summarization
│   │       │   └── SummaryPanel.tsx
│   │       ├── speakers/               # Speaker management
│   │       │   └── EnrolledSpeakersPanel.tsx
│   │       ├── jobs/                   # Background job UI
│   │       │   ├── JobPanel.tsx
│   │       │   ├── JobList.tsx
│   │       │   ├── JobCard.tsx
│   │       │   └── ShareJobDialog.tsx
│   │       ├── analytics/              # Statistics
│   │       │   └── AnalyticsPanel.tsx
│   │       └── video/                  # Video components
│   ├── hooks/                          # Custom React hooks
│   │   ├── useTranscription.ts         # Core transcription logic
│   │   ├── useVideoPlayer.ts           # Video playback control
│   │   ├── useFileUpload.ts            # File handling
│   │   ├── useSubtitles.ts             # Subtitle generation
│   │   ├── useSummaries.ts             # Summary caching
│   │   ├── useBackgroundJobSubmit.ts   # Job submission
│   │   ├── useJobTracker.ts            # Job status tracking
│   │   ├── useJobStorage.ts            # localStorage persistence
│   │   ├── useSupabaseRealtime.ts      # Real-time updates
│   │   └── useJobNotifications.ts      # Browser notifications
│   ├── services/
│   │   ├── api.ts                      # Axios API client
│   │   └── gcsUpload.ts                # Direct GCS upload
│   ├── lib/
│   │   └── supabase.ts                 # Supabase client setup
│   ├── types/
│   │   ├── job.ts                      # Job type definitions
│   │   └── [other types]
│   ├── utils/
│   │   ├── time.ts                     # Time formatting
│   │   ├── speaker.ts                  # Speaker utilities
│   │   ├── subtitle.ts                 # Subtitle generation
│   │   ├── file.ts                     # File hashing
│   │   ├── ffmpeg.ts                   # FFmpeg integration
│   │   └── animations.ts               # React Spring configs
│   ├── config.ts                       # App configuration
│   ├── App.tsx                         # Root component
│   ├── main.tsx                        # Entry point
│   └── index.css                       # Global styles
├── public/                             # Static assets
├── Dockerfile                          # Docker build
└── nginx.conf                          # Nginx configuration
```

## 3. Key Architectural Patterns

### 3.1. Orchestrator Component Pattern

The main `TranscriptionUpload.tsx` component acts as an orchestrator, managing state and coordinating child components:

```tsx
// Main orchestrator (simplified)
const TranscriptionUpload = () => {
  // Core hooks
  const transcription = useTranscription();
  const videoPlayer = useVideoPlayer();
  const fileUpload = useFileUpload();

  // Feature hooks
  const subtitles = useSubtitles();
  const summaries = useSummaries();
  const jobTracker = useJobTracker();

  return (
    <div className="flex flex-col">
      {/* Upload zone or video player */}
      {!transcription.hasResult ? (
        <UploadZone {...fileUpload} />
      ) : (
        <VideoPlayerSection {...videoPlayer} />
      )}

      {/* Processing overlay */}
      {transcription.isProcessing && (
        <ProcessingOverlay progress={transcription.progress} />
      )}

      {/* Results display */}
      {transcription.hasResult && (
        <>
          <TranscriptSegmentList segments={transcription.segments} />
          <FeaturePanels />
        </>
      )}
    </div>
  );
};
```

### 3.2. Custom Hooks for Separation of Concerns

Each hook encapsulates a specific domain of functionality:

```tsx
// useTranscription.ts - Core transcription logic
export const useTranscription = () => {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);

  const processFile = async (file: File) => {
    setIsProcessing(true);
    // Handle upload and processing
  };

  return {
    segments,
    isProcessing,
    progress,
    processFile,
    // ... more methods
  };
};

// useJobTracker.ts - Background job management
export const useJobTracker = () => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const supabase = useSupabaseRealtime();

  // Subscribe to job updates
  useEffect(() => {
    supabase.subscribeToJobs(setJobs);
  }, []);

  return { jobs, submitJob, cancelJob, retryJob };
};
```

### 3.3. Upload Flow Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         File Selection                               │
│                    (drag-drop or file browser)                       │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Hash Generation (SHA-256)                       │
│                  (for deduplication & caching)                       │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
           ┌───────────────┐              ┌───────────────┐
           │   < 32MB      │              │   >= 32MB     │
           │ Direct Upload │              │  GCS Upload   │
           └───────────────┘              └───────────────┘
                    │                              │
                    │    ┌─────────────────────────┘
                    │    │
                    ▼    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Processing Mode Selection                        │
└─────────────────────────────────────────────────────────────────────┘
                    │                              │
                    ▼                              ▼
           ┌───────────────┐              ┌───────────────┐
           │   Streaming   │              │  Background   │
           │  (Real-time)  │              │    (Job)      │
           └───────────────┘              └───────────────┘
                    │                              │
                    ▼                              ▼
           ┌───────────────┐              ┌───────────────┐
           │  SSE Updates  │              │   Supabase    │
           │               │              │   Real-time   │
           └───────────────┘              └───────────────┘
                    │                              │
                    └──────────────┬───────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Result Display                                │
│              (Transcript, Video Player, Features)                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.4. Real-time Updates with Supabase

```tsx
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js';

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

// useSupabaseRealtime.ts
export const useSupabaseRealtime = (jobId: string) => {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    const channel = supabase
      .channel(`job:${jobId}`)
      .on('postgres_changes', {
        event: 'UPDATE',
        schema: 'public',
        table: 'jobs',
        filter: `id=eq.${jobId}`,
      }, (payload) => {
        setJob(payload.new as Job);
      })
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [jobId]);

  return job;
};
```

## 4. API Integration

### 4.1. Axios Client Setup

```typescript
// services/api.ts
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 3600000, // 1 hour for large uploads
});

// Request interceptor
api.interceptors.request.use((config) => {
  console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
  return config;
});

// Response interceptor with error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Handle various error formats
    const message = error.response?.data?.detail
      || error.response?.data?.message
      || error.message;
    return Promise.reject(new Error(message));
  }
);

export default api;
```

### 4.2. GCS Direct Upload

```typescript
// services/gcsUpload.ts
export const uploadToGCS = async (
  file: File,
  signedUrl: string,
  onProgress?: (percent: number) => void
): Promise<void> => {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed: ${xhr.status}`));
      }
    };

    xhr.open('PUT', signedUrl);
    xhr.setRequestHeader('Content-Type', file.type);
    xhr.send(file);
  });
};
```

## 5. State Management Strategy

### 5.1. Server State (React Query)

Used for API data that needs caching and synchronization:

```tsx
// Fetch transcriptions list
const { data: transcriptions, isLoading } = useQuery({
  queryKey: ['transcriptions'],
  queryFn: () => api.get('/transcriptions/'),
});

// Mutation for transcription
const mutation = useMutation({
  mutationFn: (file: File) => transcribeVideo(file),
  onSuccess: () => {
    queryClient.invalidateQueries(['transcriptions']);
  },
});
```

### 5.2. Local State (useState)

Used for UI state and component-specific data:

```tsx
const [selectedSpeaker, setSelectedSpeaker] = useState<string | null>(null);
const [isPlaying, setIsPlaying] = useState(false);
const [currentTime, setCurrentTime] = useState(0);
```

### 5.3. Persistent State (localStorage)

Used for data that should survive page refreshes:

```tsx
// useJobStorage.ts
export const useJobStorage = () => {
  const [jobs, setJobs] = useState<Job[]>(() => {
    const stored = localStorage.getItem('jobs');
    return stored ? JSON.parse(stored) : [];
  });

  useEffect(() => {
    localStorage.setItem('jobs', JSON.stringify(jobs));
  }, [jobs]);

  return { jobs, addJob, removeJob, updateJob };
};
```

## 6. Component Communication

### 6.1. Props Down, Events Up

```tsx
// Parent passes data and callbacks to children
<TranscriptSegmentList
  segments={segments}
  currentTime={currentTime}
  onSegmentClick={(segment) => seekTo(segment.start)}
  onSpeakerChange={(segmentId, newSpeaker) => updateSpeaker(segmentId, newSpeaker)}
/>
```

### 6.2. Shared Hooks for Cross-Component State

```tsx
// Multiple components can use the same hook
const Component1 = () => {
  const { segments } = useTranscription();
  // ...
};

const Component2 = () => {
  const { segments, updateSegment } = useTranscription();
  // ...
};
```

## 7. Deployment

### 7.1. Netlify Configuration

```toml
# netlify.toml
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  NODE_VERSION = "18"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

### 7.2. Environment Variables

Set in Netlify dashboard:

```
VITE_API_URL=https://REDACTED_BACKEND_URL
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_anon_key
```

### 7.3. Docker Build

```dockerfile
# Multi-stage build
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

## 8. Performance Optimizations

### 8.1. Code Splitting

```tsx
// Lazy load heavy components
const ChatPanel = lazy(() => import('./features/chat/ChatPanel'));
const SearchPanel = lazy(() => import('./features/search/SearchPanel'));

// Use Suspense for loading states
<Suspense fallback={<LoadingSpinner />}>
  <ChatPanel />
</Suspense>
```

### 8.2. Memoization

```tsx
// Memoize expensive computations
const speakerStats = useMemo(() =>
  calculateSpeakerStats(segments),
  [segments]
);

// Memoize components
const SegmentItem = memo(({ segment, onClick }) => (
  // ...
));
```

### 8.3. Virtual List for Long Transcripts

```tsx
// Consider react-window for very long transcripts
import { FixedSizeList } from 'react-window';

const VirtualizedSegmentList = ({ segments }) => (
  <FixedSizeList
    height={600}
    itemCount={segments.length}
    itemSize={80}
  >
    {({ index, style }) => (
      <SegmentItem style={style} segment={segments[index]} />
    )}
  </FixedSizeList>
);
```

## 9. Error Handling

### 9.1. API Errors

```tsx
const handleTranscribe = async (file: File) => {
  try {
    const result = await transcribeVideo(file);
    setSegments(result.segments);
  } catch (error) {
    if (error instanceof Error) {
      toast.error(error.message);
    }
    console.error('Transcription failed:', error);
  }
};
```

### 9.2. Error Boundaries

```tsx
class ErrorBoundary extends Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallback onReset={() => this.setState({ hasError: false })} />;
    }
    return this.props.children;
  }
}
```

## 10. Testing Strategy

### 10.1. Unit Tests (Vitest)

```tsx
// hooks/useTranscription.test.ts
describe('useTranscription', () => {
  it('should initialize with empty segments', () => {
    const { result } = renderHook(() => useTranscription());
    expect(result.current.segments).toEqual([]);
  });
});
```

### 10.2. Component Tests (React Testing Library)

```tsx
// components/UploadZone.test.tsx
describe('UploadZone', () => {
  it('should call onFileSelect when file is dropped', async () => {
    const onFileSelect = vi.fn();
    render(<UploadZone onFileSelect={onFileSelect} />);

    // Simulate file drop
    const file = new File(['content'], 'test.mp4', { type: 'video/mp4' });
    fireEvent.drop(screen.getByRole('button'), { dataTransfer: { files: [file] } });

    expect(onFileSelect).toHaveBeenCalledWith(file);
  });
});
```
