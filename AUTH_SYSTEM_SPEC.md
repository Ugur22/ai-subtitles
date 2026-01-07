# User Authentication & API Key Management System

## Overview

Replace the current shared password gate with a full user authentication system where users bring their own LLM API keys. This protects the API from abuse and offloads LLM costs to users.

---

## Decision Summary

| Decision | Choice |
|----------|--------|
| Key failure behavior | Hard fail (no fallback to server keys) |
| Default chat access | Keys required (chat disabled without keys) |
| Existing data | Clean slate (orphaned, new users start fresh) |
| Password gate | Remove entirely |
| Registration | Email + invite code (UUID, single-use) |
| Key validation | Async (save immediately, validate in background) |
| Model selection | Provider only (system picks model) |
| Encryption key rotation | Force re-entry |
| Invite management | Admin dashboard |
| Session duration | 7 days, no refresh |
| Account deletion | Hard delete (GDPR compliant) |
| Token verification | Cache 5 minutes |
| Auth UI | Full page (/login, /register routes) |
| Settings location | Gear icon in header |
| Admin access | Separate /admin route |
| Validation feedback | Inline status + toast |
| Key display | Last 4 chars visible (••••abc123) |
| Upload limits | 50/day, 4GB max file size |
| LLM providers | Groq + xAI + OpenAI + Anthropic |
| Provider selection | Dropdown + default in settings |
| Duplicate email | Generic error (privacy) |
| Admin key access | See status only (not values) |
| No keys state | Show chat disabled with message |
| Usage tracking | Basic counts (logins, uploads, messages) |
| Session expiry jobs | Jobs continue running |
| Password reset | Email 6-digit code |
| Encryption key storage | Supabase Vault |
| Auth persistence | HttpOnly cookie |
| Email verification | Required before first login |
| Invite code format | UUID, single-use |

---

## Database Schema

### New Tables

```sql
-- User profiles (extends Supabase auth.users)
CREATE TABLE user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  display_name TEXT,
  default_llm_provider TEXT DEFAULT 'groq',
  email_verified BOOLEAN DEFAULT FALSE,
  is_admin BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User API keys (encrypted)
CREATE TABLE user_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  provider TEXT NOT NULL, -- 'groq', 'xai', 'openai', 'anthropic'
  encrypted_key TEXT NOT NULL, -- AES-256-GCM encrypted
  key_suffix TEXT NOT NULL, -- Last 4 chars for display
  is_valid BOOLEAN DEFAULT NULL, -- NULL=pending, TRUE=valid, FALSE=invalid
  validation_error TEXT,
  validated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, provider)
);

-- Invite codes
CREATE TABLE invite_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  created_by UUID REFERENCES user_profiles(id),
  used_by UUID REFERENCES user_profiles(id),
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Usage tracking
CREATE TABLE usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  action TEXT NOT NULL, -- 'login', 'upload', 'chat_message'
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Rate limiting
CREATE TABLE rate_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  limit_type TEXT NOT NULL, -- 'upload_daily'
  count INTEGER DEFAULT 0,
  window_start TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, limit_type)
);

-- Email verification codes
CREATE TABLE email_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code TEXT NOT NULL, -- 6-digit code
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Password reset codes
CREATE TABLE password_resets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  code TEXT NOT NULL, -- 6-digit code
  expires_at TIMESTAMPTZ NOT NULL,
  used BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Modify Existing Tables

```sql
-- Add user_id to jobs table
ALTER TABLE jobs ADD COLUMN user_id UUID REFERENCES user_profiles(id);
CREATE INDEX idx_jobs_user_id ON jobs(user_id);
```

### Row Level Security

```sql
-- user_profiles: users see only their own
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_profiles_own ON user_profiles
  FOR ALL USING (auth.uid() = id);

-- user_api_keys: users see only their own
ALTER TABLE user_api_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_api_keys_own ON user_api_keys
  FOR ALL USING (auth.uid() = user_id);

-- jobs: users see only their own
CREATE POLICY jobs_own ON jobs
  FOR ALL USING (auth.uid() = user_id);
```

---

## Backend API Changes

### New Auth Endpoints

```
POST /api/auth/register
  Body: { email, password, invite_code }
  Response: { user_id, message: "Verification email sent" }

POST /api/auth/verify-email
  Body: { user_id, code }
  Response: { success, access_token } (sets HttpOnly cookie)

