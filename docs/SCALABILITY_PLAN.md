# Scalability Architecture Redesign: AI-Subs Backend

> **Status:** Planning - Not Implemented
> **Created:** 2026-01-10
> **Priority:** High

---

## Executive Summary

**Problem:** Backend processes only 1 transcription at a time. With 5-10 users, most get rejected (HTTP 429) or wait 40+ minutes.

**Solution:** Full architecture redesign with:
- Google Cloud Tasks for persistent job queuing
- Separate worker service for GPU processing
- Job priorities and fair scheduling
- Horizontal scaling with multiple GPU instances

**Constraints:**
- Keep Whisper "small" model (quality over speed)
- Speaker diarization always required
- Full architecture solution preferred

---

## Current Architecture Analysis

### What We Have Now

| Resource | Current | Effective Capacity |
|----------|---------|-------------------|
| Cloud Run instances | max=1 | 1 active transcription |
| GPU | 1x NVIDIA L4 (24GB) | ~1 Whisper + Diarization job |
| Memory | 16Gi | Borderline for 1 job (~10-16GB used) |
| CPU | 4 vCPU | Shared across all operations |
| GPU Quota | 3 units | Insufficient (need 10/instance) |

### Concurrency Limits in Code

| Setting | Value | Location |
|---------|-------|----------|
| `GLOBAL_CONCURRENT_LIMIT` | 3 | `services/job_queue_service.py:12` |
| `_transcription_executor` | 1 worker | `services/background_worker.py:14` |
| `max_instances` | 1 | `backend/deploy.sh:39` |

### What Happens with 5-10 Users Today

```
User 1: Submits job → Starts processing immediately
User 2: Submits job → Queued (waits for executor)
User 3: Submits job → Queued (waits for executor)
User 4: Submits job → HTTP 429 "System busy"
User 5-10: HTTP 429 "System busy" (rejected)

Processing Order: User 1 (20min) → User 2 (20min) → User 3 (20min)
Total wait for User 3: ~40 minutes
```

### Memory Usage Per Job

| Stage | Memory |
|-------|--------|
| Whisper model | 2-4GB |
| Speaker diarization | 4-6GB |
| Audio processing | 1-2GB |
| Translation | 1-2GB |
| **Total** | **10-16GB** |

---

## Current vs Target Architecture

### Current Architecture
```
┌─────────────────────────────────────────────────────────┐
│                  Cloud Run (Single Instance)            │
│  ┌─────────────┐    ┌──────────────────────────────┐   │
│  │  FastAPI    │───▶│  BackgroundTasks (in-memory) │   │
│  │  (API)      │    │  ThreadPoolExecutor(1)       │   │
│  └─────────────┘    └──────────────────────────────┘   │
│                              │                          │
│                              ▼                          │
│                     ┌────────────────┐                  │
│                     │  GPU (L4)      │                  │
│                     │  Whisper       │                  │
│                     │  Diarization   │                  │
│                     └────────────────┘                  │
└─────────────────────────────────────────────────────────┘
```
**Problems:** Single point of failure, no persistence, no scaling

### Target Architecture
```
┌────────────────┐     ┌─────────────────┐     ┌──────────────────────┐
│   Frontend     │────▶│   API Service   │────▶│   Google Cloud Tasks │
│   (Netlify)    │     │   (Cloud Run)   │     │   (Persistent Queue) │
└────────────────┘     │   - No GPU      │     └──────────┬───────────┘
                       │   - Auth/API    │                │
                       │   - Job status  │                │
                       └─────────────────┘                │
                               ▲                          │
                               │ Status updates           │
                               │ (Supabase)               ▼
                       ┌───────┴─────────────────────────────────────┐
                       │              Worker Pool                     │
                       │  ┌─────────────┐  ┌─────────────┐           │
                       │  │  Worker 1   │  │  Worker 2   │  ...      │
                       │  │  GPU (L4)   │  │  GPU (L4)   │           │
                       │  │  Whisper    │  │  Whisper    │           │
                       │  └─────────────┘  └─────────────┘           │
                       └─────────────────────────────────────────────┘
```

**Benefits:**
- Jobs persist through restarts (no more lost jobs)
- Auto-scaling: 0 workers when idle, up to 5 during peak
- Queue position feedback for users
- Job priorities (future premium tier)
- Automatic retry on failure

---

## Implementation Plan

### Phase 1: Infrastructure Setup

