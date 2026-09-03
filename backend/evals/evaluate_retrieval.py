"""
Offline retrieval-evaluation harness for TranscriptEmbeddingService.search_transcript_chunks().

Measures whether the correct transcript moment appears in the first `--top-k`
results for a set of hand-written question/answer cases. This is a developer
tool only -- it does not change production retrieval behavior.

Usage (run from backend/):
    python evals/evaluate_retrieval.py
    python evals/evaluate_retrieval.py --top-k 10
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Run as `python evals/evaluate_retrieval.py` from backend/, so backend/ (the
# parent of this file) needs to be on sys.path for `services.*` to import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.transcript_embedding_service import transcript_embedding_service  # noqa: E402

REQUIRED_FIELDS = (
    "name",
    "video_hash",
    "user_id",
    "question",
    "expected_start_seconds",
    "acceptable_window_seconds",
)
NUMERIC_FIELDS = ("expected_start_seconds", "acceptable_window_seconds")
PLACEHOLDER = "REPLACE_ME"


def load_cases(path: Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        cases = json.load(handle)
    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a JSON array of cases")
    return cases


def validate_case(case: Dict[str, Any]) -> List[str]:
    """Return a list of problems with the case; empty list means valid."""
    problems: List[str] = []

    if not isinstance(case, dict):
        return [f"case must be a JSON object, got {type(case).__name__}"]

    for field in REQUIRED_FIELDS:
        if field not in case:
            problems.append(f"missing required field '{field}'")
            continue

        value = case[field]

        if field in NUMERIC_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"field '{field}' must be a number, got {value!r}")
            continue

        if not isinstance(value, str) or not value.strip():
            problems.append(f"field '{field}' must be a non-empty string, got {value!r}")
        elif PLACEHOLDER in value:
            problems.append(
                f"field '{field}' still contains placeholder value '{PLACEHOLDER}' -- "
                f"replace it with a real value in retrieval_cases.json"
            )

    return problems


def run_case(case: Dict[str, Any], top_k: int) -> Dict[str, Any]:
    name = case["name"]
    expected = case["expected_start_seconds"]
    window = case["acceptable_window_seconds"]

    try:
        results = transcript_embedding_service.search_transcript_chunks(
            video_hash=case["video_hash"],
            query=case["question"],
            user_id=case["user_id"],
            n_results=top_k,
        )
    except Exception as e:
        return {
            "name": name,
            "passed": False,
            "error": str(e),
            "expected": expected,
            "returned": [],
        }

    returned = [r["metadata"]["start"] for r in results]
    passed = any(abs(start - expected) <= window for start in returned)

    return {
        "name": name,
        "passed": passed,
        "error": None,
        "expected": expected,
        "returned": returned,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default="evals/retrieval_cases.json",
        help="Path to the retrieval cases JSON file (default: evals/retrieval_cases.json)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of retrieval results to check per case (default: 5)",
    )
    args = parser.parse_args()

    cases_path = Path(args.cases)
    try:
        cases = load_cases(cases_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"Failed to load cases from {cases_path}: {e}")
        return 1

    if not cases:
        print(f"No cases found in {cases_path}")
        return 1

    all_problems: List[str] = []
    for i, case in enumerate(cases):
        case_name = case.get("name", f"case[{i}]") if isinstance(case, dict) else f"case[{i}]"
        for problem in validate_case(case):
            all_problems.append(f"{case_name}: {problem}")

    if all_problems:
        print(f"Invalid cases in {cases_path}:")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1

    results = [run_case(case, args.top_k) for case in cases]

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        line = (
            f"[{status}] {result['name']} "
            f"expected={result['expected']}s returned={result['returned']}"
        )
        if result["error"]:
            line += f" error={result['error']}"
        print(line)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    hit_rate = (passed / total * 100) if total else 0.0

    print()
    print(f"Total cases: {total}")
    print(f"Passed:      {passed}")
    print(f"Failed:      {failed}")
    print(f"Hit@{args.top_k}: {hit_rate:.1f}%")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
