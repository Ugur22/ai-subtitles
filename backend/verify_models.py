#!/usr/bin/env python3
"""Load every model fetched by download_models.py, fully offline, at image build time.

Runs after `pip install -r requirements.txt` with HF_HUB_OFFLINE=1, so an incomplete
cache or a library bump that can't read it fails the build instead of triggering a
silent runtime download on Cloud Run.
"""
import os

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

import download_models as m  # noqa: E402  (offline env vars must be set first)


def verify_whisper():
    from faster_whisper import WhisperModel

    # CPU is fine here: no GPU at build time.
    for repo_id in m.WHISPER_MODEL_REPOS:
        WhisperModel(repo_id, device="cpu", compute_type="int8",
                     download_root=m.HF_HOME, local_files_only=True)
        print(f"OK: whisper {repo_id}")


def verify_sentence_transformers():
    from sentence_transformers import SentenceTransformer

    for repo_id in m.SENTENCE_TRANSFORMER_REPOS:
        embedding = SentenceTransformer(repo_id).encode(["Test sentence"])
        if len(embedding[0]) != 384:
            raise RuntimeError(f"{repo_id} must produce 384-dimensional embeddings")
        print(f"OK: {repo_id} (384-dim)")

    # Loaded by short name at runtime, which resolves to the sentence-transformers/ repo.
    embedding = SentenceTransformer(m.CLIP_REPO.split('/', 1)[1]).encode(["A photo of a cat"])
    print(f"OK: {m.CLIP_REPO} ({len(embedding[0])}-dim)")


def verify_bart():
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(m.BART_REPO)
    model = AutoModelForSeq2SeqLM.from_pretrained(m.BART_REPO)
    inputs = tokenizer("Test summarization.", return_tensors="pt", max_length=1024, truncation=True)
    model.generate(inputs["input_ids"], max_length=50, min_length=10, num_beams=4)
    print(f"OK: {m.BART_REPO}")


def verify_translation():
    from huggingface_hub import try_to_load_from_cache
    from transformers import MarianMTModel, MarianTokenizer

    for lang in m.LANGUAGES:
        repo_id = m.translation_repo(lang)
        if not isinstance(try_to_load_from_cache(repo_id, "config.json"), str):
            print(f"SKIP: {lang} not fetched")
            continue
        MarianTokenizer.from_pretrained(repo_id)
        MarianMTModel.from_pretrained(repo_id)
        print(f"OK: {repo_id}")


def verify_panns():
    from panns_inference import AudioTagging

    AudioTagging(checkpoint_path=m.PANNS_CHECKPOINT, device='cpu')
    print("OK: PANNs")


def verify_insightface():
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    print("OK: InsightFace buffalo_l")


def main():
    verify_whisper()
    verify_sentence_transformers()
    verify_bart()
    verify_panns()
    verify_translation()
    verify_insightface()
    print("All baked models verified offline.")


if __name__ == '__main__':
    main()