POST /api/auth/login
  Body: { email, password }
  Response: { success } (sets HttpOnly cookie)
  Error: { error: "Invalid credentials" } (generic)

POST /api/auth/logout
  Response: { success } (clears cookie)

POST /api/auth/forgot-password
  Body: { email }
  Response: { message: "If email exists, code sent" }

POST /api/auth/reset-password
  Body: { email, code, new_password }
  Response: { success }

GET /api/auth/me
  Response: { user_id, email, display_name, default_provider, is_admin }
```

### New API Key Endpoints

```
GET /api/keys
  Response: [{ provider, key_suffix, is_valid, validation_error, validated_at }]

POST /api/keys
  Body: { provider, api_key }
  Response: { id, provider, key_suffix, is_valid: null }
  (Triggers async validation)

DELETE /api/keys/:provider
  Response: { success }

POST /api/keys/:provider/test
  Response: { valid, error? }
  (Immediate sync test)
```

### New Admin Endpoints

```
GET /api/admin/users
  Response: [{ id, email, created_at, last_login, upload_count, has_groq, has_xai, has_openai, has_anthropic }]

POST /api/admin/invite-codes
  Response: { code }

GET /api/admin/invite-codes
  Response: [{ code, created_at, used_by, used_at }]

DELETE /api/admin/invite-codes/:code
  Response: { success }

DELETE /api/admin/users/:id
  Response: { success }

POST /api/admin/users/:id/invalidate-keys
  Response: { success }
  (Force user to re-enter keys)

GET /api/admin/stats
  Response: { total_users, active_today, uploads_today, chat_messages_today }
```

### New Settings Endpoints

```
PATCH /api/settings
  Body: { display_name?, default_llm_provider? }
  Response: { success }

DELETE /api/account
  Response: { success }
  (Hard delete - removes all user data)
```

### Auth Middleware

```python
# backend/middleware/auth.py
from functools import wraps
from fastapi import Request, HTTPException
import jwt
from datetime import datetime, timedelta

# Cache for token verification (5 min TTL)
token_cache = {}

def require_auth(f):
    @wraps(f)
    async def wrapper(request: Request, *args, **kwargs):
        token = request.cookies.get("auth_token")
        if not token:
            raise HTTPException(401, "Authentication required")

        # Check cache first
        cached = token_cache.get(token)
        if cached and cached["expires"] > datetime.now():
            request.state.user = cached["user"]
            return await f(request, *args, **kwargs)

        # Verify with Supabase
        user = await verify_supabase_token(token)
        if not user:
            raise HTTPException(401, "Invalid token")

        # Check email verification
        profile = await get_user_profile(user["id"])
        if not profile.email_verified:
            raise HTTPException(403, "Email not verified")

        # Cache result
        token_cache[token] = {
            "user": user,
            "expires": datetime.now() + timedelta(minutes=5)
        }

        request.state.user = user
        return await f(request, *args, **kwargs)
    return wrapper

def require_admin(f):
    @wraps(f)
    @require_auth
    async def wrapper(request: Request, *args, **kwargs):
        profile = await get_user_profile(request.state.user["id"])
        if not profile.is_admin:
            raise HTTPException(403, "Admin access required")
        return await f(request, *args, **kwargs)
    return wrapper
```

### Rate Limiting

```python
# backend/middleware/rate_limit.py
async def check_upload_limit(user_id: str) -> bool:
    """Check if user has uploads remaining today (50/day limit)"""
    today = datetime.now().replace(hour=0, minute=0, second=0)

    rate_limit = await supabase.table("rate_limits").select("*").eq(
        "user_id", user_id
    ).eq("limit_type", "upload_daily").single()

    if rate_limit and rate_limit["window_start"].date() == today.date():
        if rate_limit["count"] >= 50:
            return False
        await increment_rate_limit(user_id, "upload_daily")
    else:
        await reset_rate_limit(user_id, "upload_daily")

    return True

# Apply to upload endpoint
@router.post("/api/upload/signed-url")
@require_auth
async def get_signed_url(request: Request, file_info: FileInfo):
    if file_info.size > 4 * 1024 * 1024 * 1024:  # 4GB
        raise HTTPException(400, "File too large (max 4GB)")

    if not await check_upload_limit(request.state.user["id"]):
        raise HTTPException(429, "Daily upload limit reached (50/day)")

    # ... rest of handler
```

### API Key Encryption

```python
# backend/services/encryption.py
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

