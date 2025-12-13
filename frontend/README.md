# AI Subtitles - Frontend

React + TypeScript frontend for the AI Subtitles application. Features a modern, responsive interface for video transcription, subtitle generation, semantic search, and AI-powered chat about video content.

## Technology Stack

- **React** 19.0.0 with TypeScript
- **Vite** 6.1.0 - Fast build tool with Hot Module Replacement (HMR)
- **TailwindCSS** 3.3.3 - Utility-first CSS framework
- **React Query** 5.66.8 - Async state management and data fetching
- **React Router DOM** 7.2.0 - Client-side routing
- **Axios** 1.7.9 - HTTP client for API communication
- **FFmpeg.wasm** 0.12.15 - Browser-based video processing
- **React Player** 2.16.0 - Video playback component
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

### 2. Environment Configuration (Optional)

Create a `.env` file in the frontend directory if you need to customize API URL:

```bash
# .env
VITE_API_URL=http://localhost:8000
```

By default, the app connects to `http://localhost:8000`. No `.env` file is needed for local development.

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
│   │   ├── common/                    # Shared components
│   │   │   └── ImageModal.tsx
│   │   └── features/                  # Feature-specific components
│   │       ├── transcription/
│   │       │   ├── TranscriptionUpload.tsx    # Main component
│   │       │   ├── UploadZone.tsx
│   │       │   ├── ProcessingOverlay.tsx
│   │       │   ├── TranscriptDisplay.tsx
│   │       │   ├── TranscriptSegmentList.tsx
│   │       │   ├── JumpToTimeModal.tsx
│   │       │   ├── SubtitleControls.tsx
│   │       │   ├── CustomProgressBar.tsx
│   │       │   └── SavedTranscriptionsPanel.tsx
│   │       ├── chat/
│   │       │   └── ChatPanel.tsx              # RAG chat interface
│   │       ├── search/
│   │       │   └── SearchPanel.tsx            # Semantic search
│   │       ├── summary/
│   │       │   └── SummaryPanel.tsx           # Summary display
│   │       └── analytics/
│   │           └── AnalyticsPanel.tsx         # Stats & analytics
│   ├── hooks/
│   │   ├── useTranscription.ts        # Transcription logic & state
│   │   ├── useVideoPlayer.ts          # Video playback control
│   │   ├── useFileUpload.ts           # File upload & drag-drop
│   │   ├── useSubtitles.ts            # Subtitle generation
│   │   └── useSummaries.ts            # Summary generation
│   ├── services/
│   │   └── api.ts                     # Axios API client
│   ├── utils/
│   │   ├── time.ts                    # Time formatting utilities
│   │   ├── speaker.ts                 # Speaker label formatting
│   │   ├── subtitle.ts                # Subtitle generation
│   │   ├── ffmpeg.ts                  # FFmpeg web integration
│   │   └── animations.ts              # React Spring configs
│   ├── App.tsx                        # Root component
│   ├── main.tsx                       # Entry point
│   └── index.css                      # Global styles (Tailwind)
├── public/                            # Static assets
├── index.html                         # HTML template
├── package.json                       # Dependencies and scripts
├── vite.config.ts                     # Vite configuration
├── tsconfig.json                      # TypeScript config
├── tsconfig.app.json                  # App-specific TS config
├── tailwind.config.js                 # TailwindCSS config
├── postcss.config.js                  # PostCSS config
└── eslint.config.js                   # ESLint configuration
```

## Key Features

### Video Upload & Processing
- Drag-and-drop file upload
- Multiple format support (MP4, MP3, WAV, WebM, etc.)
- Progress tracking during upload and transcription
- FFmpeg-based video processing in the browser

### Transcription Display
- Synchronized video playback with transcript
- Speaker-labeled segments with color coding
- Click-to-jump navigation
- Real-time timestamp tracking
- Editable transcripts

### Search Capabilities
- **Semantic Search**: Find content by meaning using vector embeddings
- **Full-text Search**: Traditional keyword search
- Context display (before/after segments)
- Jump-to-timestamp from search results

### AI-Powered Features
- **RAG Chat**: Ask questions about video content
- **Summarization**: Generate AI summaries of transcripts
- **Translation**: Multi-language translation support

### Subtitle Management
- Export to WebVTT and SRT formats
- Translation toggle
- Speaker filtering
- Downloadable subtitle files

### Analytics
- Speaking time per speaker
- Segment statistics
- Word count analysis

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

## API Integration

The frontend communicates with the backend API at `http://localhost:8000`. All API calls are centralized in `src/services/api.ts` using Axios.

### Main Endpoints Used

```typescript
// Transcription
POST /transcribe_local/              // Upload and transcribe video
GET /transcriptions/                 // List saved transcriptions
GET /transcription/{video_hash}      // Get specific transcription
DELETE /transcription/{video_hash}   // Delete transcription

// Translation & Subtitles
POST /translate_local/               // Translate segments
GET /subtitles/{language}            // Generate subtitle file

// Search & Chat
POST /api/index_video/               // Index video for search
POST /api/chat/                      // Chat with video content

// Summaries
POST /generate_summary/              // Generate AI summary

// Video & Media
GET /video/{video_hash}              // Stream video file
POST /update_file_path/{video_hash}  // Update file path
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

The `dist/` folder contains static files that can be deployed to any static hosting service:

- **Vercel**: `vercel deploy`
- **Netlify**: Drag and drop `dist/` folder
- **AWS S3 + CloudFront**: See [deployment guide](../docs/DEPLOYMENT.md)
- **GitHub Pages**: Use gh-pages package
- **Docker**: Use nginx to serve static files

#### Example: Static File Server

```bash
# Using a simple HTTP server
npx serve dist -p 3000
```

#### Environment Variables for Production

When deploying, set the API URL:

```bash
VITE_API_URL=https://api.yourproduction.com
```

Then rebuild:

```bash
npm run build
```

## Troubleshooting

### Common Issues

**Port 5173 already in use**
```bash
# Kill the process using the port
lsof -ti:5173 | xargs kill -9
# Or specify a different port
npm run dev -- --port 3000
```

**Module not found errors**
```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

**TypeScript errors**
```bash
# Rebuild TypeScript
npm run build
```

**Vite cache issues**
```bash
# Clear Vite cache
rm -rf node_modules/.vite
npm run dev
```

**CORS errors**
- Ensure backend is running on `http://localhost:8000`
- Check that backend CORS settings allow frontend origin
- Verify API URL in `.env` if using custom configuration

**FFmpeg not loading**
- Check browser console for errors
- FFmpeg.wasm requires SharedArrayBuffer support
- Ensure proper COOP/COEP headers in production

### Browser Compatibility

- **Chrome/Edge**: Full support
- **Firefox**: Full support
- **Safari**: Full support (requires COOP/COEP headers for FFmpeg)
- **Mobile**: Limited FFmpeg support on mobile browsers

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
- **[Deployment Guide](../docs/DEPLOYMENT.md)** - Production deployment
