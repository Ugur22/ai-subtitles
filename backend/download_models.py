#!/usr/bin/env python3
"""Download all required models during Docker build."""

from transformers import MarianMTModel, MarianTokenizer
from huggingface_hub import snapshot_download
import os

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

    try:
        print(f"Downloading {whisper_model}...")
        # Download to HuggingFace cache
        snapshot_download(
            repo_id=whisper_model,
            local_files_only=False,
        )
        print(f"  OK: Whisper model downloaded successfully")
    except Exception as e:
        print(f"  ERROR: Whisper model failed: {e}")
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
