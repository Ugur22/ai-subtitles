"""
Build or rebuild a named transcript-chunking index configuration for a
single already-transcribed video.

Retrieval-index experiments (see backend/evals/README.md) compare chunk
sizes 2, 3, and 5 against the existing chunk_size_3 baseline. Each
--index-config is stored under its own index_config value in
transcript_embeddings, so re-running this for one config never touches or
overwrites another config's rows -- including the baseline.

Usage (run from backend/):
    LOCAL_MODE=true python scripts/build_retrieval_index.py --video-hash <hash> --index-config chunk_size_5
    LOCAL_MODE=true python scripts/build_retrieval_index.py --video-hash <hash> --index-config chunk_size_2 --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.local_db import LOCAL_USER_ID  # noqa: E402
from services.transcript_embedding_service import (  # noqa: E402
    INDEX_CONFIGS,
    transcript_embedding_service,
)
from services.transcription_repository import transcription_repository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-hash", required=True, help="Video hash to index")
    parser.add_argument(
        "--user-id",
        default=LOCAL_USER_ID,
        help=f"Owner user id (default: local-mode user {LOCAL_USER_ID})",
    )
    parser.add_argument(
        "--index-config",
        required=True,
        choices=sorted(INDEX_CONFIGS),
        help="Named indexing configuration to build/rebuild",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index even if this config is already indexed for this video",
    )
    args = parser.parse_args()

    transcription = transcription_repository.get_transcription(args.video_hash, args.user_id)
    if not transcription:
        print(f"No completed transcription found for video_hash={args.video_hash} user_id={args.user_id}")
        return 1

    segments = transcription.get("transcription", {}).get("segments", [])
    if not segments:
        print(f"Transcription for {args.video_hash} has no segments to index")
        return 1

    chunk_size = INDEX_CONFIGS[args.index_config]
    print(
        f"Indexing video {args.video_hash} under index_config={args.index_config} "
        f"(chunk_size={chunk_size}) from {len(segments)} segments..."
    )
    num_chunks = transcript_embedding_service.index_transcript_chunks(
        video_hash=args.video_hash,
        segments=segments,
        user_id=args.user_id,
        chunk_size=chunk_size,
        index_config=args.index_config,
        force_reindex=args.force,
    )

    print(
        f"Indexed {num_chunks} chunks for index_config={args.index_config} "
        f"(chunk_size={chunk_size}), video {args.video_hash}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
