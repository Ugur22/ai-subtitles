# TranscriptionUpload Component Refactoring Plan

## Current State: CRITICAL Issues

**File**: `TranscriptionUpload.tsx`
**Line Count**: 3,137 lines
**Status**: 🚨 MASSIVE ANTI-PATTERN - Violates React best practices

### Problems Identified

1. **God Component**: Everything is in one file (UI, logic, state, utilities)
2. **20+ useState hooks**: State management is scattered and unorganized
3. **10+ useEffect hooks**: Side effects are mixed with UI logic
4. **15+ utility functions**: Helpers defined inline instead of extracted
5. **2 inline modal components**: `ImageModal` and `JumpToTimeModal` defined within component
6. **Massive JSX**: Return statement is 1000+ lines
7. **Mixed concerns**: Video control, file upload, transcription, summaries, search all mixed together
8. **Hard to test**: Cannot unit test individual pieces
9. **Hard to maintain**: Changes require scrolling through thousands of lines
10. **Poor performance**: Entire component re-renders on any state change

---

## Refactoring Strategy

### Phase 1: Extract Utility Functions (Quick Win)

**Create**: `frontend/src/utils/transcription.ts`

Move these pure functions:
- `formatProcessingTime()` - line 51
- `formatSpeakerLabel()` - line 114
- `getSpeakerColor()` - line 131
- `secondsToTimeString()` - line 253
- `convertTimeToSeconds()` - line 580
- `timeToSeconds()` - line 1452
- `timeToMs()` - line 1106
- `msToTime()` - line 1117

**Create**: `frontend/src/utils/subtitle.ts`

Move subtitle-related functions:
- `generateWebVTT()` - line 987
- All WebVTT chunking logic

**Impact**: ~400 lines removed, utilities reusable across app

---

### Phase 2: Extract Modal Components

**Create**: `frontend/src/components/common/ImageModal.tsx`
- Extract `ImageModal` component (lines 179-237)

**Create**: `frontend/src/components/features/transcription/JumpToTimeModal.tsx`
- Extract `JumpToTimeModal` component (lines 267-408)

**Impact**: ~170 lines removed, modals reusable

---

### Phase 3: Extract Custom Hooks

**Create**: `frontend/src/hooks/useTranscription.ts`

Extract transcription-related state and logic:
```typescript
export const useTranscription = () => {
  const [transcription, setTranscription] = useState<TranscriptionResponse | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [elapsedTime, setElapsedTime] = useState(0);

  // All transcription logic here
  const handleStartTranscription = async (file: File) => { ... };
  const fetchCurrentTranscription = async () => { ... };

  return { transcription, processingStatus, elapsedTime, handleStartTranscription, ... };
};
```

**Create**: `frontend/src/hooks/useVideoPlayer.ts`

Extract video player state and controls:
```typescript
export const useVideoPlayer = (videoRef: HTMLVideoElement | null) => {
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(1);

  // Video control logic
  const handlePlayPause = () => { ... };
  const seekToTimestamp = (timeString: string) => { ... };

  return { currentTime, isPlaying, volume, handlePlayPause, seekToTimestamp, ... };
};
```

**Create**: `frontend/src/hooks/useFileUpload.ts`

Extract file upload state and drag-drop logic:
```typescript
export const useFileUpload = () => {
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = (e: React.DragEvent) => { ... };
  const handleDrop = async (e: React.DragEvent) => { ... };

  return { file, dragActive, handleDrag, handleDrop, ... };
};
```

**Create**: `frontend/src/hooks/useSubtitles.ts`

Extract subtitle management:
```typescript
export const useSubtitles = (transcription: TranscriptionResponse | null) => {
  const [showSubtitles, setShowSubtitles] = useState(true);
  const [subtitleTrackUrl, setSubtitleTrackUrl] = useState<string | null>(null);

  const createSubtitleTracks = () => { ... };

  return { showSubtitles, subtitleTrackUrl, createSubtitleTracks, ... };
};
```

**Create**: `frontend/src/hooks/useSummaries.ts`

Extract summary state and generation:
```typescript
export const useSummaries = () => {
  const [summaries, setSummaries] = useState<SummarySection[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const generateSummaries = async () => { ... };
  const fetchScreenshotsForSummaries = async (data: SummarySection[]) => { ... };

  return { summaries, summaryLoading, generateSummaries, ... };
};
```

**Impact**: ~600 lines removed, logic encapsulated and testable

---

### Phase 4: Extract Sub-Components

**Create**: `frontend/src/components/features/transcription/UploadZone.tsx`

Extract the file upload/drag-drop UI:
- Drag-drop zone
- File selection
- Language/method selection
- Start button

**Create**: `frontend/src/components/features/transcription/ProcessingOverlay.tsx`

Extract the processing status modal:
- Spinner overlay (lines 1678-1865)
- All processing UI

**Create**: `frontend/src/components/features/transcription/TranscriptionStats.tsx`

Extract the stats grid:
- File name, duration, language, speed display
- Action buttons row

**Create**: `frontend/src/components/features/video/VideoPlayer.tsx`

