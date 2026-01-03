# Background Job Processing Specification for AI-Subs

> **Date**: January 3, 2026
> **Status**: Specification Complete
> **Version**: 2.0

---

## Executive Summary

This document captures the complete specification for implementing background job processing for the AI-Subs video transcription application. The goal is to allow users to submit large video files (700+ MB), close their browser, and receive notifications when transcription is complete.

**Recommended Solution**: Supabase (PostgreSQL with real-time subscriptions) + FastAPI Background Tasks

**Key Decisions**:

- Database: Supabase (real-time, free tier, familiar SQL)
- Max Concurrent Jobs: 3 (global limit)
- Job Retention: 7 days (rolling)
- Notifications: Browser only (no email initially)
- Migration: Full migration to jobs (SSE endpoints removed)

---

## Table of Contents

1. [Decision Summary](#decision-summary)
2. [Current Architecture Analysis](#current-architecture-analysis)
3. [Solution Architecture](#solution-architecture)
4. [Backend Implementation](#backend-implementation)
5. [Frontend Implementation](#frontend-implementation)
6. [User Experience Design](#user-experience-design)
7. [Implementation Plan](#implementation-plan)
8. [Appendix: Alternative Approaches](#appendix-alternative-approaches)

---

## Decision Summary

All technical and UX decisions finalized through stakeholder interview:

### Core Architecture

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Worker death handling | Heartbeat + auto-retry | Worker updates `last_seen` every 30s. Cloud Scheduler detects stale jobs every 5 min and auto-retries |
| Concurrency limit | Global (3 jobs total) | Simple, prevents system overload. All users share the limit |
| Stale job detection | Cloud Scheduler + endpoint | Calls `/api/jobs/check-stale` every 5 min. ~$0.10/month |
| Auto-retry limit | 3 retries with exponential backoff | Resilient to transient failures without infinite loops |
| Heartbeat interval | Every 30 seconds | Balanced: quick stale detection, minimal DB writes |

### File & Data Handling

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deduplication | Return cached result | Same file hash returns existing completed result. Shows cache notice |
| Result storage | JSONB in Supabase | 500KB per job acceptable. ~350MB max with 7-day retention |
| Export formats | Pre-generate SRT, VTT, JSON | Instant downloads. TXT excluded (less common) |
| Source file cleanup | Keep 7 days | Matches job retention. Allows re-processing if needed |
| Job cleanup timing | Rolling 7 days | Delete when job is exactly 168 hours old |

### Migration Strategy

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SSE coexistence | Jobs only (full migration) | Remove SSE endpoints entirely. Cleaner codebase |
| SSE endpoint handling | Remove entirely | Clean break. No deprecation period |
| Partial failure | Mark as failed | Strict handling. Any component failure = job failure |

### Security & Access

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Job ID security | UUID + secret token | Token stored in localStorage. Required for access |
| Token visibility | Separate share action | Hidden by default. Explicit "Share this job" generates link |
| Job recovery | Both localStorage + shareable URLs | Belt and suspenders approach |

### API Behavior

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Submit response | Wait for DB confirm | Await Supabase insert before returning. Guaranteed consistency |
| Queue full handling | Block upload entirely | Disable upload with clear message when 3 jobs active |
| Cancel scope | Pending only | Cannot cancel in-progress jobs. Processing runs to completion |
| Retry settings | Same settings only | No modifications on retry. Re-upload to change settings |
| Stale job handling | One at a time | Process one stale job per scheduler run. Controlled resources |

### Frontend & UX

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Navigation | Slide-out panel | Persistent side panel/drawer for job list |
| Panel behavior | Auto-open on submit | Panel slides out when new job submitted |
| Result viewing | Reuse existing viewer | Navigate to same transcript viewer for consistency |
| Job list scale | Paginated (10 per page) | Classic pagination controls |
| Time estimates | History-based | Calculate from average duration of similar-sized past jobs |
| Mobile support | Responsive only | No PWA or special mobile features |

### Notifications & Errors

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Permission timing | After first job completes | Lower friction than asking on submit |
| Error display | User-friendly only | Generic messages to user. Full stack trace in server logs |
| Monitoring | Cloud Run metrics only | No additional Supabase job metrics |
| Orphan job IDs | Silent cleanup | Remove invalid IDs from localStorage automatically |

### Resilience

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Supabase outage | Cache last known state | Show cached list with "Offline - data may be stale" warning |
| Cache transparency | Show cache notice | Display when returning deduplicated result |

---

## Current Architecture Analysis

### Existing Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Browser   │───>│  Cloud Run  │───>│   SQLite    │
│  (React)    │    │  (FastAPI)  │    │  (ephemeral)│
└─────────────┘    └─────────────┘    └─────────────┘
      │                  │
      │<── SSE Progress ─│
      │                  │
      └── Must stay open─┘
```

### Current Components

| Layer            | Technology               | Notes                      |
| ---------------- | ------------------------ | -------------------------- |
| Frontend         | React/TypeScript         | Hosted on Netlify          |
| Backend          | FastAPI                  | Hosted on Cloud Run        |
| Database         | SQLite                   | Ephemeral (data loss risk) |
| File Storage     | GCS                      | For files ≥32MB            |
| Progress Updates | Server-Sent Events (SSE) | Requires open connection   |

### Current Upload Flow

**Small files (<32MB)**:

```
Browser → POST /transcribe_local_stream/ → SSE updates → Result
```

**Large files (≥32MB)**:

```
Browser → Get signed URL → Upload to GCS → POST /transcribe_gcs_stream/ → SSE updates → Result
```

### Critical Issues Identified

1. **Browser Dependency**: User must keep browser open for 30+ minutes
2. **SQLite on Cloud Run**: Ephemeral storage means data loss on restart
3. **No Background Processing**: Everything runs synchronously in HTTP request
4. **Timeout Risk**: Long videos may exceed Cloud Run's 60-minute timeout
5. **No Notifications**: No way to alert user when job completes

---

## Solution Architecture

### Target: Supabase + FastAPI Background Tasks

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Browser   │───>│  Cloud Run  │───>│  Supabase   │
│  (React)    │    │  (FastAPI)  │    │ (PostgreSQL)│
└─────────────┘    └─────────────┘    └─────────────┘
      │                  │                   │
      │ 1. Upload to GCS │                   │
      │ 2. POST /jobs    │                   │
      │<─────────────────│                   │
      │   {job_id,token} │                   │
      │                  │                   │
      │ 3. Subscribe to  │  4. Background    │
      │    real-time     │     processing    │
      │    updates       │──────────────────>│
      │<─────────────────────────────────────│
      │   {status update via WebSocket}      │
      │                  │                   │
      │ 5. Close browser │  6. Processing    │
      │    (optional)    │     continues     │
      │                  │──────────────────>│
      │                  │  7. Mark complete │
      │                  │                   │
      │ 8. Return later  │                   │
      │    Query status  │<──────────────────│
      │<─────────────────│ OR real-time push │
```

### Heartbeat & Stale Job Recovery

```
┌──────────────────┐     ┌─────────────────┐     ┌─────────────┐
│  Cloud Scheduler │────>│  Cloud Run      │────>│  Supabase   │
│  (every 5 min)   │     │  /check-stale   │     │             │
└──────────────────┘     └─────────────────┘     └─────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │ Find jobs where:      │
                    │ status = 'processing' │
                    │ last_seen > 90 sec    │
                    │ retry_count < 3       │
                    └───────────────────────┘
                                │
                                ▼ (one job at a time)
                    ┌───────────────────────┐
                    │ Reset to 'pending'    │
                    │ Increment retry_count │
                    │ Trigger background    │
                    └───────────────────────┘
```

### Why Supabase?

| Feature                 | Benefit                                  |
| ----------------------- | ---------------------------------------- |
| Real-time subscriptions | Instant status updates without polling   |
| PostgreSQL              | Familiar SQL, easy migration from SQLite |
| Free tier               | 500MB, unlimited API requests            |
| Persistent              | Data survives Cloud Run restarts         |
| Row-level security      | Built-in auth if needed later            |

---

## Backend Implementation

### Database Schema

```sql
CREATE TABLE transcription_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    access_token UUID NOT NULL DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'pending',
    filename TEXT NOT NULL,
    file_size_bytes BIGINT,
    video_hash TEXT,
    gcs_path TEXT,
    progress INTEGER DEFAULT 0,
    progress_stage TEXT,
    progress_message TEXT,
    error_message TEXT,
    error_code TEXT,
    result_json JSONB,
    result_srt TEXT,
    result_vtt TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0,

    -- Processing parameters
    num_speakers INTEGER,
    min_speakers INTEGER,
    max_speakers INTEGER,
    language TEXT,
    force_language BOOLEAN DEFAULT FALSE
);

-- Enable real-time
ALTER PUBLICATION supabase_realtime ADD TABLE transcription_jobs;

-- Indexes
CREATE INDEX idx_jobs_status ON transcription_jobs(status);
CREATE INDEX idx_jobs_created ON transcription_jobs(created_at DESC);
CREATE INDEX idx_jobs_hash ON transcription_jobs(video_hash);
CREATE INDEX idx_jobs_stale ON transcription_jobs(status, last_seen)
    WHERE status = 'processing';

-- Historical duration tracking for time estimates
CREATE TABLE job_duration_stats (
    id SERIAL PRIMARY KEY,
    file_size_bucket TEXT NOT NULL,  -- e.g., '0-100MB', '100-500MB', '500MB+'
    avg_duration_seconds INTEGER NOT NULL,
    sample_count INTEGER DEFAULT 1,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### API Endpoints

| Method | Endpoint                   | Purpose            | Auth Required | Response                             |
| ------ | -------------------------- | ------------------ | ------------- | ------------------------------------ |
| POST   | `/api/jobs/submit`         | Create new job     | No            | `{job_id, access_token, status}`     |
| GET    | `/api/jobs/{job_id}`       | Get job status     | Token         | `{job_id, status, progress, result}` |
| GET    | `/api/jobs`                | List user's jobs   | Token (query) | `{jobs[], total, page, per_page}`    |
| DELETE | `/api/jobs/{job_id}`       | Cancel pending job | Token         | `{job_id, status: cancelled}`        |
| POST   | `/api/jobs/{job_id}/retry` | Retry failed job   | Token         | `{job_id, status: pending}`          |
| GET    | `/api/jobs/{job_id}/share` | Get shareable link | Token         | `{share_url}`                        |
| POST   | `/api/jobs/check-stale`    | Check stale jobs   | Internal      | `{processed: 0-1}`                   |

### Job Status Flow

```
pending → processing → completed
                    ↘ failed → (manual retry) → pending

cancelled (terminal, from pending only)
```

### New Backend Files

```
backend/
├── services/
│   ├── supabase_service.py     # Supabase client connection
│   ├── job_queue_service.py    # Job CRUD operations
│   └── background_worker.py    # Transcription processing
├── routers/
│   └── jobs.py                 # Job API endpoints
└── config.py                   # Add Supabase config
```

### Job Queue Service (Core Logic)

```python
from datetime import datetime, timedelta
from typing import Optional
import hashlib

class JobQueueService:
    """Service for managing background transcription jobs."""

    GLOBAL_CONCURRENT_LIMIT = 3
    STALE_THRESHOLD_SECONDS = 90
    MAX_RETRIES = 3

    @staticmethod
    async def create_job(
        filename: str,
        gcs_path: str,
        file_size_bytes: int,
        video_hash: str,
        **params
    ) -> dict:
        """
        Create job, check max concurrent (3), check deduplication.
        Returns {job_id, access_token, cached} or raises HTTPException.
        """

        # Check for existing completed job with same hash
        existing = await supabase.table('transcription_jobs') \
            .select('job_id, access_token, result_json, completed_at') \
            .eq('video_hash', video_hash) \
            .eq('status', 'completed') \
            .order('completed_at', desc=True) \
            .limit(1) \
            .execute()

        if existing.data:
            # Return cached result with notice
            return {
                'job_id': existing.data[0]['job_id'],
                'access_token': existing.data[0]['access_token'],
                'cached': True,
                'cached_at': existing.data[0]['completed_at']
            }

        # Check global concurrent limit
        active_count = await supabase.table('transcription_jobs') \
            .select('job_id', count='exact') \
            .in_('status', ['pending', 'processing']) \
            .execute()

        if active_count.count >= JobQueueService.GLOBAL_CONCURRENT_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="System busy. Maximum 3 jobs can run at once. Please try again later."
            )

        # Create job (wait for DB confirmation)
        job = await supabase.table('transcription_jobs').insert({
            'filename': filename,
            'gcs_path': gcs_path,
            'file_size_bytes': file_size_bytes,
            'video_hash': video_hash,
            'status': 'pending',
            **params
        }).execute()

        return {
            'job_id': job.data[0]['job_id'],
            'access_token': job.data[0]['access_token'],
            'cached': False
        }

    @staticmethod
    async def verify_access(job_id: str, token: str) -> bool:
        """Verify access token matches job."""
        result = await supabase.table('transcription_jobs') \
            .select('access_token') \
            .eq('job_id', job_id) \
            .single() \
            .execute()

        return result.data and result.data['access_token'] == token

    @staticmethod
    async def update_heartbeat(job_id: str):
        """Update last_seen timestamp (called every 30s during processing)."""
        await supabase.table('transcription_jobs').update({
            'last_seen': 'now()'
        }).eq('job_id', job_id).execute()

    @staticmethod
    async def update_progress(job_id: str, progress: int, stage: str, message: str):
        """Update job progress (triggers real-time update to frontend)."""
        await supabase.table('transcription_jobs').update({
            'progress': progress,
            'progress_stage': stage,
            'progress_message': message,
            'last_seen': 'now()'
        }).eq('job_id', job_id).execute()

    @staticmethod
    async def mark_processing(job_id: str):
        """Mark job as processing."""
        await supabase.table('transcription_jobs').update({
            'status': 'processing',
            'started_at': 'now()',
            'last_seen': 'now()'
        }).eq('job_id', job_id).execute()

    @staticmethod
    async def mark_completed(job_id: str, video_hash: str, result_json: dict,
                             result_srt: str, result_vtt: str):
        """Mark job as completed with pre-generated results."""
        await supabase.table('transcription_jobs').update({
            'status': 'completed',
            'video_hash': video_hash,
            'result_json': result_json,
            'result_srt': result_srt,
            'result_vtt': result_vtt,
            'progress': 100,
            'progress_stage': 'complete',
            'progress_message': 'Transcription complete',
            'completed_at': 'now()'
        }).eq('job_id', job_id).execute()

        # Update duration stats for time estimates
        await JobQueueService._update_duration_stats(job_id)

    @staticmethod
    async def mark_failed(job_id: str, error_message: str, error_code: str = None):
        """Mark job as failed with user-friendly message."""
        # Map technical errors to user-friendly messages
        friendly_message = JobQueueService._get_friendly_error(error_message)

        await supabase.table('transcription_jobs').update({
            'status': 'failed',
            'error_message': friendly_message,
            'error_code': error_code,
            'completed_at': 'now()'
        }).eq('job_id', job_id).execute()

    @staticmethod
    def _get_friendly_error(technical_error: str) -> str:
        """Convert technical errors to user-friendly messages."""
        error_map = {
            'ffmpeg': 'Failed to process video format. The file may be corrupted or use an unsupported codec.',
            'timeout': 'Processing took too long. Try a shorter video or different format.',
            'memory': 'Video file is too large to process. Try a smaller file.',
            'network': 'Connection issue during processing. Please retry.',
        }

        for key, message in error_map.items():
            if key.lower() in technical_error.lower():
                return message

        return 'An unexpected error occurred during processing.'

    @staticmethod
    async def cancel_job(job_id: str) -> bool:
        """Cancel a pending job. Returns False if job is already processing."""
        result = await supabase.table('transcription_jobs') \
            .update({'status': 'cancelled', 'completed_at': 'now()'}) \
            .eq('job_id', job_id) \
            .eq('status', 'pending') \
            .execute()

        return len(result.data) > 0

    @staticmethod
    async def retry_job(job_id: str) -> bool:
        """Retry a failed job with same settings."""
        result = await supabase.table('transcription_jobs') \
            .update({
                'status': 'pending',
                'error_message': None,
                'error_code': None,
                'progress': 0,
                'progress_stage': None,
                'progress_message': None,
                'completed_at': None,
                'started_at': None
            }) \
            .eq('job_id', job_id) \
            .eq('status', 'failed') \
            .execute()

        return len(result.data) > 0

    @staticmethod
    async def check_and_recover_stale_jobs() -> int:
        """
        Find and recover ONE stale job (processing with no heartbeat for 90s).
        Called by Cloud Scheduler every 5 minutes.
        Returns 1 if a job was recovered, 0 otherwise.
        """
        stale_threshold = datetime.utcnow() - timedelta(seconds=JobQueueService.STALE_THRESHOLD_SECONDS)

        # Find one stale job
        stale = await supabase.table('transcription_jobs') \
            .select('job_id, retry_count') \
            .eq('status', 'processing') \
            .lt('last_seen', stale_threshold.isoformat()) \
            .lt('retry_count', JobQueueService.MAX_RETRIES) \
            .order('last_seen', ascending=True) \
            .limit(1) \
            .execute()

        if not stale.data:
            return 0

        job = stale.data[0]

        # Reset to pending with incremented retry count
        await supabase.table('transcription_jobs').update({
            'status': 'pending',
            'retry_count': job['retry_count'] + 1,
            'progress_message': f"Auto-retry attempt {job['retry_count'] + 1}/3"
        }).eq('job_id', job['job_id']).execute()

        # Trigger background processing
        background_tasks.add_task(BackgroundWorker.process_job, job['job_id'])

        return 1

    @staticmethod
    async def get_estimated_duration(file_size_bytes: int) -> Optional[int]:
        """Get estimated duration in seconds based on file size bucket."""
        if file_size_bytes < 100 * 1024 * 1024:
            bucket = '0-100MB'
        elif file_size_bytes < 500 * 1024 * 1024:
            bucket = '100-500MB'
        else:
            bucket = '500MB+'

        result = await supabase.table('job_duration_stats') \
            .select('avg_duration_seconds') \
            .eq('file_size_bucket', bucket) \
            .single() \
            .execute()

        return result.data['avg_duration_seconds'] if result.data else None

    @staticmethod
    async def cleanup_old_jobs():
        """Delete jobs older than 7 days (rolling). Called by Cloud Scheduler."""
        cutoff = datetime.utcnow() - timedelta(days=7)

        # Get GCS paths before deletion
        old_jobs = await supabase.table('transcription_jobs') \
            .select('gcs_path') \
            .lt('created_at', cutoff.isoformat()) \
            .execute()

        # Delete from database
        await supabase.table('transcription_jobs') \
            .delete() \
            .lt('created_at', cutoff.isoformat()) \
            .execute()

        # Delete source files from GCS
        for job in old_jobs.data:
            if job['gcs_path']:
                await gcs_service.delete_file(job['gcs_path'])
```

### Background Worker (Processing Logic)

```python
import asyncio

class BackgroundWorker:
    """Worker for processing transcription jobs."""

    HEARTBEAT_INTERVAL = 30  # seconds

    @staticmethod
    async def process_job(job_id: str):
        """Main processing function - runs in FastAPI BackgroundTasks."""
        heartbeat_task = None

        try:
            job = await JobQueueService.get_job(job_id)
            if not job or job['status'] != 'pending':
                return

            # Mark as processing
            await JobQueueService.mark_processing(job_id)

            # Start heartbeat
            heartbeat_task = asyncio.create_task(
                BackgroundWorker._heartbeat_loop(job_id)
            )

            # Download from GCS
            await JobQueueService.update_progress(job_id, 10, 'downloading', 'Downloading video file...')
            local_path = await gcs_service.download_to_temp(job['gcs_path'])

            # Extract audio
            await JobQueueService.update_progress(job_id, 30, 'extracting', 'Extracting audio...')
            wav_path = await audio_service.extract_audio(local_path)

            # Transcribe
            await JobQueueService.update_progress(job_id, 50, 'transcribing', 'Transcribing audio...')
            segments = await transcribe(wav_path, language=job.get('language'))

            # Speaker diarization
            await JobQueueService.update_progress(job_id, 80, 'diarizing', 'Identifying speakers...')
            segments = await add_speakers(
                segments,
                num_speakers=job.get('num_speakers'),
                min_speakers=job.get('min_speakers'),
                max_speakers=job.get('max_speakers')
            )

            # Generate all formats
            await JobQueueService.update_progress(job_id, 95, 'generating', 'Generating output formats...')
            result_json = build_result(segments)
            result_srt = generate_srt(segments)
            result_vtt = generate_vtt(segments)

            # Calculate video hash for deduplication
            video_hash = await calculate_file_hash(local_path)

            # Complete
            await JobQueueService.mark_completed(
                job_id,
                video_hash,
                result_json,
                result_srt,
                result_vtt
            )

        except Exception as e:
            import logging
            logging.exception(f"Job {job_id} failed: {e}")
            await JobQueueService.mark_failed(job_id, str(e))

        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
            # Cleanup temp files
            await cleanup_temp_files(job_id)

    @staticmethod
    async def _heartbeat_loop(job_id: str):
        """Send heartbeat every 30 seconds."""
        while True:
            await asyncio.sleep(BackgroundWorker.HEARTBEAT_INTERVAL)
            await JobQueueService.update_heartbeat(job_id)
```

### Endpoints to Remove

After migration, remove these SSE endpoints entirely:

- `POST /transcribe_local_stream/`
- `POST /transcribe_gcs_stream/`
- Any related SSE helper functions

---

## Frontend Implementation

### New Component Structure

```
frontend/src/
├── lib/
│   └── supabase.ts                    # Supabase client
├── hooks/
│   ├── useSupabaseRealtime.ts         # Real-time subscriptions
│   ├── useJobTracker.ts               # Job state management
│   ├── useJobNotifications.ts         # Browser notifications
│   └── useJobStorage.ts               # localStorage management
├── components/features/jobs/
│   ├── JobPanel.tsx                   # Slide-out panel container
│   ├── JobList.tsx                    # Paginated job list
│   ├── JobCard.tsx                    # Individual job card
│   ├── JobSubmissionConfirmation.tsx  # Success inline message
│   └── ShareJobDialog.tsx             # Share link generator
├── services/
│   └── jobApi.ts                      # Job API functions
└── types/
    └── job.ts                         # Job TypeScript types
```

### TypeScript Types

```typescript
// types/job.ts
export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export interface Job {
  job_id: string;
  access_token: string;
  status: JobStatus;
  filename: string;
  file_size_bytes: number;
  progress: number;
  progress_stage: string | null;
  progress_message: string | null;
  error_message: string | null;
  result_json: TranscriptionResult | null;
  result_srt: string | null;
  result_vtt: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  cached?: boolean;
  cached_at?: string;
}

export interface JobSubmitResponse {
  job_id: string;
  access_token: string;
  cached: boolean;
  cached_at?: string;
  estimated_duration_seconds?: number;
}

export interface StoredJob {
  job_id: string;
  access_token: string;
}
```

### Supabase Client

```typescript
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
```

### LocalStorage Job Storage

```typescript
// hooks/useJobStorage.ts
const STORAGE_KEY = 'ai-subs-jobs';

export interface StoredJob {
  job_id: string;
  access_token: string;
}

export const useJobStorage = () => {
  const getStoredJobs = (): StoredJob[] => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  };

  const addJob = (job: StoredJob) => {
    const jobs = getStoredJobs();
    if (!jobs.find(j => j.job_id === job.job_id)) {
      jobs.unshift(job);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
    }
  };

  const removeJob = (jobId: string) => {
    const jobs = getStoredJobs().filter(j => j.job_id !== jobId);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
  };

  const removeInvalidJobs = (invalidIds: string[]) => {
    // Silent cleanup of orphan IDs
    const jobs = getStoredJobs().filter(j => !invalidIds.includes(j.job_id));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
  };

  return { getStoredJobs, addJob, removeJob, removeInvalidJobs };
};
```

### Real-time Hook

```typescript
// hooks/useSupabaseRealtime.ts
import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { Job } from '../types/job';

export const useJobRealtime = (jobId: string | null, accessToken: string | null) => {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId || !accessToken) return;

    // Initial fetch
    const fetchJob = async () => {
      try {
        const response = await fetch(
          `/api/jobs/${jobId}?token=${accessToken}`
        );

        if (response.status === 404) {
          // Job no longer exists - silently remove from storage
          setError('expired');
          return;
        }

        if (!response.ok) throw new Error('Failed to fetch job');

        const data = await response.json();
        setJob(data);
      } catch (e) {
        setError('Failed to load job status');
      }
    };

    fetchJob();

    // Real-time subscription
    const subscription = supabase
      .channel(`job:${jobId}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'transcription_jobs',
          filter: `job_id=eq.${jobId}`,
        },
        (payload) => {
          setJob(payload.new as Job);
        }
      )
      .subscribe();

    return () => {
      subscription.unsubscribe();
    };
  }, [jobId, accessToken]);

  return { job, error };
};
```

### Job Tracker Hook

```typescript
// hooks/useJobTracker.ts
import { useState, useEffect, useCallback } from 'react';
import { Job, StoredJob } from '../types/job';
import { useJobStorage } from './useJobStorage';
import { useJobNotifications } from './useJobNotifications';
import { supabase } from '../lib/supabase';

export const useJobTracker = () => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isOffline, setIsOffline] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const { getStoredJobs, addJob, removeInvalidJobs } = useJobStorage();
  const { notifyJobComplete } = useJobNotifications();

  const PER_PAGE = 10;

  const fetchJobs = useCallback(async () => {
    const storedJobs = getStoredJobs();
    if (storedJobs.length === 0) {
      setJobs([]);
      setIsLoading(false);
      return;
    }

    try {
      const response = await fetch('/api/jobs?' + new URLSearchParams({
        tokens: storedJobs.map(j => j.access_token).join(','),
        page: String(page),
        per_page: String(PER_PAGE)
      }));

      if (!response.ok) throw new Error('Failed to fetch jobs');

      const data = await response.json();
      setJobs(data.jobs);
      setTotalPages(Math.ceil(data.total / PER_PAGE));
      setIsOffline(false);

      // Silent cleanup of jobs that no longer exist
      const validIds = new Set(data.jobs.map((j: Job) => j.job_id));
      const invalidIds = storedJobs
        .filter(s => !validIds.has(s.job_id))
        .map(s => s.job_id);

      if (invalidIds.length > 0) {
        removeInvalidJobs(invalidIds);
      }

    } catch (e) {
      // Cache fallback
      setIsOffline(true);
      const cached = localStorage.getItem('ai-subs-jobs-cache');
      if (cached) {
        setJobs(JSON.parse(cached));
      }
    } finally {
      setIsLoading(false);
    }
  }, [page]);

  // Cache jobs for offline fallback
  useEffect(() => {
    if (jobs.length > 0 && !isOffline) {
      localStorage.setItem('ai-subs-jobs-cache', JSON.stringify(jobs));
    }
  }, [jobs, isOffline]);

  // Subscribe to updates for active jobs
  useEffect(() => {
    const activeJobIds = jobs
      .filter(j => ['pending', 'processing'].includes(j.status))
      .map(j => j.job_id);

    if (activeJobIds.length === 0) return;

    const subscription = supabase
      .channel('active-jobs')
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'transcription_jobs',
          filter: `job_id=in.(${activeJobIds.join(',')})`,
        },
        (payload) => {
          const updatedJob = payload.new as Job;

          setJobs(prev => prev.map(j =>
            j.job_id === updatedJob.job_id ? updatedJob : j
          ));

          // Notify on completion
          if (updatedJob.status === 'completed') {
            notifyJobComplete(updatedJob.filename);
          }
        }
      )
      .subscribe();

    return () => {
      subscription.unsubscribe();
    };
  }, [jobs, notifyJobComplete]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  return {
    jobs,
    isLoading,
    isOffline,
    page,
    totalPages,
    setPage,
    refetch: fetchJobs
  };
};
```

### Job Notifications Hook

```typescript
// hooks/useJobNotifications.ts
import { useState, useEffect, useCallback } from 'react';

export const useJobNotifications = () => {
  const [permission, setPermission] = useState<NotificationPermission>('default');
  const [hasPrompted, setHasPrompted] = useState(false);

  useEffect(() => {
    setPermission(Notification.permission);
    setHasPrompted(localStorage.getItem('notification-prompted') === 'true');
  }, []);

  const requestPermission = useCallback(async () => {
    const result = await Notification.requestPermission();
    setPermission(result);
    localStorage.setItem('notification-prompted', 'true');
    setHasPrompted(true);
    return result === 'granted';
  }, []);

  const shouldPrompt = useCallback(() => {
    // Prompt after first job completes if not already prompted
    return permission === 'default' && !hasPrompted;
  }, [permission, hasPrompted]);

  const notifyJobComplete = useCallback((filename: string) => {
    if (permission !== 'granted') return;

    new Notification('Transcription Complete!', {
      body: `${filename} is ready to view`,
      icon: '/icon.png',
      requireInteraction: true,
    });
  }, [permission]);

  return {
    permission,
    requestPermission,
    notifyJobComplete,
    shouldPrompt
  };
};
```

### Job Panel Component (Slide-out)

```typescript
// components/features/jobs/JobPanel.tsx
import { useState } from 'react';
import { useJobTracker } from '../../../hooks/useJobTracker';
import { JobList } from './JobList';

interface JobPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export const JobPanel: React.FC<JobPanelProps> = ({ isOpen, onClose }) => {
  const { jobs, isLoading, isOffline, page, totalPages, setPage } = useJobTracker();

  const activeJobs = jobs.filter(j => ['pending', 'processing'].includes(j.status));
  const completedJobs = jobs.filter(j => j.status === 'completed');
  const failedJobs = jobs.filter(j => j.status === 'failed');

  return (
    <div
      className={`fixed right-0 top-0 h-full w-96 bg-white shadow-xl transform transition-transform z-50 ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      <div className="flex items-center justify-between p-4 border-b">
        <h2 className="text-lg font-semibold">My Transcriptions</h2>
        <button
          onClick={onClose}
          className="p-2 hover:bg-gray-100 rounded"
          aria-label="Close panel"
        >
          ✕
        </button>
      </div>

      {isOffline && (
        <div className="bg-yellow-50 border-b border-yellow-200 p-3 text-sm text-yellow-800">
          Offline - data may be stale
        </div>
      )}

      <div className="overflow-y-auto h-full pb-20">
        {isLoading ? (
          <div className="p-4 text-center text-gray-500">Loading...</div>
        ) : (
          <>
            {activeJobs.length > 0 && (
              <section className="p-4">
                <h3 className="text-sm font-medium text-gray-500 mb-3">
                  Active ({activeJobs.length})
                </h3>
                <JobList jobs={activeJobs} />
              </section>
            )}

            {completedJobs.length > 0 && (
              <section className="p-4 border-t">
                <h3 className="text-sm font-medium text-gray-500 mb-3">
                  Completed
                </h3>
                <JobList jobs={completedJobs} />
              </section>
            )}

            {failedJobs.length > 0 && (
              <section className="p-4 border-t">
                <h3 className="text-sm font-medium text-gray-500 mb-3">
                  Failed
                </h3>
                <JobList jobs={failedJobs} />
              </section>
            )}

            {jobs.length === 0 && (
              <div className="p-8 text-center text-gray-500">
                No transcription jobs yet
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex justify-center gap-2 p-4 border-t">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1 rounded border disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="px-3 py-1">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-3 py-1 rounded border disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};
```

### Job Card Component

```typescript
// components/features/jobs/JobCard.tsx
import { useState } from 'react';
import { Job } from '../../../types/job';
import { ShareJobDialog } from './ShareJobDialog';
import { formatDuration, formatRelativeTime } from '../../../utils/time';

interface JobCardProps {
  job: Job;
  onViewTranscript: (job: Job) => void;
  estimatedRemaining?: number;
}

export const JobCard: React.FC<JobCardProps> = ({
  job,
  onViewTranscript,
  estimatedRemaining
}) => {
  const [showShare, setShowShare] = useState(false);

  const statusStyles = {
    pending: 'bg-gray-100 text-gray-700',
    processing: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    cancelled: 'bg-gray-100 text-gray-500',
  };

  const handleRetry = async () => {
    await fetch(`/api/jobs/${job.job_id}/retry?token=${job.access_token}`, {
      method: 'POST'
    });
  };

  const handleCancel = async () => {
    await fetch(`/api/jobs/${job.job_id}?token=${job.access_token}`, {
      method: 'DELETE'
    });
  };

  return (
    <div className="bg-white rounded-lg border p-4 mb-3">
      <div className="flex items-start justify-between mb-2">
        <span className="font-medium truncate flex-1" title={job.filename}>
          {job.filename}
        </span>
        <span className={`px-2 py-0.5 rounded text-xs ml-2 ${statusStyles[job.status]}`}>
          {job.status}
        </span>
      </div>

      {job.cached && (
        <div className="text-xs text-blue-600 mb-2">
          Result from previous processing on {new Date(job.cached_at!).toLocaleDateString()}
        </div>
      )}

      {job.status === 'processing' && (
        <>
          <div className="w-full bg-gray-200 rounded-full h-1.5 mb-2">
            <div
              className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
              style={{ width: `${job.progress}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-600">
            <span>{job.progress_message}</span>
            {estimatedRemaining && (
              <span>~{formatDuration(estimatedRemaining)} remaining</span>
            )}
          </div>
        </>
      )}

      {job.status === 'pending' && (
        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-500">Waiting to start...</span>
          <button
            onClick={handleCancel}
            className="text-xs text-red-600 hover:underline"
          >
            Cancel
          </button>
        </div>
      )}

      {job.status === 'completed' && (
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => onViewTranscript(job)}
            className="flex-1 bg-blue-600 text-white py-1.5 px-3 rounded text-sm hover:bg-blue-700"
          >
            View Transcript
          </button>
          <button
            onClick={() => setShowShare(true)}
            className="p-1.5 border rounded hover:bg-gray-50"
            aria-label="Share"
          >
            🔗
          </button>
          <div className="relative group">
            <button className="p-1.5 border rounded hover:bg-gray-50">
              ⬇️
            </button>
            <div className="absolute right-0 top-full mt-1 bg-white border rounded shadow-lg hidden group-hover:block z-10">
              <a
                href={`/api/jobs/${job.job_id}/download/srt?token=${job.access_token}`}
                className="block px-4 py-2 hover:bg-gray-50 text-sm"
              >
                Download SRT
              </a>
              <a
                href={`/api/jobs/${job.job_id}/download/vtt?token=${job.access_token}`}
                className="block px-4 py-2 hover:bg-gray-50 text-sm"
              >
                Download VTT
              </a>
              <a
                href={`/api/jobs/${job.job_id}/download/json?token=${job.access_token}`}
                className="block px-4 py-2 hover:bg-gray-50 text-sm"
              >
                Download JSON
              </a>
            </div>
          </div>
        </div>
      )}

      {job.status === 'failed' && (
        <div className="mt-2">
          <p className="text-sm text-red-600 mb-2">{job.error_message}</p>
          <button
            onClick={handleRetry}
            className="text-sm text-blue-600 hover:underline"
          >
            Retry with same settings
          </button>
        </div>
      )}

      <div className="text-xs text-gray-400 mt-2">
        {formatRelativeTime(job.created_at)}
      </div>

      {showShare && (
        <ShareJobDialog
          job={job}
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  );
};
```

### Share Job Dialog

```typescript
// components/features/jobs/ShareJobDialog.tsx
import { useState } from 'react';
import { Job } from '../../../types/job';

interface ShareJobDialogProps {
  job: Job;
  onClose: () => void;
}

export const ShareJobDialog: React.FC<ShareJobDialogProps> = ({ job, onClose }) => {
  const [copied, setCopied] = useState(false);

  const shareUrl = `${window.location.origin}/jobs/${job.job_id}?token=${job.access_token}`;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
        <h3 className="text-lg font-semibold mb-4">Share Transcription</h3>

        <p className="text-sm text-gray-600 mb-4">
          Anyone with this link can view the transcription results.
        </p>

        <div className="flex gap-2">
          <input
            type="text"
            value={shareUrl}
            readOnly
            className="flex-1 px-3 py-2 border rounded text-sm bg-gray-50"
          />
          <button
            onClick={handleCopy}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>

        <button
          onClick={onClose}
          className="w-full mt-4 py-2 border rounded hover:bg-gray-50"
        >
          Close
        </button>
      </div>
    </div>
  );
};
```

---

## User Experience Design

### Updated User Journey

```
1. Upload video (any size)
   ↓
2. Submit job → Panel auto-opens
   ↓
3. See job card with:
   - Status: Processing
   - Progress bar with percentage
   - Estimated time remaining (history-based)
   - "You can safely close this browser"
   ↓
4. Options:
   a. Watch real-time progress in panel
   b. Close browser entirely
   c. Continue using app (panel can be closed/reopened)
   ↓
5. [Processing happens in background with heartbeat]
   ↓
6. On completion:
   - Real-time update if browser open
   - Browser notification (if permitted)
   ↓
7. View completed transcription in existing viewer
   ↓
8. Download SRT/VTT/JSON as needed
```

### Panel States

#### Processing State
```
┌─────────────────────────────────────────┐
│  My Transcriptions                    ✕ │
├─────────────────────────────────────────┤
│                                         │
│  Active (1)                             │
│  ┌─────────────────────────────────────┐│
│  │ demo-video.mp4              Processing│
│  │ ████████████░░░░░░░░░ 65%            │
│  │ Transcribing audio...                │
│  │ ~8 minutes remaining                 │
│  │                                      │
│  │ You can safely close this browser    │
│  └─────────────────────────────────────┘│
│                                         │
└─────────────────────────────────────────┘
```

#### Completed State
```
┌─────────────────────────────────────────┐
│  My Transcriptions                    ✕ │
├─────────────────────────────────────────┤
│                                         │
│  Completed                              │
│  ┌─────────────────────────────────────┐│
│  │ demo-video.mp4            ✓ Completed│
│  │                                      │
│  │ [View Transcript] [🔗] [⬇️]          │
│  │                                      │
│  │ 2 hours ago                          │
│  └─────────────────────────────────────┘│
│                                         │
└─────────────────────────────────────────┘
```

#### Queue Full State (Upload Page)
```
┌─────────────────────────────────────────────────┐
│                                                 │
│   ⚠️ System Busy                                │
│                                                 │
│   3 jobs are currently processing.              │
│   Please try again in a few minutes.            │
│                                                 │
│   [View Current Jobs]                           │
│                                                 │
└─────────────────────────────────────────────────┘
```

#### Cached Result Notice
```
┌─────────────────────────────────────────┐
│  demo-video.mp4              ✓ Completed│
│                                         │
│  ℹ️ Result from Dec 28, 2025            │
│                                         │
│  [View Transcript] [🔗] [⬇️]            │
└─────────────────────────────────────────┘
```

### Notification Permission Flow

After first job completes successfully:
```
┌─────────────────────────────────────────────────┐
│                                                 │
│  🔔 Get notified when jobs complete?            │
│                                                 │
│  We'll send a browser notification when your    │
│  transcriptions are ready, even if you close    │
│  this tab.                                      │
│                                                 │
│     [Enable Notifications]  [Not now]           │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Accessibility Requirements

- ARIA live regions for status updates (`aria-live="polite"`)
- Keyboard navigation for all interactive elements
- Screen reader announcements for job state changes
- 4.5:1 color contrast minimum for all text
- Focus management: panel trap focus when open
- Respect `prefers-reduced-motion` for progress animations
- Close button accessible via Escape key

---

## Implementation Plan

### Phase 1: Supabase Setup

1. Create Supabase project at supabase.com
2. Create `transcription_jobs` table with schema above
3. Create `job_duration_stats` table
4. Enable real-time for `transcription_jobs`
5. Get URL and keys for backend/frontend
6. Add environment variables to Cloud Run and Netlify

### Phase 2: Backend Services

1. Add `supabase` to requirements.txt
2. Create `services/supabase_service.py`
3. Create `services/job_queue_service.py` with full CRUD
4. Create `services/background_worker.py` with heartbeat
5. Create `routers/jobs.py` with all endpoints
6. Register router in `main.py`
7. Set up Cloud Scheduler for stale job check (every 5 min)
8. Set up Cloud Scheduler for cleanup (daily)

### Phase 3: Frontend Core

1. Install `@supabase/supabase-js`
2. Create Supabase client (`lib/supabase.ts`)
3. Create types (`types/job.ts`)
4. Create localStorage hook (`useJobStorage.ts`)
5. Create real-time hook (`useSupabaseRealtime.ts`)
6. Create notifications hook (`useJobNotifications.ts`)
7. Create job tracker hook (`useJobTracker.ts`)

### Phase 4: Frontend Components

1. Create `JobPanel.tsx` (slide-out container)
2. Create `JobList.tsx` (paginated list)
3. Create `JobCard.tsx` (individual job display)
4. Create `ShareJobDialog.tsx` (share link generator)
5. Add panel trigger to header/nav
6. Update upload flow to use job submission

### Phase 5: Integration

1. Wire up job submission from upload component
2. Auto-open panel on job submit
3. Implement notification permission prompt
4. Add direct job URL route (`/jobs/:id`)
5. Wire up transcript viewer from job cards

### Phase 6: Migration & Cleanup

1. Remove SSE endpoints (`/transcribe_local_stream/`, `/transcribe_gcs_stream/`)
2. Remove SSE-related frontend code
3. Test all flows end-to-end
4. Deploy to staging, then production

### Phase 7: Polish

1. Test max 3 concurrent limit edge cases
2. Test heartbeat/stale job recovery
3. Test 7-day cleanup
4. Test browser notifications across browsers
5. Test offline/cache fallback
6. Mobile responsiveness testing
7. Accessibility audit

---

## Environment Variables

### Backend

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
```

### Frontend

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
```

---

## Files to Create/Modify

### Backend (New)

| File                            | Purpose                    |
| ------------------------------- | -------------------------- |
| `services/supabase_service.py`  | Supabase client connection |
| `services/job_queue_service.py` | Job CRUD operations        |
| `services/background_worker.py` | Transcription processing   |
| `routers/jobs.py`               | Job API endpoints          |

### Backend (Modify)

| File               | Changes                   |
| ------------------ | ------------------------- |
| `config.py`        | Add Supabase URL/key vars |
| `main.py`          | Register jobs router      |
| `requirements.txt` | Add `supabase` package    |

### Backend (Remove)

| File/Function                     | Reason          |
| --------------------------------- | --------------- |
| `/transcribe_local_stream/`       | Replaced by jobs|
| `/transcribe_gcs_stream/`         | Replaced by jobs|
| SSE helper functions              | No longer needed|

### Frontend (New)

| File                                              | Purpose                 |
| ------------------------------------------------- | ----------------------- |
| `lib/supabase.ts`                                 | Supabase client init    |
| `types/job.ts`                                    | TypeScript types        |
| `hooks/useSupabaseRealtime.ts`                    | Real-time subscriptions |
| `hooks/useJobTracker.ts`                          | Job state management    |
| `hooks/useJobNotifications.ts`                    | Browser notifications   |
| `hooks/useJobStorage.ts`                          | localStorage management |
| `components/features/jobs/JobPanel.tsx`           | Slide-out panel         |
| `components/features/jobs/JobList.tsx`            | Job list component      |
| `components/features/jobs/JobCard.tsx`            | Job card component      |
| `components/features/jobs/ShareJobDialog.tsx`     | Share link dialog       |

### Frontend (Modify)

| File                      | Changes                     |
| ------------------------- | --------------------------- |
| `App.tsx`                 | Add job route, panel state  |
| `services/api.ts`         | Add job API functions       |
| Upload component          | Job-based submission        |
| `package.json`            | Add `@supabase/supabase-js` |
| Header/Nav component      | Add jobs panel trigger      |

---

## Appendix: Alternative Approaches

### Option 1: Cloud Tasks + Pub/Sub

**Architecture**:

```
Browser → Cloud Run API → Cloud Tasks → Cloud Run Worker → Database
```

**Pros**:

- Enterprise-grade job queue
- Automatic retries
- Scales to thousands of jobs

**Cons**:

- Complex setup
- $15-50/month
- Overkill for personal use

### Option 2: SQLite + Polling

**Architecture**:

```
Browser → Cloud Run → SQLite
Browser polls every 3-5 seconds
```

**Pros**:

- No new services
- Simple implementation

**Cons**:

- Data loss on Cloud Run restart
- Polling creates unnecessary requests
- No instant updates

### Option 3: Firestore

**Architecture**:

```
Browser → Cloud Run → Firestore
Browser subscribes to real-time updates
```

**Pros**:

- Real-time updates
- GCP native
- Free tier

**Cons**:

- NoSQL (different patterns)
- Migration effort from SQLite

### Option 4: Cloud SQL (PostgreSQL)

**Architecture**:

```
Browser → Cloud Run → Cloud SQL
Browser polls for updates
```

**Pros**:

- Familiar SQL
- Robust, managed service

**Cons**:

- $7-9/month minimum
- No real-time (requires polling)
- More complex than Supabase

---

## Success Metrics

| Metric                     | Target     | How to Measure            |
| -------------------------- | ---------- | ------------------------- |
| Browser close anxiety      | Eliminated | User can close and return |
| Job completion visibility  | 100%       | Jobs visible on return    |
| Notification delivery      | >95%       | Browser notification logs |
| Max concurrent enforcement | 100%       | API rejection rate        |
| Stale job recovery         | 100%       | No stuck processing jobs  |
| 7-day cleanup              | Automated  | Database size stable      |

---

## References

- [Supabase Documentation](https://supabase.com/docs)
- [Supabase Real-time](https://supabase.com/docs/guides/realtime)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Web Notifications API](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API)
- [Cloud Scheduler Documentation](https://cloud.google.com/scheduler/docs)
