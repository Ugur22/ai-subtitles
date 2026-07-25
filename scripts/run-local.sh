#!/usr/bin/env bash
# Run ai-subs fully locally (no GPU, no cloud): SQLite + local disk + CPU/MPS models.
#
# Usage:
#   ./scripts/run-local.sh            # setup + start backend and frontend
#   ./scripts/run-local.sh backend    # setup + start backend only
#   ./scripts/run-local.sh frontend   # start frontend only
#
# Local-mode settings are exported as environment variables, which take
# precedence over backend/.env and frontend/.env — your existing env files
# (HUGGINGFACE_TOKEN, API keys, ...) are used as-is and never modified.
#
# First pipeline run downloads models to ~/.cache (~8-10GB) — later runs are offline.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
MODE="${1:-all}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

export_local_mode_env() {
  # Overrides for this process only — real env files stay untouched.
  export LOCAL_MODE=true
  export ENABLE_GCS_UPLOADS=true          # storage behind this flag is local disk in LOCAL_MODE
  export FASTWHISPER_DEVICE=cpu           # ctranslate2 has no MPS; cpu/int8 is the Mac path
  export FASTWHISPER_COMPUTE_TYPE=int8
  export CORS_ORIGINS='["http://localhost:5173"]'
  export PYTORCH_ENABLE_MPS_FALLBACK=1    # CPU fallback for torch ops MPS lacks (pyannote)

  # Only default the LLM provider when the user hasn't chosen one themselves.
  if ! grep -qE '^DEFAULT_LLM_PROVIDER=.+' "$BACKEND/.env" 2>/dev/null; then
    export DEFAULT_LLM_PROVIDER=local     # Ollama at localhost:11434
  fi
}

setup_backend() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    red "ffmpeg not found. Install it with: brew install ffmpeg"
    exit 1
  fi

  if [ ! -x "$BACKEND/venv/bin/python" ]; then
    echo "Creating venv..."
    python3 -m venv "$BACKEND/venv"
  fi

  # Install deps only when requirements-local.txt changed since last install
  local marker="$BACKEND/venv/.local-requirements-installed"
  if [ ! -f "$marker" ] || ! cmp -s "$BACKEND/requirements-local.txt" "$marker"; then
    echo "Installing backend dependencies (this can take a while)..."
    "$BACKEND/venv/bin/python" -m pip install -q -r "$BACKEND/requirements-local.txt"
    cp "$BACKEND/requirements-local.txt" "$marker"
  fi

  # HuggingFace token (from .env or the environment) enables pyannote diarization
  if ! grep -qE '^HUGGINGFACE_TOKEN=.+' "$BACKEND/.env" 2>/dev/null && [ -z "${HUGGINGFACE_TOKEN:-}" ]; then
    red "HUGGINGFACE_TOKEN not set — speaker diarization will be disabled."
    red "To enable it:"
    red "  1. Accept terms: https://huggingface.co/pyannote/speaker-diarization-3.1"
    red "  2. Accept terms: https://huggingface.co/pyannote/segmentation-3.0"
    red "  3. Create a read token: https://huggingface.co/settings/tokens"
    red "  4. Add HUGGINGFACE_TOKEN=hf_... to backend/.env"
  fi
}

setup_frontend() {
  if [ ! -d "$FRONTEND/node_modules" ]; then
    echo "Installing frontend dependencies..."
    (cd "$FRONTEND" && npm install)
  fi
}

start_backend() {
  cd "$BACKEND"
  green "Starting backend on http://localhost:8000 (LOCAL_MODE)"
  exec ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
}

start_frontend() {
  cd "$FRONTEND"
  # Vite reads these from the process env, overriding frontend/.env
  export VITE_LOCAL_MODE=true
  export VITE_API_URL=http://localhost:8000
  green "Starting frontend on http://localhost:5173"
  exec npm run dev
}

case "$MODE" in
  backend)
    export_local_mode_env
    setup_backend
    start_backend
    ;;
  frontend)
    setup_frontend
    start_frontend
    ;;
  all)
    export_local_mode_env
    setup_backend
    setup_frontend
    cd "$BACKEND"
    green "Starting backend on http://localhost:8000 (LOCAL_MODE)"
    ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 &
    BACKEND_PID=$!
    trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT
    sleep 2
    start_frontend
    ;;
  *)
    echo "Usage: $0 [backend|frontend|all]"
    exit 1
    ;;
esac
