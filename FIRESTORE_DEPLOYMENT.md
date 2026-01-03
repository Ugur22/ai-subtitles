# Firestore Database Migration Guide

## Overview

The AI-Subs application now supports dual database backends:
- **SQLite** - For local development
- **Firestore** - For production deployment on Cloud Run

This guide covers the migration from SQLite to Firestore for production persistence.

## Architecture Changes

### Database Abstraction Layer

The new `database.py` implements:

1. **`DatabaseBackend`** - Abstract base class defining the interface
2. **`SQLiteBackend`** - Existing SQLite implementation (preserved)
3. **`FirestoreBackend`** - New Firestore implementation for Cloud Run
4. **`get_database_backend()`** - Factory function that returns the appropriate backend

### Backward Compatibility

All existing code continues to work without changes. The public API functions delegate to the selected backend:
- `init_db()`
- `store_transcription()`
- `get_transcription()`
- `list_transcriptions()`
- `delete_transcription()`
- `update_file_path()`

## Configuration

### Environment Variables

Add these to your environment:

```bash
# Database Configuration
DATABASE_TYPE=firestore              # "sqlite" or "firestore"
FIRESTORE_COLLECTION=transcriptions  # Firestore collection name

# For local SQLite (development only)
DATABASE_TYPE=sqlite
DATABASE_PATH=transcriptions.db
```

### Cloud Run Setup

#### 1. Enable Firestore API

```bash
gcloud services enable firestore.googleapis.com
```

#### 2. Create Firestore Database

In Google Cloud Console:
1. Navigate to Firestore
2. Create a new Native mode database
3. Select your region (should match Cloud Run region for best latency)

Or via CLI:

```bash
gcloud firestore databases create --region=us-central1
```

#### 3. Grant Firestore Permissions

The Cloud Run service account needs Firestore access:

```bash
# Get your Cloud Run service account
SERVICE_ACCOUNT=$(gcloud run services describe ai-subs-api \
  --region=us-central1 \
  --format='value(spec.template.spec.serviceAccountName)')

# Grant Firestore User role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/datastore.user"
```

#### 4. Update Cloud Run Environment Variables

```bash
gcloud run services update ai-subs-api \
  --region=us-central1 \
  --set-env-vars="DATABASE_TYPE=firestore,FIRESTORE_COLLECTION=transcriptions"
```

## Data Schema

### Firestore Document Structure

Each transcription is stored as a document with the video hash as the document ID:

```javascript
{
  video_hash: "abc123def456",
  filename: "video.mp4",
  file_path: "gs://bucket/path/to/video.mp4",  // GCS path
  transcription_data: {
    transcription: {
      segments: [
        {
          start: 0.0,
          end: 5.0,
          text: "Hello world",
          speaker: "SPEAKER_01",
          screenshot_url: "https://storage.googleapis.com/..."
        }
        // ... more segments
      ]
    }
    // ... other transcription metadata
  },
  created_at: Timestamp(2025-01-02T10:30:00Z)
}
```

### Indexes

Firestore automatically creates indexes for:
- Single field queries (e.g., by `video_hash`)
- The `created_at` field for ordering

No composite indexes needed for current queries.

## Migration from SQLite to Firestore

### For Existing Production Data

If you have existing SQLite data to migrate:

```python
# migration_script.py
import sqlite3
import json
from google.cloud import firestore
from datetime import datetime

def migrate_sqlite_to_firestore():
    # Connect to SQLite
    conn = sqlite3.connect('transcriptions.db')
    cursor = conn.cursor()
    cursor.execute("SELECT video_hash, filename, file_path, transcription_data, created_at FROM transcriptions")

    # Initialize Firestore
    db = firestore.Client()
    collection = db.collection('transcriptions')

    # Migrate each record
    for row in cursor.fetchall():
        video_hash, filename, file_path, transcription_data_json, created_at = row

        doc_data = {
            'video_hash': video_hash,
            'filename': filename,
            'file_path': file_path,
            'transcription_data': json.loads(transcription_data_json),
            'created_at': datetime.fromisoformat(created_at) if created_at else firestore.SERVER_TIMESTAMP
        }

        collection.document(video_hash).set(doc_data)
        print(f"Migrated: {video_hash}")

    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate_sqlite_to_firestore()
```

## Local Development

### Testing with SQLite (Recommended)

Keep using SQLite for local development:

```bash
# .env
DATABASE_TYPE=sqlite
DATABASE_PATH=transcriptions.db
```

### Testing with Firestore Emulator (Optional)

For testing Firestore locally:

