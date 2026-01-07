# API Security Analysis & Plan

## Current Security Layers

| Layer             | Protection                              | Status  |
| ----------------- | --------------------------------------- | ------- |
| **CORS**          | Only `ai-subs.netlify.app` allowed      | Working |
| **App Password**  | SHA-256 hashed password → session token | Working |
| **Supabase Auth** | JWT tokens with email verification      | Working |

---

## Endpoint Security Audit

### Protected Endpoints (require auth)

| Endpoint          | Protection       | Notes              |
| ----------------- | ---------------- | ------------------ |
| `/api/admin/*`    | `@require_admin` | Admin-only access  |
| `/api/settings/*` | `@require_auth`  | User settings      |
| `/api/keys/*`     | `@require_auth`  | API key management |
| `/api/auth/me`    | `@require_auth`  | Get current user   |

### Open Endpoints (NO auth required)

| Endpoint               | Risk Level | Impact                                       |
| ---------------------- | ---------- | -------------------------------------------- |
| `/api/transcription/*` | **HIGH**   | Anyone can transcribe videos (compute costs) |
| `/api/jobs/*`          | **HIGH**   | Anyone can submit/view jobs                  |
| `/api/video/*`         | **HIGH**   | Anyone can upload/manage videos              |
| `/api/chat/*`          | **HIGH**   | Anyone can use Grok/Groq API (API costs)     |
| `/api/upload/*`        | **MEDIUM** | Anyone can get signed URLs for GCS           |
| `/api/speaker/*`       | **MEDIUM** | Speaker management                           |
| `/api/diagnostics/*`   | **LOW**    | System status (info disclosure)              |
| `/api/auth/*`          | **OK**     | Login/register must be open                  |

---

## Risk Assessment

### What an attacker could do:

1. **Upload videos and transcribe them** - Costs you GPU compute time
2. **Use your Grok/Groq API** - Costs you API credits
3. **Fill up GCS storage** - Storage costs
4. **DoS via heavy transcription jobs** - Resource exhaustion

### Attack vectors:

- Direct access to `/docs` Swagger UI
- curl/Postman/any HTTP client
- Automated scripts

---

## Missing Feature: Job Ownership

### Current State

Jobs are created WITHOUT a `user_id` field. See `services/job_queue_service.py:77-95`:

- No user association
- Anyone can view any job
- No "my jobs" filtering possible

### Required Changes

#### 1. Add `user_id` column to jobs table (Supabase)

```sql
ALTER TABLE jobs ADD COLUMN user_id UUID REFERENCES auth.users(id);
CREATE INDEX idx_jobs_user_id ON jobs(user_id);
```

#### 2. Update `JobQueueService.create_job()` to accept user_id

**File:** `services/job_queue_service.py`

```python
@staticmethod
def create_job(
    filename: str,
    gcs_path: str,
    file_size_bytes: int,
    video_hash: str,
    user_id: str = None,  # Add this
    **params
) -> Dict:
    ...
    job_data = {
        ...
        "user_id": user_id,  # Add this
    }
```

#### 3. Update job submission endpoint to pass user_id

**File:** `routers/jobs.py`

```python
@router.post("/submit", response_model=JobSubmitResponse)
@require_auth
async def submit_job(request: Request, ...):
    user_id = request.state.user["id"]
    job = JobQueueService.create_job(
        ...,
        user_id=user_id
    )
```

#### 4. Filter jobs by user

**File:** `routers/jobs.py`

```python
@router.get("", response_model=JobListResponse)
@require_auth
async def list_jobs(request: Request, ...):
    user_id = request.state.user["id"]
    # Only return jobs belonging to this user
    jobs = JobQueueService.get_jobs_for_user(user_id)
```

#### 5. Add ownership check for job access

```python
@router.get("/{job_id}", response_model=JobStatusResponse)
@require_auth
async def get_job(request: Request, job_id: str):
    user_id = request.state.user["id"]
    job = JobQueueService.get_job(job_id)

    if job["user_id"] != user_id:
        raise HTTPException(403, "Not your job")

    return job
```

---

## Recommended Fixes

### Priority 1: Disable /docs in Production

**File:** `backend/main.py`

```python
# Change from:
app = FastAPI(title="AI-Subs API", ...)

# To:
import os
docs_url = "/docs" if os.getenv("ENVIRONMENT") != "production" else None
redoc_url = "/redoc" if os.getenv("ENVIRONMENT") != "production" else None

app = FastAPI(
    title="AI-Subs API",
    docs_url=docs_url,
    redoc_url=redoc_url,
    ...
)
```

Then add `ENVIRONMENT=production` to Cloud Run env vars.

### Priority 2: Add Auth to Core Endpoints

Apply `@require_auth` decorator to these routers:

- `routers/transcription.py`
- `routers/jobs.py`
- `routers/video.py`
- `routers/chat.py`
- `routers/upload.py`
- `routers/speaker.py`

**Example:**

```python
from middleware.auth import require_auth

@router.post("/transcribe/")
@require_auth
async def transcribe(request: Request, ...):
    # request.state.user available
    ...
```

### Priority 3: Rate Limiting

Add rate limiting middleware to prevent abuse:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/transcribe/")
@limiter.limit("5/hour")
async def transcribe(...):
    ...
```

### Priority 4: API Key Authentication (Alternative)

For programmatic access, consider API key auth:

- Generate API keys per user
- Validate via header: `X-API-Key: xxx`
- Track usage per key

---

## Implementation Checklist

### Phase 1: Disable Public Access

- [ ] Disable `/docs` and `/redoc` in production
- [ ] Add `@require_auth` to transcription endpoints
- [ ] Add `@require_auth` to jobs endpoints
- [ ] Add `@require_auth` to video endpoints
- [ ] Add `@require_auth` to chat endpoints
- [ ] Add `@require_auth` to upload endpoints
- [ ] Add `@require_auth` to speaker endpoints

### Phase 2: Job Ownership

- [ ] Add `user_id` column to jobs table in Supabase
- [ ] Update `JobQueueService.create_job()` to accept `user_id`
- [ ] Update `/api/jobs/submit` to pass authenticated user's ID
- [ ] Update `/api/jobs` list endpoint to filter by user
- [ ] Add ownership check to `/api/jobs/{job_id}` endpoint
- [ ] Add ownership check to job download/video endpoints
- [ ] Handle shared links (allow access without ownership for shared jobs)

### Phase 3: Additional Security (Optional)

- [ ] Add rate limiting
- [ ] Test all endpoints still work with frontend
- [ ] Deploy and verify

---

## Notes

- The frontend already handles authentication via cookies
- After adding `@require_auth`, ensure frontend sends credentials
- Some endpoints may need to stay open (e.g., shared links)
- Consider creating a `@require_auth_or_share_token` for public sharing features

---

_Created: 2026-01-07_
