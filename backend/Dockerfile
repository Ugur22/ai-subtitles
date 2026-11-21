# Railway/Cloud Run optimized Dockerfile for FastAPI Backend
# Includes pre-downloaded translation models for production reliability
# GPU-enabled with CUDA 12.6 + cuDNN 9 for NVIDIA L4 on Cloud Run
# (faster-whisper/CTranslate2 4.x and onnxruntime-gpu need CUDA 12 + cuDNN 9)

# Use NVIDIA CUDA base image (Ubuntu 22.04 ships Python 3.10)
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

# Set working directory
WORKDIR /app

# Set HuggingFace cache directory (persists models in image).
# Don't set the transformers-specific cache variable: transformers 4.x would read it
# instead of HF_HOME/hub, where snapshot_download bakes the models.
ENV HF_HOME=/app/.cache/huggingface

# Set CUDA environment variables
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}

# Install Python 3.10 (native to Ubuntu 22.04) and system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-dev \
    python3-venv \
    python3-pip \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    build-essential \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && python -m pip install --upgrade pip
# Create directories for persistent data
# Railway will mount volumes to these paths
RUN mkdir -p /data/static/videos \
    /data/static/screenshots \
    /data/db \
    /app/.cache/huggingface \
    /root/panns_data

# Fetch every baked model BEFORE requirements.txt, so dependency bumps don't
# re-download several GB. This layer only changes when download_models.py does.
# huggingface-hub must match requirements.txt (cache layout; enforced by tests).
RUN pip install --no-cache-dir huggingface-hub==0.36.2
# WHISPER_MODEL_REPO must match the FASTWHISPER_MODEL set at runtime (large-v3 -> this repo)
ARG WHISPER_MODEL_REPO=Systran/faster-whisper-large-v3
COPY download_models.py /tmp/models/download_models.py
RUN WHISPER_MODEL_REPO=${WHISPER_MODEL_REPO} python /tmp/models/download_models.py

# Install PyTorch with CUDA support (pinned here, independent of requirements.txt)
# Using CUDA 12.6 wheels (match the CUDA 12.6 / cuDNN 9 base image)
RUN pip install --no-cache-dir torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu126

COPY requirements.txt constraints.txt ./

# Install remaining Python dependencies at the exact versions in constraints.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Cheap build-time check (no GPU needed): the GPU libraries import cleanly
RUN python -c "import ctranslate2, torch; print('ctranslate2', ctranslate2.__version__, '| torch', torch.__version__, '| cuda', torch.version.cuda)"

# Load every fetched model fully offline: an incomplete cache or a library bump
# that can't read it fails the build here, not as a runtime download on Cloud Run.
COPY verify_models.py /tmp/models/verify_models.py
RUN WHISPER_MODEL_REPO=${WHISPER_MODEL_REPO} python /tmp/models/verify_models.py && rm -rf /tmp/models

# Verify critical pre-downloaded artifacts are baked into the image so failures
# surface at build time, not as silent runtime re-downloads on Cloud Run.
RUN test -f /root/panns_data/Cnn14_mAP=0.431.pth \
    && test -f /root/panns_data/class_labels_indices.csv \
    && ls -la /root/panns_data/

# Verify the sentence-transformers embedding model cache is COMPLETE. The runtime
# loads bge-small-en-v1.5 and needs the module subfolder files (1_Pooling/config.json,
# modules.json); a partial cache previously shipped and crash-looped the worker at
# import time. Fail the build loudly instead.
RUN find /app/.cache/huggingface -path '*bge-small-en-v1.5*/1_Pooling/config.json' | grep -q . \
    && find /app/.cache/huggingface -path '*bge-small-en-v1.5*/modules.json' | grep -q . \
    && echo "OK: bge-small-en-v1.5 cache is complete"
RUN find /app/.cache/huggingface -path '*all-MiniLM-L6-v2*/1_Pooling/config.json' | grep -q . \
    && find /app/.cache/huggingface -path '*all-MiniLM-L6-v2*/modules.json' | grep -q . \
    && echo "OK: MiniLM comparison/rollback cache is complete"

# Copy the rest of the application
COPY . .

# Create symlinks from app directories to persistent storage
# This allows the app to use normal paths while data is stored on volumes
# Note: /app/static may not exist if gitignored, so create it first
RUN mkdir -p /app/static && \
    ln -sf /data/static/videos /app/static/videos && \
    ln -sf /data/static/screenshots /app/static/screenshots

# Expose port (Railway will override this with PORT env var)
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Railway uses PORT environment variable
# Default to 8000 if not set
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
