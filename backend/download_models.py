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


def download_panns_model():
    """Download PANNs model and label file to prevent runtime downloads."""
    print("="*50)
    print("Downloading PANNs model...")
    print("="*50)

    import urllib.request

    # Create PANNs data directory
    panns_dir = "/root/panns_data"
    os.makedirs(panns_dir, exist_ok=True)
    print(f"PANNs directory: {panns_dir}")

    try:
        # Download class labels CSV
        labels_url = "http://storage.googleapis.com/panns_data/class_labels_indices.csv"
        labels_path = os.path.join(panns_dir, "class_labels_indices.csv")
        print(f"Downloading class labels from {labels_url}...")
        urllib.request.urlretrieve(labels_url, labels_path)
        print(f"  OK: Labels downloaded to: {labels_path}")

        # Download PANNs checkpoint
        checkpoint_url = "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth"
        checkpoint_path = os.path.join(panns_dir, "Cnn14_mAP=0.431.pth")
        print(f"Downloading checkpoint from {checkpoint_url}...")
        urllib.request.urlretrieve(checkpoint_url, checkpoint_path)

        # Verify checkpoint was downloaded
        if os.path.exists(checkpoint_path):
            checkpoint_size = os.path.getsize(checkpoint_path) / (1024 * 1024)  # MB
            print(f"  OK: Checkpoint downloaded to: {checkpoint_path} ({checkpoint_size:.1f} MB)")
        else:
            raise Exception("Checkpoint file not found after download")

        # Verify the model loads correctly
        print("  Verifying PANNs model loads correctly...")
        import torch
        import panns_inference
        from panns_inference import AudioTagging

        # Try to load the model
        model = AudioTagging(
            checkpoint_path=checkpoint_path,
            device='cpu'
        )
        print("  OK: PANNs model verified successfully")
        del model  # Free memory

    except Exception as e:
        print(f"  WARNING: PANNs model download failed: {e}")
        import traceback
        traceback.print_exc()
        # Don't raise - PANNs is optional, allow build to continue
        print("  PANNs will auto-download on first use if needed")


def download_emotion_model():
    """Download wav2vec2 emotion recognition model to prevent runtime downloads."""
    print("="*50)
    print("Downloading Emotion Recognition model...")
    print("="*50)

    model_name = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"

    try:
        from transformers import AutoModelForAudioClassification, AutoFeatureExtractor

        print(f"Downloading {model_name}...")
        print("  Downloading feature extractor...")
        AutoFeatureExtractor.from_pretrained(model_name)
        print("  Downloading model weights...")
        AutoModelForAudioClassification.from_pretrained(model_name)
        print(f"  OK: Emotion model downloaded successfully")

    except Exception as e:
        print(f"  WARNING: Emotion model download failed: {e}")
        import traceback
        traceback.print_exc()
        # Don't raise - emotion detection is optional
        print("  Emotion detection will be skipped if model unavailable")


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

    # Download PANNs model (optional)
    download_panns_model()

    # Download emotion recognition model (optional)
    download_emotion_model()

    # Download translation models
    download_translation_models()

    print("="*50)
    print("All model downloads complete!")
    print("="*50)


if __name__ == '__main__':
    main()
