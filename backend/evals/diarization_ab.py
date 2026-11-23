"""
A/B harness for speaker diarization across pyannote versions.

pyannote 3.1 and 4.x need different torch versions, so they can't share an image.
Each image runs `run` on the same clips through the worker's own diarization path,
then `compare` diffs the two result files offline. Runs on the `ai-subs-diarization-ab`
GPU job (infra/scripts/diarization_ab.sh), never on the prod worker.

Usage (from backend/):
    python evals/diarization_ab.py run --clip ab-clips/meeting.mp4 --label pyannote-3.1
    python evals/diarization_ab.py compare a.json b.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS_PREFIX = "ab-results"


def _overlap_seconds(a_turns: List[Dict], b_turns: List[Dict]) -> Dict[Tuple[str, str], float]:
    overlap: Dict[Tuple[str, str], float] = defaultdict(float)
    b_sorted = sorted(b_turns, key=lambda t: t["start"])
    for a in a_turns:
        for b in b_sorted:
            if b["start"] >= a["end"]:
                break
            seconds = min(a["end"], b["end"]) - max(a["start"], b["start"])
            if seconds > 0:
                overlap[(a["speaker"], b["speaker"])] += seconds
    return overlap


def map_speakers(a_turns: List[Dict], b_turns: List[Dict]) -> Dict[str, str]:
    """One-to-one mapping from A's labels to B's, greedily by shared speech time."""
    mapping: Dict[str, str] = {}
    used_b = set()
    for (a_spk, b_spk), _ in sorted(_overlap_seconds(a_turns, b_turns).items(), key=lambda kv: -kv[1]):
        if a_spk not in mapping and b_spk not in used_b:
            mapping[a_spk] = b_spk
            used_b.add(b_spk)
    return mapping


def compare_turns(a_turns: List[Dict], b_turns: List[Dict]) -> Dict:
    """
    Agreement between two diarizations without ground truth.

    `label_disagreement` is the share of time where both runs hear speech but give
    it labels that don't correspond under the best one-to-one mapping. It is not DER:
    neither side is the reference.
    """
    overlap = _overlap_seconds(a_turns, b_turns)
    mapping = map_speakers(a_turns, b_turns)
    shared = sum(overlap.values())
    matched = sum(overlap[(a, b)] for a, b in mapping.items())
    return {
        "speakers_a": len({t["speaker"] for t in a_turns}),
        "speakers_b": len({t["speaker"] for t in b_turns}),
        "mapping": mapping,
        "shared_speech_seconds": round(shared, 2),
        "label_disagreement": round(1 - matched / shared, 4) if shared else None,
    }


def compare_results(a: Dict, b: Dict) -> Dict:
    report = compare_turns(a["turns"], b["turns"])
    for key in ("label", "pyannote_version", "pipeline", "speech_seconds", "wall_seconds", "peak_gpu_allocated_mb"):
        report[key] = {"a": a.get(key), "b": b.get(key)}
    return report


def _speaker_bounds(min_speakers: Optional[int], max_speakers: Optional[int]) -> Dict:
    return {"min_speakers": min_speakers, "max_speakers": max_speakers}


def run(clip: str, label: str, out: Optional[str], min_speakers: Optional[int], max_speakers: Optional[int]) -> Dict:
    # Heavy imports stay here so `compare` and the tests run without torch.
    import torch
    import pyannote.audio

    import speaker_diarization
    from config import settings
    from services.audio_service import AudioService
    from services.gcs_service import GCSService
    from services.transcription_checkpoint import TRANSCRIPTION_CHUNK_SECONDS

    work_dir = tempfile.mkdtemp(prefix="diarization-ab-")
    local_clip = GCSService.download_to_temp(clip)
    try:
        chunks = AudioService.extract_audio_streaming(
            source_url=local_clip, output_dir=work_dir, segment_duration=TRANSCRIPTION_CHUNK_SECONDS
        )
        audio_seconds = len(chunks) * TRANSCRIPTION_CHUNK_SECONDS
        chunked = audio_seconds > settings.USE_CHUNKED_DIARIZATION_ABOVE
        bounds = _speaker_bounds(min_speakers, max_speakers)

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()

        if chunked:
            diarizer = speaker_diarization.ChunkedSpeakerDiarizer(
                chunk_duration=settings.DIARIZATION_CHUNK_DURATION,
                similarity_threshold=settings.DIARIZATION_SIMILARITY_THRESHOLD,
                use_auth_token=settings.HUGGINGFACE_TOKEN,
                link_model=settings.DIARIZATION_LINK_MODEL,
            )
            try:
                turns = diarizer.diarize_chunked(
                    audio_chunks=chunks, chunk_duration=TRANSCRIPTION_CHUNK_SECONDS, **bounds
                )
            finally:
                diarizer.unload_pipeline()
        else:
            # Same concat as the worker's full-video path (background_worker.py).
            full_audio = chunks[0]
            if len(chunks) > 1:
                full_audio = os.path.join(work_dir, "full_audio.wav")
                concat_list = os.path.join(work_dir, "concat_list.txt")
                with open(concat_list, "w") as f:
                    f.writelines(f"file '{c}'\n" for c in chunks)
                subprocess.run(
                    ["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", full_audio, "-y"],
                    check=True, capture_output=True,
                )
            diarizer = speaker_diarization.SpeakerDiarizer(use_auth_token=settings.HUGGINGFACE_TOKEN)
            turns = diarizer.diarize(full_audio, **bounds)

        wall_seconds = time.monotonic() - started
        cuda = torch.cuda.is_available()
        result = {
            "label": label,
            "clip": clip,
            "pyannote_version": pyannote.audio.__version__,
            "torch_version": torch.__version__,
            "pipeline": getattr(speaker_diarization, "DIARIZATION_PIPELINE", "pyannote/speaker-diarization-3.1"),
            "path": "chunked" if chunked else "full",
            **bounds,
            "audio_seconds": audio_seconds,
            "wall_seconds": round(wall_seconds, 1),
            "peak_gpu_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20) if cuda else None,
            "peak_gpu_reserved_mb": round(torch.cuda.max_memory_reserved() / 2**20) if cuda else None,
            "speaker_count": len({t["speaker"] for t in turns}),
            "speech_seconds": round(sum(t["end"] - t["start"] for t in turns), 1),
            "turns": [{"start": t["start"], "end": t["end"], "speaker": t["speaker"]} for t in turns],
        }

        out = out or f"{RESULTS_PREFIX}/{label}/{Path(clip).stem}.json"
        result_path = os.path.join(work_dir, "result.json")
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)
        summary = {k: v for k, v in result.items() if k != "turns"}
        print(json.dumps({"diarization_ab": summary, "out": out}))
        if not GCSService.upload_local_file(result_path, out):
            raise RuntimeError(f"Failed to upload result to {out}")
        return result
    finally:
        os.unlink(local_clip)
        shutil.rmtree(work_dir, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Diarize one clip from GCS and upload the result JSON")
    run_p.add_argument("--clip", required=True, help="Bucket-relative path, e.g. ab-clips/meeting.mp4")
    run_p.add_argument("--label", required=True, help="Name of this side, e.g. pyannote-3.1")
    run_p.add_argument("--out", help=f"Result path in the bucket (default {RESULTS_PREFIX}/<label>/<clip>.json)")
    run_p.add_argument("--min-speakers", type=int)
    run_p.add_argument("--max-speakers", type=int)

    cmp_p = sub.add_parser("compare", help="Compare two local result files")
    cmp_p.add_argument("a")
    cmp_p.add_argument("b")

    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.clip, args.label, args.out, args.min_speakers, args.max_speakers)
    else:
        a = json.loads(Path(args.a).read_text(encoding="utf-8"))
        b = json.loads(Path(args.b).read_text(encoding="utf-8"))
        print(json.dumps(compare_results(a, b), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
