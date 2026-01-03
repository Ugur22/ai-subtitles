# Phase 4 Deployment Verification Checklist

Use this checklist to verify the Firestore migration is successful in production.

## Pre-Deployment

- [ ] Code reviewed and merged to main branch
- [ ] Dependencies added to requirements.txt
- [ ] Configuration options added to config.py
- [ ] Database abstraction layer implemented
- [ ] Local testing completed with SQLite
- [ ] Documentation reviewed

## Cloud Setup

- [ ] Firestore API enabled
  ```bash
  gcloud services list --enabled | grep firestore
  ```
  Expected: `firestore.googleapis.com`

- [ ] Firestore database created
  ```bash
  gcloud firestore databases list
  ```
  Expected: Database in desired region (e.g., us-central1)

- [ ] Service account has Firestore permissions
  ```bash
  gcloud projects get-iam-policy PROJECT_ID \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:SERVICE_ACCOUNT" \
    --format="table(bindings.role)"
  ```
  Expected: `roles/datastore.user` in list

## Deployment

- [ ] Environment variables set in Cloud Run
  ```bash
  gcloud run services describe ai-subs-api \
    --region=us-central1 \
    --format="yaml(spec.template.spec.containers[].env[])"
  ```
  Expected:
  ```
  - name: DATABASE_TYPE
    value: firestore
  - name: FIRESTORE_COLLECTION
    value: transcriptions
  ```

- [ ] New revision deployed successfully
  ```bash
  gcloud run services describe ai-subs-api \
    --region=us-central1 \
    --format="value(status.latestReadyRevisionName)"
  ```

- [ ] Service is receiving traffic
  ```bash
  gcloud run services describe ai-subs-api \
    --region=us-central1 \
    --format="yaml(status.traffic[])"
  ```
  Expected: Latest revision at 100%

## Post-Deployment Verification

### Logs

- [ ] Backend initialization logged
  ```bash
  gcloud run logs read ai-subs-api --region=us-central1 --limit=100 | grep "Initialized"
  ```
  Expected: `Initialized firestore database backend`

- [ ] Firestore collection initialized
  ```bash
  gcloud run logs read ai-subs-api --region=us-central1 --limit=100 | grep "Firestore backend initialized"
  ```
  Expected: `Firestore backend initialized with collection: transcriptions`

- [ ] No permission errors
  ```bash
  gcloud run logs read ai-subs-api --region=us-central1 --limit=100 | grep -i "permission denied"
  ```
  Expected: No output

- [ ] No Firestore API errors
  ```bash
  gcloud run logs read ai-subs-api --region=us-central1 --limit=100 | grep -i "API.*not enabled"
  ```
  Expected: No output

### Functional Testing

#### 1. Create Transcription

- [ ] Upload a test video via API
  ```bash
  # Via curl or frontend
  curl -X POST https://YOUR-SERVICE-URL/transcribe \
    -F "file=@test_video.mp4"
  ```

- [ ] Transcription completes successfully
  Expected: 200 status code with transcription data

- [ ] Data stored in Firestore
  ```bash
  # Check in Firestore console or via gcloud
  gcloud firestore collections list
  ```
  Expected: `transcriptions` collection exists

- [ ] Document created with correct structure
  Check in Firestore console:
  - Document ID is video_hash
  - Fields: video_hash, filename, file_path, transcription_data, created_at
  - created_at has valid timestamp

#### 2. Retrieve Transcription

- [ ] Get transcription by hash
  ```bash
  curl https://YOUR-SERVICE-URL/transcription/VIDEO_HASH
  ```

- [ ] Response matches stored data
  Expected: 200 status code with full transcription

- [ ] file_path included in response
  Expected: `file_path` field present in JSON

#### 3. List Transcriptions

- [ ] List endpoint returns data
  ```bash
  curl https://YOUR-SERVICE-URL/transcriptions
  ```

- [ ] Response includes metadata
  Expected: Array with video_hash, filename, created_at, file_path

- [ ] Thumbnail extracted correctly
  Expected: `thumbnail_url` field present (if screenshots exist)

- [ ] Results ordered by created_at DESC
  Expected: Newest transcriptions first

#### 4. Update Transcription

- [ ] Update file path
  ```bash
  # Via API endpoint (if exposed)
  ```

- [ ] Changes persisted in Firestore
  Check in Firestore console: file_path field updated

#### 5. Delete Transcription

- [ ] Delete test transcription
  ```bash
  curl -X DELETE https://YOUR-SERVICE-URL/transcription/VIDEO_HASH
  ```

- [ ] Document removed from Firestore
  Expected: Document no longer in collection

- [ ] Subsequent GET returns 404
  Expected: 404 status code

### Performance Testing

- [ ] Response times acceptable
  - Get transcription: < 200ms
  - List transcriptions: < 500ms
  - Store transcription: < 2s (depends on video size)

- [ ] No timeouts under load
  Test with multiple concurrent requests

- [ ] Memory usage stable
  Monitor Cloud Run metrics for memory leaks

### Cost Monitoring

- [ ] Firestore usage appears in billing
  ```bash
  # Check in Cloud Console → Billing → Reports
  # Filter by Firestore/Datastore service
  ```

- [ ] Costs within expected range
  - Reads: ~$0.06 per 100K
  - Writes: ~$0.18 per 100K
  - Storage: ~$0.18/GB/month

- [ ] No unexpected quota exceeded errors
  ```bash
  gcloud run logs read ai-subs-api --region=us-central1 | grep -i quota
  ```
  Expected: No output

### Security Verification

- [ ] Only service account can access Firestore
  Verify in Cloud Console → IAM & Admin

- [ ] No credentials exposed in logs
  ```bash
  gcloud run logs read ai-subs-api --region=us-central1 | grep -i "credential\|password\|secret"
  ```
  Expected: No sensitive data

- [ ] Firestore security rules not overly permissive
  Check in Firestore console → Rules

### Monitoring & Alerting

- [ ] Cloud Logging capturing Firestore operations
  Check in Cloud Console → Logging → Logs Explorer

- [ ] Error budget alerts configured
  Optional: Set up alerts for error rates

- [ ] Uptime monitoring configured
  Optional: Set up uptime checks

## Rollback Plan (If Issues Detected)

### Immediate Rollback

If critical issues found:

```bash
# Option 1: Switch back to SQLite (requires persistent volume)
gcloud run services update ai-subs-api \
  --region=us-central1 \
  --set-env-vars="DATABASE_TYPE=sqlite"

# Option 2: Revert to previous revision
gcloud run services update-traffic ai-subs-api \
  --region=us-central1 \
  --to-revisions=PREVIOUS_REVISION=100
```

- [ ] Rollback executed
- [ ] Service restored to working state
- [ ] Root cause identified
- [ ] Fix planned

## Documentation

- [ ] Deployment notes documented
- [ ] Any issues encountered logged
- [ ] Configuration documented for team
- [ ] Monitoring dashboards created

## Sign-Off

- [ ] All checks passed
- [ ] Performance acceptable
- [ ] Costs within budget
- [ ] Team notified of changes
- [ ] Documentation updated

---

**Deployment Date:** _______________
**Deployed By:** _______________
**Verified By:** _______________
**Status:** ☐ Success  ☐ Partial  ☐ Rollback Required

**Notes:**
```
[Add any deployment notes, observations, or issues here]
```
