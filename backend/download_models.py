#!/usr/bin/env python3
"""Download all required models during Docker build."""

from transformers import MarianMTModel, MarianTokenizer
from huggingface_hub import snapshot_download
import os

# Set cache directory explicitly (matches Dockerfile ENV vars)
os.environ['HF_HOME'] = '/app/.cache/huggingface'
os.environ['TRANSFORMERS_CACHE'] = '/app/.cache/huggingface'
os.environ['XDG_CACHE_HOME'] = '/app/.cache'

# Common language models (source -> English)
# Each model is ~300MB, total ~3GB for all languages
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
]

def download_whisper_model():
    """Download faster-whisper model to prevent runtime downloads."""
    print("="*50)
    print("Downloading Faster-Whisper model...")
    print("="*50)

    # The model used by faster-whisper (Systran/faster-whisper-small)
    whisper_model = "Systran/faster-whisper-small"
    cache_dir = os.environ.get('HF_HOME', '/app/.cache/huggingface')

    print(f"Cache directory: {cache_dir}")
    print(f"Cache exists: {os.path.exists(cache_dir)}")

    try:
        print(f"Downloading {whisper_model}...")
        # Download to HuggingFace cache with explicit cache_dir
        model_path = snapshot_download(
            repo_id=whisper_model,
            local_files_only=False,
            cache_dir=cache_dir,
        )
        print(f"  OK: Whisper model downloaded to: {model_path}")

        # Verify the model files exist
        if os.path.exists(model_path):
            files = os.listdir(model_path)
            print(f"  Model files: {files}")

        # Also try to load with faster_whisper to ensure it works
        from faster_whisper import WhisperModel
        print("  Verifying model loads correctly...")
        model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8",
            download_root=cache_dir
        )
        print("  OK: Model verified successfully")
        del model  # Free memory

    except Exception as e:
        print(f"  ERROR: Whisper model failed: {e}")
        import traceback
        traceback.print_exc()
        raise  # Whisper is critical, fail the build if it can't be downloaded


def download_translation_models():
    """Download MarianMT translation models."""
    print("="*50)
    print("Downloading Translation models...")
    print("="*50)

    for lang in LANGUAGES:
        model_name = f'Helsinki-NLP/opus-mt-{lang}-en'
        try:
            print(f'Downloading {model_name}...')
            MarianTokenizer.from_pretrained(model_name)
            MarianMTModel.from_pretrained(model_name)
            print(f'  OK: {lang} model downloaded successfully')
        except Exception as e:
            print(f'  SKIP: {lang} model failed: {e}')
            # Continue with other languages even if one fails


def main():
    # Download Whisper model first (critical)
    download_whisper_model()

    # Download translation models
    download_translation_models()

    print("="*50)
    print("All model downloads complete!")
    print("="*50)


if __name__ == '__main__':
    main()
