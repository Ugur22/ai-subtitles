# GPU Cost Analysis for Cloud Run

## Current Setup (CPU Only)

| Resource | Config | Cost/hour |
|----------|--------|-----------|
| CPU | 2 vCPU | ~$0.048 |
| Memory | 8 GB | ~$0.040 |
| **Total** | | **~$0.09/hr** |

**Problem:** Speaker diarization on 80min video takes 1-2+ hours on CPU, with high risk of timeout (Cloud Run has 5-minute request timeout).

---

## GPU-Enabled Cloud Run (NVIDIA L4)

| Resource | Config | Cost/hour |
|----------|--------|-----------|
| CPU | 4 vCPU (minimum required) | ~$0.096 |
| Memory | 16 GB (minimum required) | ~$0.080 |
| GPU | NVIDIA L4 (24GB VRAM) | ~$0.67 |
| **Total** | | **~$0.85/hr** |

---

## Cost Comparison Per Video (80min video with diarization)

| Scenario | Processing Time | Cost |
|----------|-----------------|------|
| **CPU** (current) | ~60-120 min | $0.09-0.18 |
| **GPU** (L4) | ~5-10 min | $0.07-0.14 |

**Conclusion:** GPU is actually cheaper per video because it's ~10x faster!

---

## Monthly Cost Estimates

| Usage | CPU Cost | GPU Cost | Savings |
|-------|----------|----------|---------|
| 10 videos/month | ~$1-2 | ~$0.70-1.40 | 30% |
| 50 videos/month | ~$5-10 | ~$3.50-7 | 30% |
| 100 videos/month | ~$10-20 | ~$7-14 | 30% |

*Assumes scale-to-zero when idle (no minimum instances charged)*

---

## Feature Comparison

| Factor | CPU | GPU (L4) |
|--------|-----|----------|
| Min instances | 0 (free when idle) | 0 (free when idle) |
| Cold start time | ~10-30s | ~30-60s (GPU init) |
| Memory required | 8 GB | 16 GB minimum |
| CPU required | 2 vCPU | 4 vCPU minimum |
| Diarization speed | Very slow (~10-20x realtime) | Fast (~0.5-1x realtime) |
| Timeout risk | High | Low |
| Whisper speed | Moderate | Fast |
| PyTorch/CUDA support | CPU only | Full CUDA support |

---

## GPU Availability on Cloud Run

| GPU Type | VRAM | Availability | Best For |
|----------|------|--------------|----------|
| NVIDIA L4 | 24 GB | Cloud Run | Inference, ML workloads |
| NVIDIA T4 | 16 GB | Compute Engine only | Not available on Cloud Run |
| NVIDIA A100 | 40/80 GB | Compute Engine only | Training, heavy inference |

**Note:** Cloud Run only supports NVIDIA L4 GPUs currently.

---

## GPU Quota Requirements

| Quota Name | Per Instance | Default | Notes |
|------------|--------------|---------|-------|
| `NvidiaL4GpuAllocNoZonalRedundancyPerProjectRegion` | 10 units | 3 units | Request increase for GPU |

**To request quota increase:**
1. Go to: https://console.cloud.google.com/iam-admin/quotas?project=ai-subs-poc
2. Filter for: `NvidiaL4GpuAllocNoZonalRedundancyPerProjectRegion`
3. Request at least **10** (for 1 instance) or **30** (for 3 instances)

---

## Deployment Command (GPU-Enabled)

```bash
gcloud run deploy ai-subs-backend \
  --image=us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --no-gpu-zonal-redundancy \
  --cpu=4 \
  --memory=16Gi \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=1 \
  --port=8000 \
  --allow-unauthenticated \
  --no-cpu-throttling
```

---

## Recommendation

### For occasional use (< 20 videos/month):
- **GPU is cost-effective** - faster processing, lower per-video cost
- Scale-to-zero means you only pay when processing
- Eliminates timeout issues on long videos

### For heavy use (> 50 videos/month):
- Consider **committed use discounts** (up to 30% off)
- Or use **Compute Engine with spot instances** for batch processing

### Alternative: Disable diarization
If speaker labels aren't needed:
- Keep CPU-only setup
- Disable `ENABLE_SPEAKER_DIARIZATION=false`
- Processing will be fast enough on CPU (Whisper is reasonably fast)

---

## Sources

- [Cloud Run pricing | Google Cloud](https://cloud.google.com/run/pricing)
- [GPU support for services | Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/gpu)
- [GPU pricing | Google Cloud](https://cloud.google.com/compute/gpus-pricing)
- [NVIDIA L4 Price Comparison](https://getdeploying.com/gpus/nvidia-l4)
