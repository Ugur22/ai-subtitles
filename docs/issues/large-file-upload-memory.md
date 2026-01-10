# Issue: Browser Memory Exhaustion on Large File Uploads (>2GB)

## Problem Summary

When uploading files larger than ~2.3GB, the browser runs out of memory and crashes. Files around 1.8GB work fine. The UI advertises support for up to 10GB files, but browser memory limits prevent this.

## Root Cause

The file hashing function loads the **entire file into memory** before hashing. Combined with the XHR upload buffer and the original file object, this creates multiple copies of the file in browser memory.

## Memory Usage Breakdown

| Step | Memory Added | Code Location |
|------|--------------|---------------|
| File object (selection) | +2.37GB | `useFileUpload.ts:30-31` |
| Blob URL | minimal | `URL.createObjectURL(file)` |
| **File hashing (Uint8Array)** | **+2.37GB** | `frontend/src/utils/file.ts:37` |
| XHR upload buffer | +2.37GB | `gcsUpload.ts:146, 230` |
| **Peak Total** | **~7GB+** | Exceeds browser limit |

### Why 1.8GB Works, 2.37GB Doesn't

- **Typical browser memory limit**: 2-3GB per tab (depends on system RAM)
- **1.8GB file**: Peak ~3.6GB → Just barely fits
- **2.37GB file**: Peak ~7GB+ → Crashes browser

## Affected Files

| File | Lines | Issue |
|------|-------|-------|
| `frontend/src/utils/file.ts` | 14-50 | `generateFileHash()` loads entire file into memory |
| `frontend/src/utils/file.ts` | 37 | `new Uint8Array(totalSize)` - creates full copy |
| `frontend/src/services/gcsUpload.ts` | 146 | `xhr.send(file)` - simple upload |
| `frontend/src/services/gcsUpload.ts` | 230 | `xhr.send(file)` - resumable upload |
| `frontend/src/services/api.ts` | 664 | Calls `generateFileHash()` |
| `frontend/src/services/api.ts` | 675 | Calls `uploadToGCS()` |

## Current Code - The Problem

### File Hashing (frontend/src/utils/file.ts:14-50)

```typescript
export async function generateFileHash(file: File): Promise<string> {
  const CHUNK_SIZE = 8 * 1024 * 1024; // 8MB chunks for reading
  const totalSize = file.size;
  const chunks: Uint8Array[] = [];

  // Read file in chunks
  for (let offset = 0; offset < totalSize; offset += CHUNK_SIZE) {
    const chunk = file.slice(offset, offset + CHUNK_SIZE);
    const buffer = await chunk.arrayBuffer();
    chunks.push(new Uint8Array(buffer));
  }

  // PROBLEM: Combines ALL chunks into a single array (entire file in memory)
  const combined = new Uint8Array(totalSize);  // <-- FULL FILE COPY
  let position = 0;
  for (const chunk of chunks) {
    combined.set(chunk, position);
    position += chunk.length;
  }

  // Hash the combined array
  const hashBuffer = await crypto.subtle.digest('SHA-256', combined);
  // ...
}
```

## Proposed Fix: Streaming Hash Calculation

### Option 1: Use Incremental Hashing with SubtleCrypto (Not Supported)

Unfortunately, the Web Crypto API (`crypto.subtle.digest`) does not support incremental/streaming hashing. It requires the entire data at once.

### Option 2: Use a JavaScript Hashing Library (Recommended)

Use a library like `hash-wasm` or `js-sha256` that supports incremental hashing:

```typescript
import { createSHA256 } from 'hash-wasm';

export async function generateFileHash(file: File): Promise<string> {
  const CHUNK_SIZE = 8 * 1024 * 1024; // 8MB chunks
  const hasher = await createSHA256();
  hasher.init();

  for (let offset = 0; offset < file.size; offset += CHUNK_SIZE) {
    const chunk = file.slice(offset, offset + CHUNK_SIZE);
    const buffer = await chunk.arrayBuffer();
    hasher.update(new Uint8Array(buffer));
    // Chunk is garbage collected after this iteration
  }

  return hasher.digest('hex');
}
```

### Option 3: Sample-Based Hashing (Faster, Less Accurate)

For very large files, hash only a sample (first chunk + last chunk + file size):

```typescript
export async function generateFileHash(file: File): Promise<string> {
  const SAMPLE_SIZE = 8 * 1024 * 1024; // 8MB

  // Read first 8MB
  const firstChunk = await file.slice(0, SAMPLE_SIZE).arrayBuffer();

  // Read last 8MB
  const lastStart = Math.max(0, file.size - SAMPLE_SIZE);
  const lastChunk = await file.slice(lastStart, file.size).arrayBuffer();

  // Combine: first chunk + last chunk + file size string
  const sizeBytes = new TextEncoder().encode(file.size.toString());
  const combined = new Uint8Array(
    firstChunk.byteLength + lastChunk.byteLength + sizeBytes.length
  );
  combined.set(new Uint8Array(firstChunk), 0);
  combined.set(new Uint8Array(lastChunk), firstChunk.byteLength);
  combined.set(sizeBytes, firstChunk.byteLength + lastChunk.byteLength);

  const hashBuffer = await crypto.subtle.digest('SHA-256', combined);
  return Array.from(new Uint8Array(hashBuffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}
```

**Pros**: Fast, uses only ~16MB memory regardless of file size
**Cons**: Two files with same start/end/size but different middle will have same hash (unlikely but possible)

### Option 4: Skip Hashing for Very Large Files

For files over a threshold (e.g., 1GB), use a UUID instead of a content hash:

```typescript
export async function generateFileHash(file: File): Promise<string> {
  const ONE_GB = 1024 * 1024 * 1024;

  if (file.size > ONE_GB) {
    // Use UUID + file metadata instead of content hash
    return `${crypto.randomUUID()}-${file.size}-${file.lastModified}`;
  }

  // Original hashing logic for smaller files
  // ...
}
```

## Recommended Implementation

**Use Option 2 (hash-wasm)** for best balance of accuracy and memory efficiency:

1. Install dependency: `npm install hash-wasm`
2. Replace `generateFileHash()` with streaming implementation
3. Memory usage becomes constant (~8MB) regardless of file size

## Configured Limits (Not the Issue)

These are correctly configured but browser memory is the bottleneck:

| Setting | Value | Location |
|---------|-------|----------|
| Backend MAX_UPLOAD_SIZE | 10GB | `backend/config.py:45` |
| UI advertised limit | 10GB | `UploadZone.tsx:172` |
| GCS signed URL limit | 10GB | `backend/routers/upload.py:191` |
| Cloud Run direct upload | 32MB | Hard limit (bypassed via GCS) |

## Testing Checklist

- [ ] Upload a 500MB file → should work
- [ ] Upload a 1.5GB file → should work
- [ ] Upload a 2.5GB file → should work (after fix)
- [ ] Upload a 5GB file → should work (after fix)
- [ ] Monitor browser memory during upload
- [ ] Verify file hash is correct (compare with CLI tool)

## Priority

**Medium** - Affects users with very large files. Workaround: use smaller files or compress before upload.

## Dependencies to Add

```json
{
  "dependencies": {
    "hash-wasm": "^4.11.0"
  }
}
```
