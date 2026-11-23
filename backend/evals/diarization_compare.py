"""
Compare two diarization_ab.py result files.

Usage (from backend/):
    python evals/diarization_compare.py a.json b.json
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Overlap = Dict[Tuple[str, str], float]


def overlap_seconds(a_turns: List[Dict], b_turns: List[Dict]) -> Overlap:
    overlap: Overlap = defaultdict(float)
    b_sorted = sorted(b_turns, key=lambda t: t["start"])
    lo = 0
    for a in sorted(a_turns, key=lambda t: t["start"]):
        while lo < len(b_sorted) and b_sorted[lo]["end"] <= a["start"]:
            lo += 1
        for b in b_sorted[lo:]:
            if b["start"] >= a["end"]:
                break
            seconds = min(a["end"], b["end"]) - max(a["start"], b["start"])
            if seconds > 0:
                overlap[(a["speaker"], b["speaker"])] += seconds
    return overlap


def greedy_one_to_one_mapping(overlap: Overlap) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    used_b = set()
    for (a_spk, b_spk), _ in sorted(overlap.items(), key=lambda kv: -kv[1]):
        if a_spk not in mapping and b_spk not in used_b:
            mapping[a_spk] = b_spk
            used_b.add(b_spk)
    return mapping


def _speech_seconds(turns: List[Dict]) -> float:
    return round(sum(t["end"] - t["start"] for t in turns), 1)


def compare_turns(a_turns: List[Dict], b_turns: List[Dict]) -> Dict:
    overlap = overlap_seconds(a_turns, b_turns)
    mapping = greedy_one_to_one_mapping(overlap)
    shared = sum(overlap.values())
    matched = sum(overlap[pair] for pair in mapping.items())
    return {
        "speakers": {"a": len({t["speaker"] for t in a_turns}), "b": len({t["speaker"] for t in b_turns})},
        "speech_seconds": {"a": _speech_seconds(a_turns), "b": _speech_seconds(b_turns)},
        "mapping": mapping,
        "shared_speech_seconds": round(shared, 2),
        "unmatched_shared_speech": round(1 - matched / shared, 4) if shared else None,
    }


def compare_results(a: Dict, b: Dict) -> Dict:
    report = compare_turns(a["turns"], b["turns"])
    for key in ("label", "pyannote_version", "pipeline", "wall_seconds", "peak_gpu_allocated_mb"):
        report[key] = {"a": a.get(key), "b": b.get(key)}
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a")
    parser.add_argument("b")
    args = parser.parse_args(argv)
    a = json.loads(Path(args.a).read_text(encoding="utf-8"))
    b = json.loads(Path(args.b).read_text(encoding="utf-8"))
    print(json.dumps(compare_results(a, b), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
