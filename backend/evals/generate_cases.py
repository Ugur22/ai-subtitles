"""
Semi-automated candidate-case generator for the retrieval eval harness.

Samples chunks from an already-indexed video's transcript, asks the
existing LLM chat service to draft one natural question per sampled chunk,
and writes candidate cases to a separate file for human review. It never
writes directly to retrieval_cases.json -- LLM-authored questions are not
verified ground truth and must be reviewed before use.

This makes real LLM API calls (uses GROQ_API_KEY / XAI_API_KEY from .env)
and has a real cost -- don't run it excessively.

Usage (run from backend/):
    python evals/generate_cases.py --video-hash <hash> --user-id <id>
    python evals/generate_cases.py --video-hash <hash> --user-id <id> --count 30 --provider groq
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.evaluate_retrieval import validate_case  # noqa: E402
from llm_providers import llm_manager  # noqa: E402
from services.supabase_service import supabase  # noqa: E402

QUESTION_PROMPT = (
    "Here is a snippet of a video transcript (timestamp {start}s):\n\n"
    "\"{text}\"\n\n"
    "Write ONE natural, specific question a viewer might ask that is answered "
    "by this snippet. Do not mention \"the snippet\" or \"the transcript\". "
    "Reply with only the question, no quotes, no extra text."
)


def fetch_chunks(video_hash: str, user_id: str) -> List[Dict[str, Any]]:
    client = supabase()
    result = client.table('transcript_embeddings').select(
        'chunk_index,start_time,chunk_text'
    ).eq('user_id', user_id).eq('video_hash', video_hash).order('chunk_index').execute()
    return result.data or []


def sample_chunks(chunks: List[Dict[str, Any]], count: int, min_chunk_chars: int) -> List[Dict[str, Any]]:
    usable = [c for c in chunks if len(c.get('chunk_text', '').strip()) >= min_chunk_chars]
    if not usable:
        return []
    if count >= len(usable):
        return usable

    indices = sorted({round(i * (len(usable) - 1) / (count - 1)) for i in range(count)}) if count > 1 else [0]
    return [usable[i] for i in indices]


async def generate_question(chunk: Dict[str, Any], provider_name: str) -> str:
    provider = llm_manager.get_provider(provider_name)
    prompt = QUESTION_PROMPT.format(start=chunk['start_time'], text=chunk['chunk_text'])
    answer = await provider.generate([{"role": "user", "content": prompt}], temperature=0.7, max_tokens=60)
    return answer.strip().strip('"')


async def generate_cases(
    video_hash: str,
    user_id: str,
    count: int,
    window: float,
    min_chunk_chars: int,
    provider_name: str,
) -> Dict[str, Any]:
    chunks = fetch_chunks(video_hash, user_id)
    if not chunks:
        raise RuntimeError(
            f"No transcript chunks found for video_hash={video_hash!r} user_id={user_id!r}. "
            f"Check the ids, and that the video has been indexed."
        )

    sampled = sample_chunks(chunks, count, min_chunk_chars)

    candidates: List[Dict[str, Any]] = []
    skipped = 0
    for chunk in sampled:
        try:
            question = await generate_question(chunk, provider_name)
        except Exception as e:
            print(f"  skipping chunk {chunk['chunk_index']} (start={chunk['start_time']}s): {e}")
            skipped += 1
            continue

        if not question:
            print(f"  skipping chunk {chunk['chunk_index']} (start={chunk['start_time']}s): empty LLM response")
            skipped += 1
            continue

        case = {
            "name": f"generated-chunk-{chunk['chunk_index']}",
            "video_hash": video_hash,
            "user_id": user_id,
            "question": question,
            "expected_start_seconds": chunk['start_time'],
            "acceptable_window_seconds": window,
        }

        problems = validate_case(case)
        if problems:
            print(f"  skipping chunk {chunk['chunk_index']}: generated case failed validation: {problems}")
            skipped += 1
            continue

        candidates.append(case)

    return {
        "chunks_available": len(chunks),
        "chunks_sampled": len(sampled),
        "generated": len(candidates),
        "skipped": skipped,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-hash", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--count", type=int, default=15, help="Number of candidate cases to generate (default: 15)")
    parser.add_argument("--provider", default=None, help="LLM provider to use (default: configured default)")
    parser.add_argument("--window", type=float, default=30, help="acceptable_window_seconds for generated cases (default: 30)")
    parser.add_argument("--min-chunk-chars", type=int, default=90, help="Skip chunks shorter than this (default: 90)")
    parser.add_argument("--out", default="evals/generated_cases.json", help="Output file (default: evals/generated_cases.json)")
    args = parser.parse_args()

    try:
        result = asyncio.run(
            generate_cases(
                video_hash=args.video_hash,
                user_id=args.user_id,
                count=args.count,
                window=args.window,
                min_chunk_chars=args.min_chunk_chars,
                provider_name=args.provider,
            )
        )
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1

    out_path = Path(args.out)
    out_path.write_text(json.dumps(result["candidates"], indent=2) + "\n", encoding="utf-8")

    print()
    print(f"Chunks available: {result['chunks_available']}")
    print(f"Chunks sampled:   {result['chunks_sampled']}")
    print(f"Generated:        {result['generated']}")
    print(f"Skipped:          {result['skipped']}")
    print(f"Wrote candidates to {out_path}")
    print()
    print(
        "Review these before merging into retrieval_cases.json -- LLM-authored "
        "questions are not verified ground truth; a question can occasionally "
        "be answerable from a neighboring chunk too."
    )

    return 0 if result["generated"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
