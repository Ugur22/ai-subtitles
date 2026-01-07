# Authentication System Implementation Guide

This guide covers Phases 1-2 of the authentication system implementation based on `AUTH_SYSTEM_SPEC.md`.

## Overview

This implementation provides:
- **Phase 1**: Full user authentication with Supabase Auth
  - Registration with invite codes
  - Email verification (6-digit codes)
  - Login/logout with HttpOnly cookies
  - Password reset flow
  - Authentication middleware with 5-min caching

- **Phase 2**: API key management
  - Encrypted storage (AES-256-GCM)
  - Async validation
  - Support for groq, xai, openai, anthropic
  - Admin dashboard
  - User settings
  - Upload rate limiting (50/day, 4GB max)

## Files Created

### Backend Files

#### Middleware
- `/Users/ugurertas/projects/ai-subs/backend/middleware/__init__.py`
- `/Users/ugurertas/projects/ai-subs/backend/middleware/auth.py` - Authentication decorators (@require_auth, @require_admin)
- `/Users/ugurertas/projects/ai-subs/backend/middleware/rate_limit.py` - Upload quotas (50/day)

#### Services
- `/Users/ugurertas/projects/ai-subs/backend/services/encryption.py` - AES-256-GCM encryption for API keys
- `/Users/ugurertas/projects/ai-subs/backend/services/key_validator.py` - Async API key validation
- `/Users/ugurertas/projects/ai-subs/backend/services/email.py` - Email service (stub, needs SMTP config)

#### Routers
- `/Users/ugurertas/projects/ai-subs/backend/routers/auth_new.py` - Auth endpoints (register, login, verify, reset)
- `/Users/ugurertas/projects/ai-subs/backend/routers/keys.py` - API key management
- `/Users/ugurertas/projects/ai-subs/backend/routers/admin.py` - Admin dashboard
- `/Users/ugurertas/projects/ai-subs/backend/routers/settings.py` - User settings

#### Database
- `/Users/ugurertas/projects/ai-subs/backend/sql/auth_system_migration.sql` - Complete database schema

## Setup Instructions

### Step 1: Database Migration

1. Go to your Supabase project SQL editor
2. Run the migration file:
   ```sql
   -- Copy and paste contents of backend/sql/auth_system_migration.sql
   ```

3. Create initial invite codes:
   ```sql
   INSERT INTO invite_codes (code) VALUES (gen_random_uuid());
   INSERT INTO invite_codes (code) VALUES (gen_random_uuid());
   INSERT INTO invite_codes (code) VALUES (gen_random_uuid());

   -- Get the codes to use for registration
   SELECT code FROM invite_codes WHERE used_by IS NULL;
   ```

### Step 2: Update main.py

Replace `/Users/ugurertas/projects/ai-subs/backend/main.py` to include new routers:

```python
# Import new routers
from routers import (
    video, chat, speaker, transcription, upload, jobs,
    diagnostics
)
from routers import auth_new, keys, admin, settings

# Include routers (REPLACE old auth.router line)
app.include_router(transcription.router)
app.include_router(speaker.router)
app.include_router(chat.router)
app.include_router(video.router)
app.include_router(upload.router)
app.include_router(jobs.router)

# New auth routers
app.include_router(auth_new.router)  # Instead of old auth.router
app.include_router(keys.router)
app.include_router(admin.router)
app.include_router(settings.router)

app.include_router(diagnostics.router)
```

### Step 3: Update Requirements

Add to `backend/requirements.txt`:
```
cryptography>=41.0.0  # For AES-256-GCM encryption
httpx>=0.24.0  # For async API key validation
```

Install:
```bash
cd backend
pip install cryptography httpx
```

### Step 4: Environment Variables

No new env vars required! The encryption key is stored in Supabase Vault.

Optional (for email sending later):
```env
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your_sendgrid_api_key
SMTP_FROM=noreply@yourdomain.com
```

### Step 5: Create First Admin User

1. Register a user through the API (need invite code from Step 1)
2. Promote to admin:
   ```sql
   UPDATE user_profiles
   SET is_admin = TRUE
   WHERE email = 'your-email@example.com';
   ```

### Step 6: Update Other Routers (Phase 3 - TODO)

The following files need updates to use the new auth system:

#### Update upload.py
```python
from middleware.auth import require_auth
from middleware.rate_limit import check_upload_limit, validate_file_size

@router.post("/api/upload/signed-url")
@require_auth
async def get_signed_url(request: Request, file_info: FileInfo):
    user_id = request.state.user["id"]

    # Validate file size
    validate_file_size(file_info.size)

    # Check rate limit
    if not await check_upload_limit(user_id):
        raise HTTPException(429, "Daily upload limit reached (50/day)")

    # ... rest of handler
```

#### Update jobs.py
Add user_id filtering:
```python
@router.get("", response_model=JobListResponse)
@require_auth
async def list_jobs(request: Request, page: int = 1, per_page: int = 10):
    user_id = request.state.user["id"]

    # Filter jobs by user_id
    response = client.table("jobs").select("*").eq("user_id", user_id).execute()
    # ... rest of handler
```

#### Update chat.py
Use user's API keys instead of server keys:
```python
from services.encryption import get_encryption_key, decrypt_api_key

@router.post("/chat/")
@require_auth
async def chat_with_video(request: Request, chat_request: ChatRequest):
    user_id = request.state.user["id"]
    provider = chat_request.provider  # groq, xai, openai, anthropic

    # Get user's API key
    client = SupabaseService.get_client()
    key_response = client.table("user_api_keys").select("encrypted_key, is_valid").eq(
        "user_id", user_id
    ).eq("provider", provider).single().execute()

    if not key_response.data:
        raise HTTPException(
            400,
            f"No API key configured for {provider}. Please add your API key in settings."
        )

    if key_response.data["is_valid"] == False:
        raise HTTPException(
            400,
            f"Your {provider} API key is invalid. Please update it in settings."
        )

    # Decrypt key
    encryption_key = await get_encryption_key()
    api_key = decrypt_api_key(key_response.data["encrypted_key"], encryption_key)

    # Use api_key for LLM request instead of settings.GROQ_API_KEY, etc.
    # ... rest of handler
```

## API Endpoints

### Authentication

#### POST /api/auth/register
Register new user with invite code.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "invite_code": "uuid-from-admin"
}
```

**Response:**
```json
{
  "user_id": "uuid",
  "message": "Registration successful. Please check your email for verification code."
}
```

#### POST /api/auth/verify-email
Verify email with 6-digit code.

**Request:**
```json
{
  "user_id": "uuid",
  "code": "123456"
}
```

#### POST /api/auth/login
Login and get HttpOnly cookie (7 days).

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword"
}
```

**Response:** Sets `auth_token` HttpOnly cookie.

#### POST /api/auth/logout
Logout and clear cookie.

#### POST /api/auth/forgot-password
Request password reset code.

#### POST /api/auth/reset-password
Reset password with code.

#### GET /api/auth/me
Get current user profile (requires auth).

### API Keys

#### GET /api/keys
List user's API keys (requires auth).

**Response:**
```json
[
  {
    "provider": "groq",
    "key_suffix": "abc123",
    "is_valid": true,
    "validation_error": null,
    "validated_at": "2026-01-07T12:00:00Z",
    "created_at": "2026-01-07T11:00:00Z"
  }
]
```

#### POST /api/keys
Add/update API key (requires auth).

**Request:**
```json
{
  "provider": "groq",
  "api_key": "gsk_..."
}
```

Triggers async validation in background.

#### DELETE /api/keys/{provider}
Delete API key (requires auth).

#### POST /api/keys/{provider}/test
Test API key immediately (requires auth).

### Admin

#### GET /api/admin/users
List all users (requires admin).

#### POST /api/admin/invite-codes
Create invite code (requires admin).

#### GET /api/admin/invite-codes
List invite codes (requires admin).

#### DELETE /api/admin/invite-codes/{code}
Delete invite code (requires admin).

#### DELETE /api/admin/users/{user_id}
Hard delete user (requires admin).

#### POST /api/admin/users/{user_id}/invalidate-keys
Force user to re-enter all API keys (requires admin).

#### GET /api/admin/stats
Get dashboard stats (requires admin).

### Settings

#### PATCH /api/settings
Update profile settings (requires auth).

**Request:**
```json
{
  "display_name": "John Doe",
  "default_llm_provider": "groq"
}
```

#### DELETE /api/settings/account
Hard delete own account (requires auth).

## Security Features

