# Issue: 504 Gateway Timeout Causes Logout During Transcription

## Problem Summary

When a user refreshes the page during an active transcription job, they sometimes get logged out due to 504 gateway errors. Subsequent login attempts are also slow.

## Root Cause

The Supabase client has **no timeout configured** on its API calls. When the backend is under heavy load (GPU processing transcription), Supabase calls hang indefinitely until CloudRun's 300-second timeout triggers a 504.

## The Problem Chain

1. User starts transcription → GPU becomes busy
2. User refreshes page → Frontend calls `/api/auth/me` to verify session
3. Backend tries to verify with Supabase → **No timeout configured**
4. Supabase call hangs (backend under load) → Waits indefinitely
5. After 300 seconds → CloudRun timeout → **504 Gateway Timeout**
6. Frontend receives 504 → Clears user state → **User logged out**

## Affected Files

### Backend - No Timeouts on Supabase Calls

| File | Lines | Function | Issue |
|------|-------|----------|-------|
| `backend/middleware/auth.py` | 75-103 | `_verify_supabase_token()` | No timeout on `client.auth.get_user(token)` |
| `backend/middleware/auth.py` | 106-128 | `_get_user_profile()` | No timeout on Supabase query |
| `backend/routers/auth_new.py` | 615-640 | Login endpoint | No timeout on `sign_in_with_password()` |
| `backend/middleware/auth.py` | 18 | `_auth_executor` | Only 4 worker threads |

### Frontend - Clears User on Any Error

| File | Lines | Issue |
|------|-------|-------|
| `frontend/src/hooks/useAuth.tsx` | 36-40 | Any error sets `user` to `null` (causes logout) |
| `frontend/src/hooks/useAuth.tsx` | 45-47 | Calls `/api/auth/me` on every mount |
| `frontend/src/components/auth/ProtectedRoute.tsx` | 10 | No retry logic for failed auth |

## Code Examples

### Backend - Missing Timeout (auth.py:75-103)
```python
def _verify_supabase_token(token: str) -> Optional[Dict]:
    """This runs in executor but still calls Supabase blocking"""
    client = SupabaseService.get_client()
    response = client.auth.get_user(token)  # NO TIMEOUT - hangs indefinitely
    return response.user
```

### Frontend - Clears User on Error (useAuth.tsx:36-40)
```typescript
catch (err) {
  setUser(null);  // USER LOGGED OUT ON ANY ERROR (including 504)
}
```

## Proposed Fixes

### 1. Add Timeouts to Supabase Calls (Backend)

```python
import asyncio
from concurrent.futures import TimeoutError

SUPABASE_TIMEOUT = 10  # seconds

async def _verify_supabase_token_async(token: str) -> Optional[Dict]:
    try:
        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                _auth_executor, _verify_supabase_token, token
            ),
            timeout=SUPABASE_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning("Supabase token verification timed out")
        return None
```

### 2. Add Retry Logic for Auth Failures (Frontend)

```typescript
const fetchUser = async (retries = 3) => {
  for (let i = 0; i < retries; i++) {
    try {
      const userData = await authService.getCurrentUser();
      setUser(userData);
      return;
    } catch (err) {
      if (i === retries - 1) {
        // Only clear user after all retries fail
        // And only if it's an auth error, not a server error
        if (err.status === 401 || err.status === 403) {
          setUser(null);
        }
        // For 504/500, keep existing user state
      }
      await new Promise(r => setTimeout(r, 1000 * (i + 1))); // Exponential backoff
    }
  }
};
```

### 3. Distinguish Auth Errors from Server Errors (Frontend)

```typescript
catch (err) {
  const status = err?.response?.status || err?.status;

  // Only logout on actual auth failures
  if (status === 401 || status === 403) {
    setUser(null);
  }
  // For 5xx errors, keep user logged in (server issue, not auth issue)
  // User's session token is still valid
}
```

### 4. Increase Auth Executor Pool Size (Backend)

```python
# backend/middleware/auth.py line 18
_auth_executor = ThreadPoolExecutor(max_workers=8)  # Increase from 4 to 8
```

## Testing Checklist

- [ ] Start a transcription job
- [ ] Refresh page during transcription
- [ ] Verify user stays logged in (no 504 logout)
- [ ] If 504 occurs, verify retry logic kicks in
- [ ] Verify login speed is reasonable under load
- [ ] Test with slow network conditions

## Priority

**High** - This directly impacts user experience and causes data loss (user loses their place in the app).