Extract video player:
- Video element
- Custom controls
- Progress bar
- Volume control
- Play/pause
- Jump to time

**Create**: `frontend/src/components/features/transcription/TranscriptView.tsx`

Extract transcript display:
- Segment list
- Translation toggle
- Speaker labels
- Screenshot thumbnails
- Seek on click

**Create**: `frontend/src/components/features/transcription/TabContainer.tsx`

Extract tab switching logic:
- Transcript/Summary tabs
- Tab content rendering

**Impact**: ~1500 lines removed, UI components reusable and focused

---

### Phase 5: Context API for Shared State

**Create**: `frontend/src/contexts/TranscriptionContext.tsx`

Create context to avoid prop drilling:
```typescript
export const TranscriptionContext = createContext<TranscriptionContextType | undefined>(undefined);

export const TranscriptionProvider: React.FC = ({ children }) => {
  const transcriptionState = useTranscription();
  const videoState = useVideoPlayer(videoRef);

  return (
    <TranscriptionContext.Provider value={{ ...transcriptionState, ...videoState }}>
      {children}
    </TranscriptionContext.Provider>
  );
};
```

**Impact**: Cleaner prop passing, better state management

---

### Phase 6: Final Component Structure

After refactoring, `TranscriptionUpload.tsx` should be ~200-300 lines:

```typescript
export const TranscriptionUpload: React.FC = () => {
  return (
    <TranscriptionProvider>
      <div className="...">
        <UploadZone />
        <TranscriptionResults />
      </div>
    </TranscriptionProvider>
  );
};

const TranscriptionResults = () => {
  const { transcription } = useTranscriptionContext();

  if (!transcription) return null;

  return (
    <>
      <TranscriptionStats />
      <VideoPlayer />
      <TabContainer />
    </>
  );
};
```

---

## New File Structure

```
frontend/src/
├── components/
│   ├── common/
│   │   ├── ImageModal.tsx          [NEW]
│   │   └── ...
│   └── features/
│       ├── transcription/
│       │   ├── TranscriptionUpload.tsx      [MAIN - reduced to ~250 lines]
│       │   ├── UploadZone.tsx              [NEW]
│       │   ├── ProcessingOverlay.tsx       [NEW]
│       │   ├── TranscriptionStats.tsx      [NEW]
│       │   ├── TranscriptView.tsx          [NEW]
│       │   ├── TabContainer.tsx            [NEW]
│       │   ├── JumpToTimeModal.tsx         [NEW]
│       │   └── ...existing files
│       └── video/
│           └── VideoPlayer.tsx              [NEW]
├── hooks/
│   ├── useTranscription.ts         [NEW]
│   ├── useVideoPlayer.ts           [NEW]
│   ├── useFileUpload.ts            [NEW]
│   ├── useSubtitles.ts             [NEW]
│   └── useSummaries.ts             [NEW]
├── utils/
│   ├── transcription.ts            [NEW]
│   ├── subtitle.ts                 [NEW]
│   ├── animations.ts               [existing]
│   └── ...
├── contexts/
│   └── TranscriptionContext.tsx    [NEW]
└── services/
    └── api.ts                      [existing]
```

---

## Benefits After Refactoring

### Before (Current)
- ❌ 3,137 lines in one file
- ❌ Cannot test individual pieces
- ❌ Hard to find specific functionality
- ❌ Performance issues (re-renders everything)
- ❌ Cannot reuse logic/components
- ❌ Merge conflicts on every change
- ❌ New developers overwhelmed

### After (Refactored)
- ✅ Main component ~250 lines
- ✅ Each piece unit testable
- ✅ Easy to locate functionality
- ✅ Optimized re-renders
- ✅ Reusable hooks and components
- ✅ Minimal merge conflicts
- ✅ Clear, understandable structure

---

## Implementation Order (Recommended)

1. **Week 1**: Extract utilities (Phase 1) - Low risk, quick wins
2. **Week 1**: Extract modals (Phase 2) - Low risk, independent
3. **Week 2**: Create custom hooks (Phase 3) - Medium complexity
4. **Week 2-3**: Extract sub-components (Phase 4) - Higher complexity
5. **Week 3**: Add context (Phase 5) - Final integration
6. **Week 4**: Testing, bug fixes, optimization

**Total Estimated Time**: 3-4 weeks
**Complexity**: Medium-High
**Risk**: Medium (need comprehensive testing)

---

## Testing Strategy

For each extracted piece:
1. Write unit tests for utilities
2. Write component tests for UI pieces
3. Write integration tests for hooks
4. Maintain E2E tests for full flow
5. Manual testing of all features

---

## Notes

- Keep the old component until all pieces are tested
- Use feature flags to switch between old/new
- Refactor incrementally, not all at once
- Document each new component/hook
- Review with team before merging each phase

---

## Conclusion

This refactoring is **CRITICAL** for maintainability. The current 3,137-line component is:
- A code smell
- A maintenance nightmare
- A performance bottleneck
- A testing impossibility

Following this plan will transform it into a clean, modular, testable architecture that follows React best practices.
