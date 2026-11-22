# faster-whisper/CTranslate2 4.x and onnxruntime-gpu need CUDA 12 + cuDNN 9. Those come
# from torch's cu126 pip wheels (registered with ldconfig below), not from this base image.
FROM nvidia/cuda:12.6.3-base-ubuntu22.04

WORKDIR /app

# Don't set the transformers-specific cache variable: transformers 4.x would read it
# instead of HF_HOME/hub, where snapshot_download bakes the models.
ENV HF_HOME=/app/.cache/huggingface

# No compiler: every pinned package ships a Linux wheel except docopt and moviepy,
# which are pure Python.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ffmpeg \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && python -m pip install --upgrade pip
RUN mkdir -p /data/static/videos \
    /data/static/screenshots \
    /data/db \
    /app/.cache/huggingface \
    /root/panns_data

# Fetch every baked model BEFORE requirements.txt, so dependency bumps don't
# re-download several GB. This layer only changes when download_models.py does.
RUN pip install --no-cache-dir huggingface-hub==0.36.2
ARG WHISPER_MODEL_REPO=Systran/faster-whisper-large-v3
COPY download_models.py /tmp/models/download_models.py
RUN WHISPER_MODEL_REPO=${WHISPER_MODEL_REPO} python /tmp/models/download_models.py

RUN pip install --no-cache-dir torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu126 \
    && python -c "import glob, nvidia; print('\n'.join(d for p in nvidia.__path__ for d in sorted(glob.glob(p + '/*/lib'))))" \
       > /etc/ld.so.conf.d/nvidia-pip.conf \
    && ldconfig

COPY requirements.txt constraints.txt ./

# insightface hard-requires GUI opencv-python and CPU onnxruntime (faster-whisper and
# chromadb want onnxruntime too). The CPU and GPU onnxruntime wheels share one module
# directory, so the CPU build must be gone before the GPU one goes in.
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt \
    && pip uninstall -y opencv-python onnxruntime \
    && pip install --no-cache-dir --no-deps -c constraints.txt opencv-python-headless onnxruntime-gpu

# Cheap build-time check (no GPU needed): the GPU libraries import cleanly and
# onnxruntime is the GPU build (providers are compiled in, so no device is required)
RUN python -c "import ctranslate2, torch, cv2, onnxruntime as ort; \
assert 'CUDAExecutionProvider' in ort.get_available_providers(), ort.get_available_providers(); \
print('ctranslate2', ctranslate2.__version__, '| torch', torch.__version__, '| cuda', torch.version.cuda, \
'| cv2', cv2.__version__, '| onnxruntime', ort.__version__)"

# libcuda.so.1 is the driver, mounted by Cloud Run at runtime; every other library must resolve.
# The TensorRT provider is skipped: TensorRT is not installed and never selected.
RUN cd "$(python -c 'import os, onnxruntime; print(os.path.dirname(os.path.dirname(onnxruntime.__file__)))')" \
    && missing=$( { find ctranslate2 ctranslate2.libs -name '*.so*'; \
                    ls onnxruntime/capi/libonnxruntime_providers_cuda.so; } 2>/dev/null \
                 | xargs ldd 2>/dev/null | grep 'not found' | grep -v 'libcuda\.so' | sort -u) \
    && if [ -n "$missing" ]; then echo "Unresolved CUDA libraries:"; echo "$missing"; exit 1; fi

COPY verify_models.py /tmp/models/verify_models.py
RUN WHISPER_MODEL_REPO=${WHISPER_MODEL_REPO} python /tmp/models/verify_models.py && rm -rf /tmp/models

RUN test -f /root/panns_data/Cnn14_mAP=0.431.pth \
    && test -f /root/panns_data/class_labels_indices.csv \
    && ls -la /root/panns_data/

RUN find /app/.cache/huggingface -path '*bge-small-en-v1.5*/1_Pooling/config.json' | grep -q . \
    && find /app/.cache/huggingface -path '*bge-small-en-v1.5*/modules.json' | grep -q . \
    && echo "OK: bge-small-en-v1.5 cache is complete"
RUN find /app/.cache/huggingface -path '*all-MiniLM-L6-v2*/1_Pooling/config.json' | grep -q . \
    && find /app/.cache/huggingface -path '*all-MiniLM-L6-v2*/modules.json' | grep -q . \
    && echo "OK: MiniLM comparison/rollback cache is complete"

COPY . .

RUN mkdir -p /app/static && \
    ln -sf /data/static/videos /app/static/videos && \
    ln -sf /data/static/screenshots /app/static/screenshots

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