#### 1.1 Create Cloud Tasks Queue
```bash
# Create queue for transcription jobs
gcloud tasks queues create transcription-jobs \
  --location=us-central1 \
  --max-dispatches-per-second=1 \
  --max-concurrent-dispatches=3 \
  --max-attempts=3 \
  --min-backoff=60s \
  --max-backoff=3600s

# Create high-priority queue for premium users (future)
gcloud tasks queues create transcription-priority \
  --location=us-central1 \
  --max-dispatches-per-second=2 \
  --max-concurrent-dispatches=5
```

#### 1.2 Request GPU Quota Increase
- Request 50+ units of `NvidiaL4GpuAllocNoZonalRedundancyPerProjectRegion`
- URL: https://console.cloud.google.com/iam-admin/quotas?project=ai-subs-poc
- Justification: Multi-user transcription service

#### 1.3 Create Service Account for Workers
```bash
gcloud iam service-accounts create transcription-worker \
  --display-name="Transcription Worker"

# Grant necessary permissions
gcloud projects add-iam-policy-binding ai-subs-poc \
  --member="serviceAccount:transcription-worker@ai-subs-poc.iam.gserviceaccount.com" \
  --role="roles/cloudtasks.enqueuer"
```

---

### Phase 2: Code Changes

#### 2.1 New File: `backend/services/cloud_tasks_service.py`
```python
"""
Cloud Tasks integration for persistent job queuing.

Responsibilities:
- Create tasks in Cloud Tasks queue
- Handle task callbacks from Cloud Tasks
- Manage job priorities
- Retry failed jobs with exponential backoff
"""

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import json

class CloudTasksService:
    def __init__(self):
        self.client = tasks_v2.CloudTasksClient()
        self.project = "ai-subs-poc"
        self.location = "us-central1"
        self.queue = "transcription-jobs"

    def create_transcription_task(self, job_id: str, priority: int = 5):
        """Queue a transcription job in Cloud Tasks."""
        parent = self.client.queue_path(self.project, self.location, self.queue)

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"https://ai-subs-worker-xxxxx.run.app/process/{job_id}",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"job_id": job_id, "priority": priority}).encode()
            }
        }

        # Add scheduling for priority (higher priority = sooner)
        if priority > 5:
            task["schedule_time"] = timestamp_pb2.Timestamp()  # Now

        return self.client.create_task(parent=parent, task=task)

    def get_queue_depth(self) -> int:
        """Get number of pending tasks."""
        # Implementation for queue monitoring
        pass
```

#### 2.2 New File: `backend/worker/main.py`
```python
"""
Dedicated transcription worker service.

This runs as a separate Cloud Run service with GPU.
It receives tasks from Cloud Tasks and processes them.
"""

from fastapi import FastAPI, BackgroundTasks
from services.background_worker import process_job

app = FastAPI()

@app.post("/process/{job_id}")
async def process_transcription(job_id: str, background_tasks: BackgroundTasks):
    """
    Called by Cloud Tasks to process a transcription job.
    Returns 200 immediately, processes in background.
    If processing fails, Cloud Tasks will retry.
    """
    background_tasks.add_task(process_job, job_id)
    return {"status": "accepted", "job_id": job_id}

@app.get("/health")
async def health():
    return {"status": "healthy", "gpu": check_gpu_available()}
```

#### 2.3 Modify: `backend/routers/jobs.py`
**Changes:**
- Replace `BackgroundTasks` with Cloud Tasks enqueue
- Add queue position endpoint
- Add estimated wait time calculation

```python
# In submit_job endpoint, replace:
# background_tasks.add_task(process_job, job_id)

# With:
from services.cloud_tasks_service import CloudTasksService
cloud_tasks = CloudTasksService()
cloud_tasks.create_transcription_task(job_id, priority=job.priority)
```

#### 2.4 New Endpoint: Queue Status
**File:** `backend/routers/jobs.py`
```python
@router.get("/queue/status")
async def get_queue_status():
    """Get current queue depth and estimated wait time."""
    return {
        "queue_depth": cloud_tasks.get_queue_depth(),
        "active_workers": get_active_worker_count(),
        "estimated_wait_minutes": calculate_wait_time(),
        "processing_jobs": get_processing_count()
    }
```

#### 2.5 Add Job Priority Support
**File:** `backend/models/job.py`
```python
class JobCreate(BaseModel):
    video_url: str
    priority: int = 5  # 1-10, higher = more urgent
    # ...
```

---

### Phase 3: Worker Deployment

#### 3.1 New Dockerfile: `backend/worker/Dockerfile`
Same as main Dockerfile but:
- Only includes transcription dependencies
- No API routes, just worker logic
- Optimized for GPU processing