async def get_encryption_key():
    """Get encryption key from Supabase Vault"""
    result = await supabase.rpc("vault.read_secret", {"secret_name": "api_key_encryption"})
    return bytes.fromhex(result["secret"])

def encrypt_api_key(key: str, encryption_key: bytes) -> str:
    """Encrypt API key with AES-256-GCM"""
    aesgcm = AESGCM(encryption_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, key.encode(), None)
    return (nonce + ciphertext).hex()

def decrypt_api_key(encrypted: str, encryption_key: bytes) -> str:
    """Decrypt API key"""
    data = bytes.fromhex(encrypted)
    nonce, ciphertext = data[:12], data[12:]
    aesgcm = AESGCM(encryption_key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
```

### Async Key Validation

```python
# backend/services/key_validator.py
import asyncio
import httpx
from datetime import datetime

async def validate_api_key_async(user_id: str, provider: str, encrypted_key: str):
    """Validate API key in background"""
    try:
        encryption_key = await get_encryption_key()
        api_key = decrypt_api_key(encrypted_key, encryption_key)

        # Test the key with a minimal API call
        is_valid, error = await test_provider_key(provider, api_key)

        # Update database
        await supabase.table("user_api_keys").update({
            "is_valid": is_valid,
            "validation_error": error,
            "validated_at": datetime.now().isoformat()
        }).eq("user_id", user_id).eq("provider", provider)

    except Exception as e:
        await supabase.table("user_api_keys").update({
            "is_valid": False,
            "validation_error": str(e),
            "validated_at": datetime.now().isoformat()
        }).eq("user_id", user_id).eq("provider", provider)

async def test_provider_key(provider: str, api_key: str) -> tuple[bool, str | None]:
    """Test if API key is valid"""
    try:
        if provider == "groq":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return True, None
                return False, f"API returned {resp.status_code}"

        elif provider == "xai":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return True, None
                return False, f"API returned {resp.status_code}"

        elif provider == "openai":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return True, None
                return False, f"API returned {resp.status_code}"

        elif provider == "anthropic":
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}]
                    }
                )
                if resp.status_code in [200, 400]:  # 400 means key is valid but request issue
                    return True, None
                return False, f"API returned {resp.status_code}"

    except Exception as e:
        return False, str(e)
```

---

## Frontend Changes

### New Routes

```
/login          - Full page login form
/register       - Full page registration with invite code
/verify-email   - Email verification code entry
/forgot-password - Request reset code
/reset-password - Enter code + new password
/admin          - Admin dashboard (admin users only)
```

### New Components

```
src/
  components/
    auth/
      LoginPage.tsx           # Full page login
      RegisterPage.tsx        # Registration with invite code
      VerifyEmailPage.tsx     # 6-digit code entry
      ForgotPasswordPage.tsx
      ResetPasswordPage.tsx
      ProtectedRoute.tsx      # Wrapper for auth-required routes

    settings/
      SettingsPanel.tsx       # Main settings container
      APIKeysTab.tsx          # API key management
      ProfileTab.tsx          # Display name, email
      AccountTab.tsx          # Delete account
      ProviderCard.tsx        # Individual provider key card
      KeyStatusIndicator.tsx  # Valid/invalid/pending indicator

    admin/
      AdminDashboard.tsx      # Main admin view
      UsersList.tsx           # User management table
      InviteCodesList.tsx     # Invite code management
      StatsCards.tsx          # Usage statistics

    chat/
      ChatProviderSelector.tsx  # Dropdown to select LLM provider
      NoKeysWarning.tsx         # "Configure API key" message

    layout/
      Header.tsx              # Update with settings icon + user menu
      SettingsIcon.tsx        # Gear icon that opens settings

  hooks/
    useAuth.ts                # Rewrite for Supabase Auth + cookies
    useAPIKeys.ts             # Manage user API keys
    useSettings.ts            # User settings state
    useAdmin.ts               # Admin operations

  services/
    auth.ts                   # Auth API calls
    keys.ts                   # API key management
    admin.ts                  # Admin API calls
```

### Auth Flow

```tsx
// src/App.tsx
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify-email" element={<VerifyEmailPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />

            {/* Protected routes */}
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<MainApp />} />
              <Route path="/admin" element={<AdminRoute><AdminDashboard /></AdminRoute>} />
            </Route>
          </Routes>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

