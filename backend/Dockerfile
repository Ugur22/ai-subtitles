# Railway/Cloud Run optimized Dockerfile for FastAPI Backend
# Includes pre-downloaded translation models for production reliability

# Use Python 3.9 slim image as base
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Set HuggingFace cache directory (persists models in image)
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

# Install system dependencies including FFmpeg and wget (for PANNs model download)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*
# Create directories for persistent data
# Railway will mount volumes to these paths
RUN mkdir -p /data/static/videos \
    /data/static/screenshots \
    /data/chroma_db \
    /data/db \
    /app/.cache/huggingface \
    /root/panns_data

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download MarianMT translation models during build
# This prevents runtime download failures in Cloud Run/Railway
# Models: Spanish, Italian, French, German, Portuguese, Dutch, Russian, Chinese, Japanese, Arabic
COPY download_models.py /tmp/download_models.py
RUN python /tmp/download_models.py && rm /tmp/download_models.py

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
