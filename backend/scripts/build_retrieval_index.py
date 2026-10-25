"""Build one owner-scoped transcript index without changing other model/config indexes."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


INDEX_CONFIGS = {"chunk_size_2": 2, "chunk_size_3": 3, "chunk_size_5": 5}


def _completed_targets(client):
    rows = client.table("jobs").select("user_id,video_hash").eq("status", "completed").execute().data or []
    return sorted({(row["user_id"], row["video_hash"]) for row in rows if row.get("user_id") and row.get("video_hash")})


def main(rebuild_all: bool = False) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-hash")
    parser.add_argument("--user-id", help="Owner of the completed transcription")
    parser.add_argument("--index-config", choices=sorted(INDEX_CONFIGS), default="chunk_size_3")
    parser.add_argument("--model", choices=["BAAI/bge-small-en-v1.5", "all-MiniLM-L6-v2"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-remote", action="store_true",
                        help="Required: this uses the service key of the Supabase project in the environment")
    if rebuild_all:
        parser.add_argument("--all", action="store_true",
                            help="Every completed job; lists what would be rebuilt unless --execute is given")
        parser.add_argument("--execute", action="store_true", help="With --all: actually rebuild")
    args = parser.parse_args()
    use_all = rebuild_all and args.all
    if use_all and (args.video_hash or args.user_id):
        parser.error("--all cannot be combined with --video-hash or --user-id")
    if not use_all and not (args.video_hash and args.user_id):
        parser.error("--video-hash and --user-id are required" + (" (or --all)" if rebuild_all else ""))
    if args.model:
        os.environ["TEXT_EMBEDDING_MODEL"] = args.model

    from config import settings
    from evals.safety import require_remote_opt_in
    from services.transcript_embedding_service import transcript_embedding_service
    from services.transcription_repository import transcription_repository

    require_remote_opt_in(args.allow_remote, "transcript index rebuild" if rebuild_all else "transcript index build")
    dry_run = args.dry_run or (use_all and not args.execute)

    if use_all:
        from services.supabase_service import supabase
        targets = _completed_targets(supabase())
        if not targets:
            print("No completed jobs found")
            return 0
    else:
        targets = [(args.user_id, args.video_hash)]

    failures = 0
    for user_id, video_hash in targets:
        transcription = transcription_repository.get_transcription(video_hash, user_id)
        if not transcription:
            print(f"Owner={user_id} video={video_hash}: no completed transcription")
            failures += 1
            continue
        segments = transcription.get("transcription", {}).get("segments", [])
        print(f"Owner={user_id} video={video_hash} model={settings.TEXT_EMBEDDING_MODEL} "
              f"index={args.index_config} segments={len(segments)}")
        if dry_run:
            continue
        try:
            count = transcript_embedding_service.index_transcript_chunks(
                video_hash, segments, user_id,
                chunk_size=INDEX_CONFIGS[args.index_config], index_config=args.index_config,
                force_reindex=args.force or rebuild_all,
            )
            print(f"  Published {count} transcript chunks")
            if rebuild_all:
                count = transcript_embedding_service.index_audio_events(
                    video_hash, segments, user_id, force_reindex=True,
                )
                print(f"  Published {count} audio events")
        except Exception as error:
            print(f"  Index rebuild failed: {error}", file=sys.stderr)
            failures += 1
    if use_all and dry_run:
        print(f"Dry run: {len(targets)} video(s) listed, nothing written. Re-run with --execute to rebuild.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
