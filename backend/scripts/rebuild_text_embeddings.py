"""Rebuild transcript and audio embeddings for one owner/video, or every completed job with --all.

Existing rows for other embedding models are left in place, so the rebuild can be rolled back.
"""

from build_retrieval_index import main


if __name__ == "__main__":
    raise SystemExit(main(rebuild_all=True))
