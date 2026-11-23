#!/usr/bin/env python3
"""Fetch every model baked into the Docker image (source of truth for what is baked).

Runs BEFORE `pip install -r requirements.txt` so dependency bumps don't invalidate this
multi-GB layer: only huggingface_hub, whisper_models and the stdlib may be imported here
(enforced by tests/test_deployment_contract.py). Load checks live in verify_models.py.
"""
import os
import urllib.request
import zipfile

from huggingface_hub import HfApi, snapshot_download

from whisper_models import WHISPER_MODEL_CHOICES

HF_HOME = '/app/.cache/huggingface'
os.environ['HF_HOME'] = HF_HOME
os.environ['XDG_CACHE_HOME'] = '/app/.cache'

WHISPER_MODEL_REPOS = tuple(WHISPER_MODEL_CHOICES.values())

# Active chat embedding model + offline MiniLM comparison/rollback (both 384-dim)
SENTENCE_TRANSFORMER_REPOS = ("BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2")
CLIP_REPO = "sentence-transformers/clip-ViT-B-32"
BART_REPO = "facebook/bart-large-cnn"

# Common language models (source -> English), ~300MB each
LANGUAGES = [
    'es',  # Spanish
    'it',  # Italian
    'fr',  # French
    'de',  # German
    'pt',  # Portuguese
    'nl',  # Dutch
    'ru',  # Russian
    'zh',  # Chinese
    'ja',  # Japanese
    'ar',  # Arabic
    'pl',  # Polish
    'tr',  # Turkish
    'ko',  # Korean
    'cs',  # Czech
]


def translation_repo(lang):
    return f'Helsinki-NLP/opus-mt-{lang}-en'


PANNS_DIR = "/root/panns_data"
# The original storage.googleapis.com/panns_data bucket returns 404 (taken down);
# GitHub raw is the surviving canonical source for the labels.
PANNS_LABELS_URL = "https://raw.githubusercontent.com/qiuqiangkong/audioset_tagging_cnn/master/metadata/class_labels_indices.csv"
PANNS_CHECKPOINT_URL = "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth"
PANNS_CHECKPOINT = os.path.join(PANNS_DIR, "Cnn14_mAP=0.431.pth")
PANNS_LABELS = os.path.join(PANNS_DIR, "class_labels_indices.csv")

# Same BASE_REPO_URL and layout insightface.utils.storage uses, so FaceAnalysis finds it offline.
INSIGHTFACE_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
INSIGHTFACE_DIR = "/root/.insightface/models/buffalo_l"


def _banner(title):
    print("=" * 50)
    print(title)
    print("=" * 50)


def _transformers_snapshot(repo_id):
    """Fetch only what transformers' from_pretrained loads: config/tokenizer files plus
    safetensors when the repo has them, else pytorch_model.bin (skips TF/Flax/Rust/ONNX)."""
    files = HfApi().list_repo_files(repo_id)
    has_safetensors = any(f.endswith('.safetensors') for f in files)
    patterns = ['*.json', '*.txt', '*.model', '*.spm']
    patterns += ['*.safetensors'] if has_safetensors else ['pytorch_model*.bin']
    return snapshot_download(repo_id, allow_patterns=patterns)


def fetch_whisper():
    for repo_id in WHISPER_MODEL_REPOS:
        _banner(f"Fetching Faster-Whisper {repo_id}...")
        # cache_dir=HF_HOME (not HF_HOME/hub) is where faster_whisper's download_root looks.
        path = snapshot_download(repo_id=repo_id, cache_dir=HF_HOME)
        print(f"  OK: {path}: {os.listdir(path)}")


def fetch_sentence_transformers():
    _banner("Fetching sentence-transformers models...")
    for repo_id in (*SENTENCE_TRANSFORMER_REPOS, CLIP_REPO):
        _transformers_snapshot(repo_id)
        print(f"  OK: {repo_id}")


def fetch_bart():
    _banner(f"Fetching {BART_REPO}...")
    _transformers_snapshot(BART_REPO)
    print(f"  OK: {BART_REPO}")


def fetch_translation_models():
    _banner("Fetching translation models...")
    for lang in LANGUAGES:
        repo_id = translation_repo(lang)
        try:
            _transformers_snapshot(repo_id)
            print(f'  OK: {lang} model fetched')
        except Exception as e:
            # Non-critical: verify_models.py skips languages that aren't cached.
            print(f'  SKIP: {lang} model failed: {e}')


def fetch_panns():
    _banner("Fetching PANNs model...")
    os.makedirs(PANNS_DIR, exist_ok=True)
    urllib.request.urlretrieve(PANNS_LABELS_URL, PANNS_LABELS)
    urllib.request.urlretrieve(PANNS_CHECKPOINT_URL, PANNS_CHECKPOINT)
    size_mb = os.path.getsize(PANNS_CHECKPOINT) / (1024 * 1024)
    print(f"  OK: {PANNS_CHECKPOINT} ({size_mb:.1f} MB)")


def fetch_insightface():
    _banner("Fetching InsightFace buffalo_l...")
    models_dir = os.path.dirname(INSIGHTFACE_DIR)
    os.makedirs(INSIGHTFACE_DIR, exist_ok=True)
    zip_path = os.path.join(models_dir, "buffalo_l.zip")
    urllib.request.urlretrieve(INSIGHTFACE_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(INSIGHTFACE_DIR)
    os.remove(zip_path)
    print(f"  OK: {INSIGHTFACE_DIR}: {os.listdir(INSIGHTFACE_DIR)}")


def main():
    fetch_whisper()
    fetch_sentence_transformers()
    fetch_bart()
    fetch_panns()
    fetch_translation_models()
    fetch_insightface()
    _banner("All model fetches complete!")


if __name__ == '__main__':
    main()