// src/components/auth/ProtectedRoute.tsx
function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return <LoadingSpinner />;
  if (!isAuthenticated) return <Navigate to="/login" />;

  return <Outlet />;
}
```

### Settings Panel

```tsx
// src/components/settings/SettingsPanel.tsx
function SettingsPanel({ isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('api-keys');

  return (
    <SlideOverPanel isOpen={isOpen} onClose={onClose}>
      <div className="flex border-b">
        <TabButton active={activeTab === 'api-keys'} onClick={() => setActiveTab('api-keys')}>
          API Keys
        </TabButton>
        <TabButton active={activeTab === 'profile'} onClick={() => setActiveTab('profile')}>
          Profile
        </TabButton>
        <TabButton active={activeTab === 'account'} onClick={() => setActiveTab('account')}>
          Account
        </TabButton>
      </div>

      {activeTab === 'api-keys' && <APIKeysTab />}
      {activeTab === 'profile' && <ProfileTab />}
      {activeTab === 'account' && <AccountTab />}
    </SlideOverPanel>
  );
}
```

### API Keys Tab

```tsx
// src/components/settings/APIKeysTab.tsx
function APIKeysTab() {
  const { keys, addKey, deleteKey, isLoading } = useAPIKeys();

  const providers = [
    { id: 'groq', name: 'Groq', placeholder: 'gsk_...' },
    { id: 'xai', name: 'xAI (Grok)', placeholder: 'xai-...' },
    { id: 'openai', name: 'OpenAI', placeholder: 'sk-...' },
    { id: 'anthropic', name: 'Anthropic', placeholder: 'sk-ant-...' },
  ];

  return (
    <div className="space-y-4 p-4">
      <p className="text-sm text-gray-600">
        Add your API keys to enable chat features. Keys are encrypted and stored securely.
      </p>

      {providers.map(provider => (
        <ProviderCard
          key={provider.id}
          provider={provider}
          savedKey={keys.find(k => k.provider === provider.id)}
          onSave={(key) => addKey(provider.id, key)}
          onDelete={() => deleteKey(provider.id)}
        />
      ))}
    </div>
  );
}
```

### Provider Card

```tsx
// src/components/settings/ProviderCard.tsx
function ProviderCard({ provider, savedKey, onSave, onDelete }) {
  const [inputValue, setInputValue] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    await onSave(inputValue);
    setInputValue('');
    setIsSaving(false);
    toast.success(`${provider.name} key saved. Validating...`);
  };

  return (
    <div className="border rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">{provider.name}</h3>
        <KeyStatusIndicator status={savedKey?.is_valid} />
      </div>

      {savedKey ? (
        <div className="flex items-center justify-between">
          <code className="text-sm bg-gray-100 px-2 py-1 rounded">
            ••••••••{savedKey.key_suffix}
          </code>
          <button onClick={onDelete} className="text-red-600 text-sm">
            Remove
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type="password"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={provider.placeholder}
            className="flex-1 border rounded px-3 py-2"
          />
          <button
            onClick={handleSave}
            disabled={!inputValue || isSaving}
            className="bg-blue-600 text-white px-4 py-2 rounded"
          >
            Save
          </button>
        </div>
      )}

      {savedKey?.validation_error && (
        <p className="text-red-600 text-sm mt-2">{savedKey.validation_error}</p>
      )}
    </div>
  );
}
```

### Chat Provider Selection

```tsx
// src/components/chat/ChatProviderSelector.tsx
function ChatProviderSelector({ value, onChange, disabled }) {
  const { keys } = useAPIKeys();
  const { settings } = useSettings();

  const availableProviders = keys
    .filter(k => k.is_valid)
    .map(k => k.provider);

  if (availableProviders.length === 0) {
    return <NoKeysWarning />;
  }

  return (
    <select
      value={value || settings.default_llm_provider}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="border rounded px-2 py-1"
    >
      {availableProviders.map(provider => (
        <option key={provider} value={provider}>
          {providerNames[provider]}
        </option>
      ))}
    </select>
  );
}
```

### No Keys Warning

```tsx
// src/components/chat/NoKeysWarning.tsx
function NoKeysWarning() {
  const { openSettings } = useSettings();

  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
      <p className="text-yellow-800 mb-2">
        Chat is disabled. Add an API key to enable chat features.
      </p>
      <button
        onClick={() => openSettings('api-keys')}
        className="text-yellow-800 underline"
      >
        Configure API Keys
      </button>
    </div>
  );
}
```

---

## Files to Modify

### Backend

| File | Changes |
|------|---------|
| `backend/main.py` | Add auth middleware, new routers |
| `backend/config.py` | Remove APP_PASSWORD_HASH, add SUPABASE_VAULT config |
| `backend/routers/auth.py` | Complete rewrite for Supabase Auth |
| `backend/routers/chat.py` | Use user's API keys, add provider selection |
| `backend/routers/jobs.py` | Add user_id to jobs, update queries |
| `backend/routers/upload.py` | Add auth + rate limiting |
| `backend/sql/supabase_schema.sql` | Add new tables |
| **New** `backend/routers/admin.py` | Admin endpoints |
| **New** `backend/routers/keys.py` | API key management |
| **New** `backend/routers/settings.py` | User settings |
| **New** `backend/middleware/auth.py` | Auth decorators |
| **New** `backend/middleware/rate_limit.py` | Rate limiting |
| **New** `backend/services/encryption.py` | Key encryption |
| **New** `backend/services/key_validator.py` | Async validation |
| **New** `backend/services/email.py` | Email sending |

### Frontend

| File | Changes |
|------|---------|
| `frontend/src/App.tsx` | Add routing, AuthProvider |
| `frontend/src/services/api.ts` | Update for cookie-based auth |
| `frontend/src/hooks/useAuth.ts` | Rewrite for Supabase Auth |
| **Delete** `frontend/src/components/auth/PasswordGate.tsx` | Remove entirely |
| **New** `frontend/src/components/auth/LoginPage.tsx` | |
| **New** `frontend/src/components/auth/RegisterPage.tsx` | |
| **New** `frontend/src/components/auth/VerifyEmailPage.tsx` | |
| **New** `frontend/src/components/auth/ForgotPasswordPage.tsx` | |
| **New** `frontend/src/components/auth/ResetPasswordPage.tsx` | |
| **New** `frontend/src/components/auth/ProtectedRoute.tsx` | |
| **New** `frontend/src/components/settings/SettingsPanel.tsx` | |
| **New** `frontend/src/components/settings/APIKeysTab.tsx` | |
| **New** `frontend/src/components/settings/ProviderCard.tsx` | |
| **New** `frontend/src/components/admin/AdminDashboard.tsx` | |
| **New** `frontend/src/hooks/useAPIKeys.ts` | |
| **New** `frontend/src/hooks/useSettings.ts` | |
| **New** `frontend/src/hooks/useAdmin.ts` | |

---

## Environment & Secrets

### Supabase Vault Setup

```sql
-- Create encryption key in Supabase Vault
SELECT vault.create_secret(
  'api_key_encryption',
  encode(gen_random_bytes(32), 'hex')
);
```

### Remove from Secrets

- `app-password-hash` - no longer needed

### New Environment Variables

```
# Email provider for verification/reset
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=<sendgrid-api-key>
SMTP_FROM=noreply@yourdomain.com
```

---

## Implementation Phases

### Phase 1: Database & Backend Auth Foundation
1. Create new database tables and RLS policies
2. Set up Supabase Vault encryption key
3. Implement auth middleware with caching
4. Create auth endpoints (register, login, verify, reset)
5. Add user_id column to jobs table

### Phase 2: API Key Management
1. Implement encryption service
2. Create API key endpoints
3. Implement async validation worker
4. Update chat router to use user keys

### Phase 3: Frontend Auth
1. Set up React Router
2. Create login/register pages
3. Implement ProtectedRoute
4. Update API service for cookies
5. Delete PasswordGate component

### Phase 4: Settings & Admin
1. Create settings panel UI
2. Implement API keys management UI
3. Create admin dashboard
4. Implement invite code management

### Phase 5: Rate Limiting & Polish
1. Implement upload rate limiting (50/day, 4GB)
2. Add usage tracking
3. Implement account deletion
4. Testing and bug fixes

---

## Security Checklist

- [ ] API keys encrypted with AES-256-GCM at rest
- [ ] Encryption key stored in Supabase Vault
- [ ] HttpOnly cookies for session tokens
- [ ] Token verification cached for 5 minutes max
- [ ] Generic error messages for auth (no enumeration)
- [ ] Email verification required before access
- [ ] Invite codes are UUIDs (unguessable)
- [ ] Rate limiting on uploads (50/day)
- [ ] File size limit (4GB)
- [ ] RLS policies on all user tables
- [ ] Hard delete for GDPR compliance
- [ ] Admin cannot see actual API key values
