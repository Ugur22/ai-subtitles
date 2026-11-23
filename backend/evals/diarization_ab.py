"""
Diarize one GCS clip and upload the result, for comparing pyannote versions.

pyannote 3.1 and 4.x need different torch versions, so each side runs in its own
image on the `ai-subs-diarization-ab` GPU job (infra/scripts/diarization_ab.sh).
It picks full-audio or chunked diarization the way the worker does and records the
raw diarizer turns. Compare two results with evals/diarization_compare.py.

Usage (from backend/):
    python evals/diarization_ab.py --clip ab-clips/meeting.mp4 --label pyannote-3.1
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyannote.audio  # noqa: E402
import torch  # noqa: E402

import speaker_diarization  # noqa: E402
from config import settings  # noqa: E402
from services.audio_service import AudioService  # noqa: E402
from services.gcs_service import GCSService  # noqa: E402
from services.transcription_checkpoint import TRANSCRIPTION_CHUNK_SECONDS  # noqa: E402


def _diarize(chunks: List[str], work_dir: str, bounds: Dict, chunked: bool) -> List[Dict]:
    if chunked:
        diarizer = speaker_diarization.ChunkedSpeakerDiarizer(
            chunk_duration=settings.DIARIZATION_CHUNK_DURATION,
            similarity_threshold=settings.DIARIZATION_SIMILARITY_THRESHOLD,
            use_auth_token=settings.HUGGINGFACE_TOKEN,
            link_model=settings.DIARIZATION_LINK_MODEL,
        )
        try:
            return diarizer.diarize_chunked(audio_chunks=chunks, chunk_duration=TRANSCRIPTION_CHUNK_SECONDS, **bounds)
        finally:
            diarizer.unload_pipeline()

    full_audio = chunks[0]
    if len(chunks) > 1:
        full_audio = os.path.join(work_dir, "full_audio.wav")
        speaker_diarization.concatenate_audio_files(chunks, full_audio)
    return speaker_diarization.SpeakerDiarizer(use_auth_token=settings.HUGGINGFACE_TOKEN).diarize(full_audio, **bounds)


def run(clip: str, label: str, min_speakers: Optional[int], max_speakers: Optional[int]) -> Dict:
    work_dir = tempfile.mkdtemp(prefix="diarization-ab-")
    local_clip = GCSService.download_to_temp(clip)
    try:
        chunks = AudioService.extract_audio_streaming(
            source_url=local_clip, output_dir=work_dir, segment_duration=TRANSCRIPTION_CHUNK_SECONDS
        )
        audio_seconds = len(chunks) * TRANSCRIPTION_CHUNK_SECONDS
        chunked = audio_seconds > settings.USE_CHUNKED_DIARIZATION_ABOVE
        bounds = {"min_speakers": min_speakers, "max_speakers": max_speakers}

        cuda = torch.cuda.is_available()
        if cuda:
            torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        turns = _diarize(chunks, work_dir, bounds, chunked)
        wall_seconds = time.monotonic() - started

        summary = {
            "label": label,
            "clip": clip,
            "pyannote_version": pyannote.audio.__version__,
            "torch_version": torch.__version__,
            "pipeline": speaker_diarization.DIARIZATION_PIPELINE,
            "path": "chunked" if chunked else "full",
            **bounds,
            "audio_seconds": audio_seconds,
            "wall_seconds": round(wall_seconds, 1),
            "peak_gpu_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20) if cuda else None,
            "peak_gpu_reserved_mb": round(torch.cuda.max_memory_reserved() / 2**20) if cuda else None,
        }
        result = {**summary, "turns": [{"start": t["start"], "end": t["end"], "speaker": t["speaker"]} for t in turns]}

        out = f"ab-results/{label}/{Path(clip).stem}.json"
        result_path = os.path.join(work_dir, "result.json")
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)
        print(json.dumps({"diarization_ab": summary, "speakers": len({t["speaker"] for t in turns}), "out": out}))
        if not GCSService.upload_local_file(result_path, out):
            raise RuntimeError(f"Failed to upload result to {out}")
        return result
    finally:
        os.unlink(local_clip)
        shutil.rmtree(work_dir, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clip", required=True, help="Bucket-relative path, e.g. ab-clips/meeting.mp4")
    parser.add_argument("--label", required=True, help="Name of this side, e.g. pyannote-3.1")
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    args = parser.parse_args(argv)
    run(args.clip, args.label, args.min_speakers, args.max_speakers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