#### 3.2 Worker Deploy Script: `backend/worker/deploy.sh`
```bash
gcloud run deploy ai-subs-worker \
  --image=us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-worker:latest \
  --platform=managed \
  --region=us-central1 \
  --memory=16Gi \
  --cpu=4 \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --min-instances=0 \
  --max-instances=5 \
  --timeout=3600 \
  --concurrency=1 \
  --no-allow-unauthenticated
```

#### 3.3 API Service (No GPU)
```bash
gcloud run deploy ai-subs-api \
  --image=us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-api:latest \
  --memory=2Gi \
  --cpu=2 \
  --min-instances=1 \
  --max-instances=10 \
  --allow-unauthenticated
```

---

### Phase 4: Database Schema Updates

#### 4.1 Add Priority Column
```sql
ALTER TABLE jobs ADD COLUMN priority INTEGER DEFAULT 5;
ALTER TABLE jobs ADD COLUMN queue_position INTEGER;
ALTER TABLE jobs ADD COLUMN worker_instance TEXT;
```

#### 4.2 Add Queue Metrics Table
```sql
CREATE TABLE queue_metrics (
  id UUID PRIMARY KEY,
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  queue_depth INTEGER,
  active_workers INTEGER,
  avg_processing_time INTEGER,
  jobs_completed_hour INTEGER
);
```

---

### Phase 5: Monitoring & Observability

#### 5.1 Cloud Monitoring Dashboard
- Queue depth over time
- Worker utilization
- Job completion rate
- Error rate by stage
- GPU memory usage

#### 5.2 Alerting
- Queue depth > 20 jobs: Warning
- Queue depth > 50 jobs: Critical
- Worker error rate > 5%: Alert
- Average wait time > 30 min: Alert

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `backend/services/cloud_tasks_service.py` | Create | Cloud Tasks integration |
| `backend/worker/main.py` | Create | Worker service entry point |
| `backend/worker/Dockerfile` | Create | Worker-specific Docker image |
| `backend/worker/deploy.sh` | Create | Worker deployment script |
| `backend/routers/jobs.py` | Modify | Replace BackgroundTasks with Cloud Tasks |
| `backend/models/job.py` | Modify | Add priority field |
| `backend/deploy.sh` | Modify | Remove GPU, reduce resources |
| `frontend/src/components/JobStatus.tsx` | Modify | Show queue position |

---

## Rollout Plan

### Stage 1: Parallel Deployment (Safe)
1. Deploy worker service alongside existing
2. Keep existing system running
3. Route 10% of new jobs to Cloud Tasks
4. Monitor for issues

### Stage 2: Gradual Migration
1. Increase Cloud Tasks routing to 50%
2. Reduce API service GPU allocation
3. Monitor queue depth and wait times

### Stage 3: Full Cutover
1. Route 100% to Cloud Tasks
2. Remove GPU from API service
3. Scale workers based on demand

---

## Cost Analysis

| Component | Instances | Monthly Cost |
|-----------|-----------|--------------|
| API Service (no GPU) | 1-10 | ~$50-100 |
| Worker (L4 GPU) | 0-5 | ~$200-1000 |
| Cloud Tasks | N/A | ~$5 |
| **Total** | | **$255-1105** |

vs Current: ~$200/month (but can't scale)

---

## Verification Steps

1. **Unit Tests:**
   - Cloud Tasks service creates tasks correctly
   - Worker processes jobs end-to-end
   - Priority queue ordering works

2. **Integration Tests:**
   - Submit 10 concurrent jobs
   - Verify queue ordering
   - Check all complete successfully

3. **Load Tests:**
   - Simulate 50 concurrent users
   - Measure queue depth and wait times
   - Verify no jobs dropped

4. **Failover Tests:**
   - Kill worker mid-job
   - Verify Cloud Tasks retries
   - Check job completes on new worker

---

## Quick Reference: Current Bottlenecks

| Resource | Bottleneck | Impact |
|----------|-----------|--------|
| **GPU VRAM (24GB)** | 1 job at a time | Only 1 real concurrent job |
| **CPU** | 4 cores | Shared across all executors |
| **RAM (16GB)** | Audio + models | Limits to 1 job safely |
| **ThreadPoolExecutor** | max_workers=1 | Sequential processing |
| **Cloud Run** | max_instances=1 | No horizontal scaling |
| **GPU Quota** | 3 units (need 10) | Can't add more instances |

---

## Immediate Action Items

1. [ ] Request GPU quota increase (can take days for approval)
2. [ ] Set up Cloud Tasks queue in GCP console
3. [ ] Create worker service account with permissions
4. [ ] Begin code refactoring for Cloud Tasks integration
