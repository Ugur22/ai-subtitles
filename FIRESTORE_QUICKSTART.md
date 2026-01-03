# Firestore Migration - Quick Start Guide

## 5-Minute Cloud Run Deployment

### Prerequisites
- Google Cloud project with billing enabled
- Cloud Run service already deployed
- gcloud CLI installed and authenticated

### Step 1: Enable Firestore API
```bash
gcloud services enable firestore.googleapis.com
```

### Step 2: Create Firestore Database
```bash
# Create in same region as Cloud Run (e.g., us-central1)
gcloud firestore databases create --region=us-central1
```

### Step 3: Grant Permissions
```bash
# Get your Cloud Run service account
SERVICE_ACCOUNT=$(gcloud run services describe ai-subs-api \
  --region=us-central1 \
  --format='value(spec.template.spec.serviceAccountName)')

# Grant Firestore access
gcloud projects add-iam-policy-binding $(gcloud config get-value project) \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/datastore.user"
```

### Step 4: Update Cloud Run Environment
```bash
gcloud run services update ai-subs-api \
  --region=us-central1 \
  --set-env-vars="DATABASE_TYPE=firestore,FIRESTORE_COLLECTION=transcriptions"
```

### Step 5: Verify Deployment
```bash
# Check logs for successful initialization
gcloud run logs read ai-subs-api --region=us-central1 --limit=50 | grep -i firestore

# Should see:
# "Initialized firestore database backend"
# "Firestore backend initialized with collection: transcriptions"
```

## Local Development

Keep using SQLite for local development - no changes needed!

```bash
# Your .env file (default)
DATABASE_TYPE=sqlite
DATABASE_PATH=transcriptions.db
```

## Rollback (If Needed)

```bash
# Switch back to SQLite (only works with persistent volume)
gcloud run services update ai-subs-api \
  --region=us-central1 \
  --set-env-vars="DATABASE_TYPE=sqlite"
```

Or revert to previous Cloud Run revision:
```bash
gcloud run services update-traffic ai-subs-api \
  --region=us-central1 \
  --to-revisions=PREVIOUS_REVISION=100
```

## Monitoring

### View Firestore Data
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Navigate to Firestore → Data
3. Open `transcriptions` collection
4. Verify documents appear after transcriptions

### Check Costs
1. Go to Cloud Console → Billing
2. Filter by Firestore/Datastore
3. Monitor read/write/storage costs

### Logs
```bash
# View application logs
gcloud run logs read ai-subs-api --region=us-central1

# Filter Firestore operations
gcloud run logs read ai-subs-api --region=us-central1 | grep -i firestore
```

## Common Issues

### "Permission denied"
**Fix:** Run Step 3 again to grant Firestore permissions

### "API not enabled"
**Fix:** Run Step 1 again to enable Firestore API

### "Collection not found"
**Fix:** Verify FIRESTORE_COLLECTION env var is set correctly

### Slow performance
**Fix:** Ensure Cloud Run and Firestore are in the same region

## Need Help?

- See full deployment guide: `FIRESTORE_DEPLOYMENT.md`
- Check implementation details: `PHASE4_IMPLEMENTATION_SUMMARY.md`
- Review code: `/backend/database.py`

## That's It!

Your Cloud Run instance now persists data to Firestore instead of ephemeral local storage.
