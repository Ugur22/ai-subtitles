# AI-Subs Frontend Production Deployment Guide

This guide explains how the frontend has been configured for production deployment and how to use it.

## Changes Made

### 1. Configuration File
**File:** `/frontend/src/config.ts`
```typescript
export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
```
- Centralized API URL configuration
- Uses environment variable `VITE_API_URL` for production
- Falls back to `http://localhost:8000` for local development

### 2. Updated Components
All hardcoded `http://localhost:8000` URLs have been replaced with `API_BASE_URL` in:

- ✅ `frontend/src/components/features/transcription/TranscriptionUpload.tsx`
- ✅ `frontend/src/components/features/transcription/TranscriptSegmentList.tsx`
- ✅ `frontend/src/components/features/transcription/SavedTranscriptionsPanel.tsx`
- ✅ `frontend/src/components/features/chat/ChatPanel.tsx`
- ✅ `frontend/src/components/features/chat/ChatMessage.tsx`
- ✅ `frontend/src/components/features/speakers/EnrolledSpeakersPanel.tsx`
- ✅ `frontend/src/components/features/summary/SummaryPanel.tsx`

### 3. Environment Configuration
**File:** `/frontend/.env.example`
```env
VITE_API_URL=http://localhost:8000
```
- Template for environment variables
- Copy to `.env` for local development
- Provides documentation for required variables

### 4. Docker Configuration
**File:** `/frontend/Dockerfile`
- Multi-stage build for optimal image size
- Build stage: Node.js 20 Alpine
- Production stage: Nginx Alpine
- Accepts `VITE_API_URL` as build argument
- Serves static files efficiently

### 5. Nginx Configuration
**File:** `/frontend/nginx.conf`
- Client-side routing support (SPA)
- Static asset caching (1 year)
- No caching for index.html
- Security headers
- Gzip compression

## Deployment Options

### Option 1: Docker Build (Recommended)

#### Build for Production
```bash
cd frontend

# Build with production API URL
docker build \
  --build-arg VITE_API_URL=https://api.yourdomain.com \
  -t ai-subs-frontend:latest \
  .
```

#### Run Container
```bash
docker run -d \
  -p 80:80 \
  --name ai-subs-frontend \
  ai-subs-frontend:latest
```

### Option 2: Docker Compose

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  frontend:
    build:
      context: ./frontend
      args:
        VITE_API_URL: https://api.yourdomain.com
    ports:
      - "80:80"
    restart: unless-stopped

  # Add your backend service here if needed
```

Run:
```bash
docker-compose up -d
```

### Option 3: Manual Build and Deploy

#### 1. Set Environment Variable
```bash
cd frontend
export VITE_API_URL=https://api.yourdomain.com
```

Or create `.env` file:
```bash
cp .env.example .env
# Edit .env and set VITE_API_URL
```

#### 2. Build
```bash
npm install
npm run build
```

#### 3. Deploy
The `dist` folder contains your production build. Deploy it to:
- **Nginx:** Copy to `/var/www/html` and use the provided `nginx.conf`
- **Apache:** Copy to document root with appropriate `.htaccess`
- **Static Hosting:** Upload to Netlify, Vercel, or AWS S3

## Environment-Specific Deployments

### Development
```bash
# Uses default localhost:8000
npm run dev
```

### Staging
```bash
# Create .env.staging
echo "VITE_API_URL=https://staging-api.yourdomain.com" > .env.staging

# Build with staging config
npm run build -- --mode staging
```

### Production
```bash
# Create .env.production
echo "VITE_API_URL=https://api.yourdomain.com" > .env.production

# Build
npm run build
```

## Docker Build Examples

### Example 1: Local Network
```bash
docker build \
  --build-arg VITE_API_URL=http://192.168.1.100:8000 \
  -t ai-subs-frontend:local \
  .
```

### Example 2: Cloud Deployment
```bash
docker build \
  --build-arg VITE_API_URL=https://api.ai-subs.com \
  -t ghcr.io/username/ai-subs-frontend:v1.0.0 \
  .

docker push ghcr.io/username/ai-subs-frontend:v1.0.0
```

### Example 3: Behind Reverse Proxy
```bash
# API is on same domain at /api path
docker build \
  --build-arg VITE_API_URL=/api \
  -t ai-subs-frontend:proxy \
  .
```

## Nginx Reverse Proxy Setup

If you want to serve both frontend and backend from the same domain:

```nginx
# /etc/nginx/sites-available/ai-subs

server {
    listen 80;
    server_name yourdomain.com;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support (if needed)
    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Verification

After deployment, verify:

1. **API Connection:**
   - Open browser DevTools → Network tab
   - Check that API requests go to the correct URL

2. **Video Playback:**
   - Upload and transcribe a video
   - Verify video loads from correct URL

3. **Image Loading:**
   - Check thumbnails and screenshots load correctly

4. **Console Errors:**
   - Look for any CORS or mixed content errors

## Troubleshooting

### Issue: CORS Errors
**Solution:** Configure your backend to allow requests from your frontend domain:
```python
# FastAPI example
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Issue: Images/Videos Not Loading
**Cause:** Relative URLs not resolving correctly
**Solution:** Ensure backend serves media files with absolute URLs or proper base paths

### Issue: 404 on Page Refresh
**Cause:** SPA routing not configured
**Solution:** Use the provided `nginx.conf` which has `try_files $uri $uri/ /index.html;`

### Issue: Mixed Content (HTTPS/HTTP)
**Solution:** Ensure API URL uses HTTPS if frontend is on HTTPS:
```bash
docker build --build-arg VITE_API_URL=https://api.yourdomain.com -t frontend .
```

## Security Considerations

1. **HTTPS:** Always use HTTPS in production
2. **CORS:** Restrict allowed origins on backend
3. **Environment Variables:** Never commit `.env` files
4. **Build Args:** Don't include secrets in Docker build args
5. **Headers:** The nginx.conf includes security headers

## Monitoring

Add health check endpoint to nginx:
```nginx
location /health {
    access_log off;
    return 200 "healthy\n";
    add_header Content-Type text/plain;
}
```

## Scaling

For high-traffic deployments:
1. Use CDN for static assets
2. Enable gzip/brotli compression (already in nginx.conf)
3. Use multiple nginx instances behind load balancer
4. Cache API responses where appropriate

## Rollback

Keep previous Docker images:
```bash
# Tag before deploying new version
docker tag ai-subs-frontend:latest ai-subs-frontend:backup

# Rollback if needed
docker stop ai-subs-frontend
docker rm ai-subs-frontend
docker run -d -p 80:80 --name ai-subs-frontend ai-subs-frontend:backup
```

## Additional Resources

- [Vite Environment Variables](https://vitejs.dev/guide/env-and-mode.html)
- [Docker Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/)
- [Nginx SPA Configuration](https://nginx.org/en/docs/)
