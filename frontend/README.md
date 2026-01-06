# AI Subtitles - Frontend

React + TypeScript frontend for the AI Subtitles application. Features a modern, responsive interface for video transcription, subtitle generation, semantic search, visual search, background job processing, and AI-powered chat about video content.

**Live Demo**: [https://REDACTED_FRONTEND_URL](https://REDACTED_FRONTEND_URL)

## Technology Stack

### Core

- **React** 19.0.0 with TypeScript
- **Vite** 6.1.0 - Fast build tool with Hot Module Replacement (HMR)
- **TailwindCSS** 3.3.3 - Utility-first CSS framework
- **React Query** 5.66.8 - Async state management and data fetching
- **React Router DOM** 7.2.0 - Client-side routing

### API & Real-time

- **Axios** 1.7.9 - HTTP client for API communication
- **Supabase** - Real-time job status updates

### Media

- **FFmpeg.wasm** 0.12.15 - Browser-based video processing
- **React Player** 2.16.0 - Video playback component

### UI

- **React Spring** 10.0.3 - Animation library
- **React Markdown** 9.0.1 - Markdown rendering
- **Headless UI** 2.2.0 - Unstyled accessible components
- **Heroicons** 2.2.0 - Icon library

## Prerequisites

- **Node.js** 18.x or higher
- **npm** 9.x or higher (comes with Node.js)
- **Backend API** running on `http://localhost:8000` (see [backend setup](../backend/README.md))

## Installation

### 1. Install Dependencies

```bash
# From the frontend directory
npm install
```

### 2. Environment Configuration

Create a `.env` file in the frontend directory:

```bash
# .env

# Backend API URL
VITE_API_URL=http://localhost:8000

# Supabase (for real-time job updates)
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_anon_key
```

By default, the app connects to `http://localhost:8000` for local development.

### 3. Start Development Server

```bash
npm run dev
```

The application will open at `http://localhost:5173` with hot reload enabled.

## Available Scripts

### Development

```bash
npm run dev
```

Starts the Vite development server with HMR on port 5173.

### Production Build

```bash
npm run build
```

Builds the app for production:

1. Runs TypeScript compiler (`tsc -b`)
2. Builds optimized bundle with Vite
3. Output in `dist/` directory

### Preview Production Build

```bash
npm run preview
```

Locally preview the production build before deployment.

### Linting

```bash
npm run lint
```

Runs ESLint to check code quality and identify issues.

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── common/                     # Shared components
│   │   │   └── ImageModal.tsx
│   │   └── features/                   # Feature-specific components
│   │       ├── transcription/
│   │       │   ├── TranscriptionUpload.tsx     # Main orchestrator component
│   │       │   ├── UploadZone.tsx
│   │       │   ├── ProcessingOverlay.tsx
│   │       │   ├── TranscriptSegmentList.tsx
│   │       │   ├── JumpToTimeModal.tsx
│   │       │   ├── SubtitleControls.tsx
│   │       │   ├── CustomProgressBar.tsx
│   │       │   └── SavedTranscriptionsPanel.tsx
│   │       ├── chat/
│   │       │   └── ChatPanel.tsx               # RAG chat interface
│   │       ├── search/
│   │       │   └── SearchPanel.tsx             # Semantic & visual search
│   │       ├── summary/
│   │       │   └── SummaryPanel.tsx            # Summary display
│   │       ├── speakers/
│   │       │   └── EnrolledSpeakersPanel.tsx   # Speaker management
│   │       ├── jobs/                           # Background job UI
│   │       │   ├── JobPanel.tsx
│   │       │   ├── JobList.tsx
│   │       │   ├── JobCard.tsx
│   │       │   └── ShareJobDialog.tsx
│   │       ├── analytics/
│   │       │   └── AnalyticsPanel.tsx
│   │       └── video/
│   │           └── [video components]
│   ├── hooks/
│   │   ├── useTranscription.ts          # Transcription logic & state
│   │   ├── useVideoPlayer.ts            # Video playback control
│   │   ├── useFileUpload.ts             # File upload & drag-drop
│   │   ├── useSubtitles.ts              # Subtitle generation
│   │   ├── useSummaries.ts              # Summary generation
│   │   ├── useBackgroundJobSubmit.ts    # Submit jobs to queue
│   │   ├── useJobTracker.ts             # Track & fetch jobs
│   │   ├── useJobStorage.ts             # Persist jobs to localStorage
│   │   ├── useSupabaseRealtime.ts       # Real-time job updates
│   │   └── useJobNotifications.ts       # Browser notifications
│   ├── services/
│   │   ├── api.ts                       # Axios API client
│   │   └── gcsUpload.ts                 # Direct GCS upload client
│   ├── lib/
│   │   └── supabase.ts                  # Supabase client setup
│   ├── types/
│   │   ├── job.ts                       # Job type definitions
│   │   └── [other types]
│   ├── utils/
│   │   ├── time.ts                      # Time formatting utilities
│   │   ├── speaker.ts                   # Speaker label formatting
│   │   ├── subtitle.ts                  # Subtitle generation
│   │   ├── file.ts                      # File hashing & utilities
│   │   ├── ffmpeg.ts                    # FFmpeg web integration
│   │   └── animations.ts                # React Spring configs
│   ├── config.ts                        # App configuration
│   ├── App.tsx                          # Root component
│   ├── main.tsx                         # Entry point
│   └── index.css                        # Global styles (Tailwind)
├── public/                              # Static assets
├── index.html                           # HTML template
├── package.json                         # Dependencies and scripts
├── vite.config.ts                       # Vite configuration
├── tsconfig.json                        # TypeScript config
├── tsconfig.app.json                    # App-specific TS config
├── tailwind.config.js                   # TailwindCSS config
├── postcss.config.js                    # PostCSS config
├── eslint.config.js                     # ESLint configuration
├── Dockerfile                           # Docker build
└── nginx.conf                           # Nginx configuration
```

## Key Features

### Video Upload & Processing

- Drag-and-drop file upload
- Multiple format support (MP4, MP3, WAV, WebM, MKV, etc.)
- **Direct GCS upload** for large files (bypasses 32MB limit)
- **Resumable uploads** for files >100MB
- Progress tracking during upload and transcription
- FFmpeg-based video processing in the browser

### Background Job Processing

- **Async job submission** for large files
- **Real-time status updates** via Supabase
- Job queue with retry support
- **Browser notifications** when jobs complete
- **Share links** for job results
- Job history with localStorage persistence

### Transcription Display

- Synchronized video playback with transcript
- Speaker-labeled segments with color coding
- Click-to-jump navigation
- Real-time timestamp tracking
- Editable speaker names (propagates to vector store)

### Search Capabilities

- **Semantic Search**: Find content by meaning using vector embeddings
- **Visual Search**: Find moments by describing what you see (CLIP-powered)
- **Full-text Search**: Traditional keyword search
- Context display (before/after segments)
- Jump-to-timestamp from search results

### AI-Powered Features

- **RAG Chat**: Ask questions about video content (multi-modal)
- **Summarization**: Generate AI summaries of transcripts
- **Translation**: Multi-language translation support
- **Audio Events**: Detect laughter, applause, music in chat context

### Subtitle Management

- Export to WebVTT and SRT formats
- Translation toggle
- Speaker filtering
- Downloadable subtitle files

### Speaker Management

- Enroll speaker voice samples
- Auto-identify speakers in new videos
- Edit speaker names
- Speaker-based filtering

### Analytics

- Speaking time per speaker
- Segment statistics
- Word count analysis

## Custom Hooks

The application uses several custom hooks for clean separation of concerns:

| Hook                     | Purpose                                            |
| ------------------------ | -------------------------------------------------- |
| `useTranscription`       | Transcription logic, processing status, timers     |
| `useVideoPlayer`         | Video playback controls (play/pause, seek, volume) |
| `useFileUpload`          | File selection, drag-drop, file state              |
| `useSubtitles`           | Subtitle generation and display toggle             |
| `useSummaries`           | Summary generation and caching                     |
| `useBackgroundJobSubmit` | Submit files for background processing             |
| `useJobTracker`          | Track and fetch background jobs                    |
| `useJobStorage`          | Persist jobs to localStorage                       |
| `useSupabaseRealtime`    | Real-time updates from Supabase                    |
| `useJobNotifications`    | Browser notifications for job completion           |

## API Integration

The frontend communicates with the backend API. All API calls are centralized in `src/services/api.ts` using Axios.

### Upload Flow

```
1. File Selection (drag-drop or browse)
2. File Hash Generation (SHA-256 for deduplication)
3. Size Check:
   - < 32MB: Direct upload to backend
   - >= 32MB: Get signed URL, upload to GCS
4. Processing Mode:
   - Streaming: Real-time SSE updates
   - Background: Submit to job queue
5. Result Retrieval
```

### Main Endpoints Used

```typescript
// Transcription
POST /transcribe_local/              // Direct upload & transcribe
POST /transcribe_local_stream/       // Streaming with SSE
POST /transcribe_gcs_stream/         // Transcribe from GCS
GET /transcriptions/                 // List saved transcriptions
GET /transcription/{video_hash}      // Get specific transcription
DELETE /transcription/{video_hash}   // Delete transcription

// Upload & Jobs
POST /api/upload/signed-url          // Get GCS signed URL
POST /api/upload/resumable-url       // Get resumable upload URL
POST /api/jobs/submit                // Submit background job
GET /api/jobs/{job_id}               // Get job status/results
GET /api/jobs                        // List all jobs
GET /api/jobs/{job_id}/share         // Generate share link

// Search & Chat
POST /api/index_video/               // Index for semantic search
POST /api/index_images/              // Index screenshots (CLIP)
POST /api/search_images/             // Visual search
POST /api/chat/                      // Multi-modal RAG chat

// Speaker Recognition
POST /api/speaker/enroll             // Enroll speaker
GET /api/speaker/list                // List enrolled speakers
POST /api/speaker/transcription/{hash}/auto_identify_speakers

// Translation & Subtitles
POST /translate_local/               // Translate segments
GET /subtitles/{language}            // Generate subtitle file

// Summaries
POST /generate_summary/              // Generate AI summary
```

See the full API documentation in the [Backend README](../backend/README.md).

## Building for Production

### 1. Build the Application

```bash
npm run build
```

This creates an optimized production build in the `dist/` directory.

### 2. Test Production Build Locally

```bash
npm run preview
```

### 3. Deploy

#### Netlify (Recommended)

The app is deployed to Netlify with automatic deploys:

1. Connect repository to Netlify
2. Set environment variables:
   - `VITE_API_URL=`
   - `VITE_SUPABASE_URL=https://your-project.supabase.co`
   - `VITE_SUPABASE_ANON_KEY=your_anon_key`
3. Build command: `npm run build`
4. Publish directory: `dist`

#### Docker

```bash
# Build image
docker build -t ai-subs-frontend \
  --build-arg VITE_API_URL=https://your-api.run.app .

# Run container
docker run -p 80:80 ai-subs-frontend
```

#### Other Options

- **Vercel**: `vercel deploy`
- **AWS S3 + CloudFront**: Upload `dist/` contents
- **GitHub Pages**: Use gh-pages package

## Environment Variables

| Variable                 | Description          | Default                 |
| ------------------------ | -------------------- | ----------------------- |
| `VITE_API_URL`           | Backend API URL      | `http://localhost:8000` |
| `VITE_SUPABASE_URL`      | Supabase project URL | -                       |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon key    | -                       |

Note: Variables prefixed with `VITE_` are exposed to frontend code.

## Troubleshooting

### Common Issues

**Port 5173 already in use**

```bash
lsof -ti:5173 | xargs kill -9
# Or specify a different port
npm run dev -- --port 3000
```

**Module not found errors**

```bash
rm -rf node_modules package-lock.json
npm install
```

**TypeScript errors**

```bash
npm run build
```

**Vite cache issues**

```bash
rm -rf node_modules/.vite
npm run dev
```

**CORS errors**

- Ensure backend is running and allows frontend origin
- Check that API URL in `.env` is correct

**FFmpeg not loading**

- Check browser console for errors
- FFmpeg.wasm requires SharedArrayBuffer support
- Ensure proper COOP/COEP headers in production

**Large file upload fails**

- Files >32MB require GCS upload (backend must have GCS configured)
- Files >100MB use resumable upload protocol
- Check browser console for upload errors

**Background jobs not updating**

- Verify Supabase credentials in `.env`
- Check that Supabase real-time is enabled
- Verify network connection to Supabase

### Browser Compatibility

- **Chrome/Edge**: Full support
- **Firefox**: Full support
- **Safari**: Full support (requires COOP/COEP headers for FFmpeg)
- **Mobile**: Limited FFmpeg support on mobile browsers

## Development Guidelines

### Code Style

- Use **functional components** with hooks (no class components)
- Implement **proper TypeScript types** for all props and state
- Follow **atomic design principles** for component organization
- Use **TailwindCSS utilities** instead of custom CSS when possible

### State Management

- Use **React Query** for server state (API data, caching)
- Use **custom hooks** for complex component logic
- Keep local state in components when possible
- Avoid prop drilling - extract shared logic to hooks
- Use **Supabase real-time** for live updates

### Component Guidelines

1. **Single Responsibility**: Each component should do one thing well
2. **Props Typing**: Always define TypeScript interfaces for props
3. **Error Boundaries**: Handle errors gracefully
4. **Loading States**: Show feedback during async operations
5. **Accessibility**: Use semantic HTML and ARIA attributes

### Performance Best Practices

- Lazy load heavy components (video player, FFmpeg)
- Use React.memo() for expensive renders
- Implement virtualization for long lists
- Optimize images and assets
- Cache API responses with React Query

## Architecture

For detailed information about component architecture, state management patterns, and design decisions, see [ARCHITECTURE.md](./ARCHITECTURE.md).

## Contributing

When contributing to the frontend:

1. Follow the existing code style
2. Add TypeScript types for new code
3. Test components in isolation
4. Update this README if adding new features
5. Run linting before committing: `npm run lint`

## Related Documentation

- **[Main README](../README.md)** - Project overview and quick start
- **[Frontend Architecture](./ARCHITECTURE.md)** - Detailed architecture guide
- **[Backend README](../backend/README.md)** - Backend setup and API docs
- **[Production Deployment](../docs/PRODUCTION_DEPLOYMENT_FIXES.md)** - Cloud Run + Netlify deployment
