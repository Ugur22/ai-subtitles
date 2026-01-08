# Frontend Architecture

## 1. Technology Stack

- **React** (with TypeScript)
- **Vite** for build tooling
- **TailwindCSS** for styling
- **React Query** for API state management
- **React Router** for routing
- **AWS S3 + CloudFront** for hosting

## 2. Project Structure

````bash
frontend/
├── src/
│   ├── components/
│   │   ├── common/
│   │   │   ├── Button.tsx
│   │   │   ├── Input.tsx
│   │   │   └── ProgressBar.tsx
│   │   ├── layout/
│   │   │   ├── Header.tsx
│   │   │   ├── Footer.tsx
│   │   │   └── Sidebar.tsx
│   │   └── features/
│   │       ├── auth/
│   │       ├── transcription/
│   │       └── dashboard/
│   ├── pages/
│   │   ├── HomePage.tsx
│   │   ├── DashboardPage.tsx
│   │   ├── TranscribePage.tsx
│   │   └── AccountPage.tsx
│   ├── hooks/
│   │   ├── useTranscription.ts
│   │   └── useAuth.ts
│   ├── services/
│   │   ├── api.ts
│   │   └── transcription.ts
│   └── utils/
└── public/

## 3. Key Features

### 3.1. User Dashboard
```tsx
// pages/DashboardPage.tsx
const DashboardPage = () => {
  const { transcriptions } = useTranscriptions();

  return (
    <div className="container mx-auto">
      <h1>Your Transcriptions</h1>
      <TranscriptionsList data={transcriptions} />
      <UsageStats />
      <SubscriptionDetails />
    </div>
  );
};
````

### 3.2. Transcription Upload

```tsx
// components/features/transcription/UploadForm.tsx
const UploadForm = () => {
  const { mutate, isLoading } = useTranscriptionMutation();

  return (
    <div className="upload-container">
      <FileDropzone
        onDrop={(files) => mutate(files[0])}
        accept=".mp4,.mp3,.wav"
      />
      {isLoading && <TranscriptionProgress />}
    </div>
  );
};
```

### 3.3. Real-time Progress

```tsx
// components/features/transcription/TranscriptionProgress.tsx
const TranscriptionProgress = () => {
  const { progress, status } = useTranscriptionProgress();

  return (
    <div className="progress-container">
      <ProgressBar value={progress} />
      <StatusIndicator status={status} />
      <TimeRemaining />
    </div>
  );
};
```

## 4. API Integration

```typescript
// services/api.ts
import axios from "axios";

const api = axios.create({
  baseURL: process.env.VITE_API_URL,
});

export const transcribeVideo = async (file: File) => {
  const formData = new FormData();
  formData.append("file", file);

  return api.post("/transcribe/", formData, {
    onUploadProgress: (progress) => {
      const percentage = (progress.loaded / progress.total) * 100;
      // Update upload progress
    },
  });
};
```

## 5. Deployment Steps

### 5.1. Build Setup

```bash
# Install dependencies
npm install

# Build for production
npm run build

# Preview production build
npm run preview
```

### 5.2. AWS S3 Static Hosting

```bash
# Create S3 bucket
aws s3 mb s3://your-app-frontend

# Configure for static website hosting
aws s3 website s3://your-app-frontend --index-document index.html

# Upload build files
aws s3 sync dist/ s3://your-app-frontend

# Make bucket public
aws s3api put-bucket-policy --bucket your-app-frontend --policy file://bucket-policy.json
```

### 5.3. CloudFront Distribution

```bash
# Create distribution
aws cloudfront create-distribution \
    --origin-domain-name your-app-frontend.s3.amazonaws.com \
    --default-root-object index.html
```

## 6. Environment Configuration

```env
# .env.production
VITE_API_URL=https://api.yourdomain.com
VITE_STRIPE_PUBLIC_KEY=pk_live_xxx
VITE_GA_TRACKING_ID=UA-XXXXX-Y
```

## 7. Development Guidelines

1. **Component Structure**

   - Use functional components with hooks
   - Implement proper TypeScript types
   - Follow atomic design principles

2. **State Management**

   - Use React Query for server state
   - Use Context for global app state
   - Keep component state local when possible

3. **Performance**

   - Implement code splitting
   - Use lazy loading for routes
   - Optimize images and assets
   - Cache API responses

4. **Testing**
   - Write unit tests with Vitest
   - Use React Testing Library
   - Implement E2E tests with Cypress

## 8. CI/CD Pipeline

```yaml
# .github/workflows/frontend.yml
name: Frontend CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install dependencies
        run: npm ci
      - name: Run tests
        run: npm test
      - name: Build
        run: npm run build
      - name: Deploy to S3
        run: aws s3 sync dist/ s3://your-app-frontend
      - name: Invalidate CloudFront
        run: aws cloudfront create-invalidation --distribution-id XXX --paths "/*"
```