1. **HttpOnly Cookies**: Session tokens stored in HttpOnly cookies (XSS protection)
2. **Token Caching**: 5-minute cache to reduce database load
3. **Email Verification**: Required before first login
4. **Encrypted Keys**: API keys encrypted with AES-256-GCM
5. **Encryption Key in Vault**: Master encryption key stored in Supabase Vault
6. **Rate Limiting**: 50 uploads/day, 4GB max file size
7. **Row Level Security**: Supabase RLS policies on all user tables
8. **Generic Errors**: Don't reveal if email exists (privacy)
9. **Invite-Only**: Registration requires invite code

## Testing

### Manual Testing

1. **Register Flow**:
   ```bash
   # Get invite code from admin
   curl -X POST http://localhost:8000/api/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"test@example.com","password":"password123","invite_code":"YOUR_CODE"}'

   # Check console for verification code, then verify
   curl -X POST http://localhost:8000/api/auth/verify-email \
     -H "Content-Type: application/json" \
     -d '{"user_id":"USER_ID","code":"123456"}'
   ```

2. **Login Flow**:
   ```bash
   curl -X POST http://localhost:8000/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"test@example.com","password":"password123"}' \
     -c cookies.txt  # Save cookie
   ```

3. **Protected Endpoint**:
   ```bash
   curl http://localhost:8000/api/auth/me -b cookies.txt
   ```

4. **Add API Key**:
   ```bash
   curl -X POST http://localhost:8000/api/keys \
     -H "Content-Type: application/json" \
     -b cookies.txt \
     -d '{"provider":"groq","api_key":"gsk_..."}'
   ```

5. **Test API Key**:
   ```bash
   curl -X POST http://localhost:8000/api/keys/groq/test -b cookies.txt
   ```

## Known Limitations & TODOs

### Current Implementation

1. **Email Service**: Currently logs codes to console. Need to implement real email:
   - Configure SMTP in `services/email.py`
   - Add SendGrid/AWS SES integration
   - Add email templates

2. **Supabase Auth Admin API**: Some endpoints use `client.auth.admin.*` which requires service role key. Make sure `SUPABASE_SERVICE_KEY` is the service role key, not anon key.

3. **Frontend**: This is backend-only implementation. Frontend needs:
   - Login/Register pages
   - Settings panel with API key management
   - Admin dashboard
   - Protected routes

### Phase 3 Tasks (Not Implemented)

1. Update `upload.py` with auth + rate limiting
2. Update `jobs.py` to filter by user_id
3. Update `chat.py` to use user's API keys
4. Add usage logging to all endpoints
5. Remove old `auth.py` (current password gate)

### Phase 4 Tasks (Not Implemented)

1. Frontend implementation (see AUTH_SYSTEM_SPEC.md)
2. Email templates
3. Email provider configuration
4. Testing suite

## Troubleshooting

### "Encryption key not found in Supabase Vault"

Run the vault creation SQL:
```sql
SELECT vault.create_secret(
  encode(gen_random_bytes(32), 'hex'),
  'api_key_encryption'
);
```

### "Auth user may be orphaned"

If user profile creation fails during registration, the Supabase auth user isn't automatically deleted (requires admin API). Manually clean up:
```sql
-- In Supabase SQL editor
SELECT id, email FROM auth.users WHERE id NOT IN (SELECT id FROM user_profiles);
```

### "Invalid or expired token"

Tokens expire after 7 days. User needs to log in again.

### "Email not verified"

User must verify email before logging in. Check console for verification code (if using stub email service).

## Architecture Notes

### Why Supabase Auth?

- Built-in JWT handling
- Email confirmation workflows
- Password hashing (bcrypt)
- Session management
- Admin API for user management

### Why HttpOnly Cookies?

- XSS protection (JavaScript can't access)
- Automatic inclusion in requests
- More secure than localStorage

### Why Async Validation?

- Don't block user during key save
- Test multiple providers in parallel
- Update validation status asynchronously

### Why Encryption Key in Vault?

- Separate from application secrets
- Centralized key management
- Easier rotation (invalidate all keys, users re-enter)

## Next Steps

1. Run database migration
2. Update main.py to include new routers
3. Test registration flow
4. Create first admin user
5. Test admin dashboard
6. Update upload/jobs/chat routers (Phase 3)
7. Implement frontend (Phase 4)
8. Configure real email service
9. Deploy to Cloud Run

## Support

For issues or questions:
1. Check Supabase logs for database errors
2. Check backend console for "[Auth]", "[Keys]", "[Admin]" logs
3. Verify encryption key exists in Vault
4. Verify RLS policies are enabled
5. Check that SUPABASE_SERVICE_KEY is service role (not anon)