```bash
# Install Firebase CLI
npm install -g firebase-tools

# Start Firestore emulator
firebase emulators:start --only firestore

# Set environment
export FIRESTORE_EMULATOR_HOST=localhost:8080
export DATABASE_TYPE=firestore
export FIRESTORE_COLLECTION=transcriptions

# Run your app
python main.py
```

### Testing with Production Firestore (Optional)

To test against production Firestore from local:

```bash
# Authenticate with gcloud
gcloud auth application-default login

# Set environment
export DATABASE_TYPE=firestore
export FIRESTORE_COLLECTION=transcriptions-dev

# Run your app
python main.py
```

## Performance Considerations

### Firestore vs SQLite

**Firestore advantages:**
- Fully managed, no database files
- Scales automatically
- Works with ephemeral Cloud Run instances
- Built-in replication and backups
- Real-time updates capability (future feature)

**Trade-offs:**
- Network latency (10-50ms per operation vs <1ms for SQLite)
- Cost-per-operation pricing model
- Query limitations compared to SQL

### Optimization Tips

1. **Use batch operations** when storing multiple documents
2. **Cache frequently accessed data** in memory
3. **Use document IDs** (video_hash) for direct lookups instead of queries
4. **Minimize reads** by storing all needed data in single document
5. **Monitor costs** via Google Cloud Console

### Cost Estimation

Firestore pricing (as of 2025):
- Document reads: $0.06 per 100,000
- Document writes: $0.18 per 100,000
- Document deletes: $0.02 per 100,000
- Storage: $0.18/GB/month

For typical usage (1000 transcriptions/month):
- Writes: ~1000 = $0.002
- Reads: ~10,000 = $0.006
- Storage: ~1GB = $0.18
- **Total: ~$0.20/month**

## Monitoring

### Check Database Backend

The application logs which backend is initialized:

```
Initialized firestore database backend
Firestore backend initialized with collection: transcriptions
```

### Firestore Console

Monitor your data via:
1. Google Cloud Console → Firestore
2. View documents in the `transcriptions` collection
3. Check query performance
4. Review costs in billing

### Application Logging

Both backends include detailed logging:

```python
# Success logs
Stored transcription for video.mp4 with hash abc123 in Firestore

# Error logs
Error storing transcription in Firestore: [error details]
Error retrieving transcription from Firestore: [error details]
```

## Troubleshooting

### Common Issues

#### 1. "Permission denied" errors

**Cause:** Service account lacks Firestore permissions

**Solution:**
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT" \
  --role="roles/datastore.user"
```

#### 2. "Firestore API not enabled"

**Cause:** Firestore API not activated

**Solution:**
```bash
gcloud services enable firestore.googleapis.com
```

#### 3. "Collection not found" or empty results

**Cause:** Wrong collection name or no data

**Solution:**
- Verify `FIRESTORE_COLLECTION` environment variable
- Check data exists in Firestore Console

#### 4. Slow query performance

**Cause:** Network latency or missing indexes

**Solution:**
- Ensure Cloud Run and Firestore are in same region
- Check if composite index needed (unlikely for current queries)

#### 5. "Backend not initialized" errors

**Cause:** Configuration issue or import problem

**Solution:**
- Verify `DATABASE_TYPE` is set correctly
- Check application logs for initialization messages
- Ensure `google-cloud-firestore` dependency installed

## Rollback Plan

If issues occur in production:

1. **Immediate rollback:**
   ```bash
   gcloud run services update ai-subs-api \
     --region=us-central1 \
     --set-env-vars="DATABASE_TYPE=sqlite"
   ```

   **Note:** This will only work if you have persistent volume mounted with SQLite database.

2. **Full rollback:**
   - Revert to previous Cloud Run revision
   ```bash
   gcloud run services update-traffic ai-subs-api \
     --region=us-central1 \
     --to-revisions=PREVIOUS_REVISION=100
   ```

## Security Considerations

### Authentication

- Firestore uses Google Cloud IAM for authentication
- Cloud Run service account automatically authenticated
- No credentials needed in code (uses Application Default Credentials)

### Data Access

- Only the Cloud Run service account can access Firestore
- Fine-grained permissions via IAM roles
- Audit logs available via Cloud Logging

### Data Encryption

- Firestore encrypts data at rest by default
- All data encrypted in transit (HTTPS)
- No additional configuration needed

## Next Steps

After migration:

1. **Monitor performance** for first 24-48 hours
2. **Verify costs** in Cloud Billing
3. **Test all CRUD operations** via application
4. **Check error logs** for any issues
5. **Document any custom configurations** for your team

## Support

For issues:
1. Check application logs: `gcloud run logs read ai-subs-api --region=us-central1`
2. Review Firestore metrics in Cloud Console
3. Consult [Firestore documentation](https://cloud.google.com/firestore/docs)
4. Check backend code in `/backend/database.py`
