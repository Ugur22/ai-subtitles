"""
Offline end-to-end evaluation harness for the real POST /api/chat/ endpoint.

Unlike `evaluate_retrieval.py` (which only tests
`TranscriptEmbeddingService.search_transcript_chunks()`), this harness drives
the full chat/RAG pipeline -- retrieval, context assembly, and LLM
answer-synthesis -- exactly as `routers/chat.py`'s `chat_with_video()` runs it
in production, via an in-process ASGI client wrapping the real app from
`main.py` -- no live server needed. It rule-checks the final synthesized
answer text and
its citations against hand-verified ground truth, which is the only way to
catch answer-synthesis bugs that pass retrieval-only testing (see
`FINDINGS.md` for examples already found this way).

This is a local developer tool only -- it does not change production
behavior. Every run makes real LLM API calls (Groq/Grok, per
`DEFAULT_LLM_PROVIDER` / `--provider`) against whatever video is indexed
locally, so it has a real, if small, cost -- don't run it excessively.

Usage (run from backend/, requires LOCAL_MODE so it never touches a remote
Supabase project):
    LOCAL_MODE=true python evals/evaluate_chat.py
    LOCAL_MODE=true python evals/evaluate_chat.py --provider grok
    LOCAL_MODE=true python evals/evaluate_chat.py --cases evals/chat_cases.json --out evals/chat_eval_results.json
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Run as `python evals/evaluate_chat.py` from backend/, so backend/ (the
# parent of this file) needs to be on sys.path for `main`/`services.*` to
# import once we actually load the app inside main() below.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REQUIRED_FIELDS = (
    "id",
    "video_hash",
    "user_id",
    "question",
    "expected_answer",
    "expected_time_range",
)
STRING_FIELDS = ("id", "video_hash", "user_id", "question", "expected_answer")
PLACEHOLDER = "REPLACE_ME"

# Small, dependency-free stopword set for answer_terms_ok's keyword
# extraction. Deliberately not importing chat.py's `_extract_keywords` --
# that would pull the whole chat.py import chain (and its LLM/DB
# dependencies) into what should stay a decoupled, easily unit-testable
# scoring function.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "and", "or", "but", "that", "this",
    "it", "he", "she", "they", "his", "her", "their", "you", "your", "i",
    "we", "us", "with", "as", "by", "from", "because", "so", "not", "do",
    "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "should", "about", "if", "just", "now", "how", "what", "why", "who",
    "when", "where", "which", "him", "them", "my", "me",
}


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

    for field in STRING_FIELDS:
        if field not in case:
            continue
        value = case[field]
        if not isinstance(value, str) or not value.strip():
            problems.append(f"field '{field}' must be a non-empty string, got {value!r}")
        elif PLACEHOLDER in value:
            problems.append(
                f"field '{field}' still contains placeholder value '{PLACEHOLDER}' -- "
                f"replace it with a real value in chat_cases.json"
            )

    if "expected_time_range" in case:
        time_range = case["expected_time_range"]
        if not isinstance(time_range, dict):
            problems.append(f"field 'expected_time_range' must be an object, got {time_range!r}")
        else:
            for key in ("start", "end"):
                if key not in time_range:
                    problems.append(f"field 'expected_time_range' missing key '{key}'")
                elif isinstance(time_range[key], bool) or not isinstance(time_range[key], (int, float)):
                    problems.append(
                        f"field 'expected_time_range.{key}' must be a number, got {time_range[key]!r}"
                    )

    if "what_must_not_be_claimed" in case:
        forbidden = case["what_must_not_be_claimed"]
        if not isinstance(forbidden, list) or not all(isinstance(x, str) for x in forbidden):
            problems.append("field 'what_must_not_be_claimed' must be a list of strings")

    return problems


def citation_overlap(sources: List[Dict[str, Any]], expected_time_range: Dict[str, float]) -> bool:
    """True if any source's [start, end] window overlaps expected_time_range."""
    exp_start = expected_time_range["start"]
    exp_end = expected_time_range["end"]
    for source in sources or []:
        s_start = source.get("start")
        s_end = source.get("end")
        if s_start is None or s_end is None:
            continue
        if s_start <= exp_end and s_end >= exp_start:
            return True
    return False


def _extract_terms(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def answer_terms_ok(answer: str, expected_answer: str) -> bool:
    """True if a majority of expected_answer's key terms appear in answer."""
    terms = _extract_terms(expected_answer)
    if not terms:
        return True
    answer_lower = (answer or "").lower()
    hits = sum(1 for term in terms if term in answer_lower)
    return hits > len(terms) * 0.5


def forbidden_claims_ok(answer: str, what_must_not_be_claimed: List[str]) -> bool:
    """True (pass) if none of the forbidden substrings appear in answer."""
    answer_lower = (answer or "").lower()
    return not any(forbidden.lower() in answer_lower for forbidden in (what_must_not_be_claimed or []))


class _SyncASGIClient:
    """Minimal synchronous wrapper around httpx's ASGI transport.

    Needed because this repo pins fastapi==0.104.1/starlette==0.27.0 but
    leaves httpx unpinned (`httpx>=0.24.1` in requirements.txt): starlette
    0.27's `TestClient` still passes `app=` directly to `httpx.Client`, a
    kwarg httpx>=0.28 removed. `httpx.ASGITransport` itself only implements
    the async request path, so each call here drives it through a
    short-lived `asyncio.run()` -- same in-process ASGI call `TestClient`
    would make, just not routed through the now-broken wrapper.
    """

    def __init__(self, app):
        self._app = app

    def post(self, url: str, json: Dict[str, Any]):
        import httpx

        async def _post():
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
                return await async_client.post(url, json=json)

        return asyncio.run(_post())


def run_case(case: Dict[str, Any], client, provider: Optional[str]) -> Dict[str, Any]:
    case_id = case["id"]
    question = case["question"]
    payload: Dict[str, Any] = {
        "question": question,
        "video_hash": case["video_hash"],
        "provider": provider,
    }

    start_time = time.monotonic()
    try:
        response = client.post("/api/chat/", json=payload)
        duration_seconds = time.monotonic() - start_time
        if response.status_code != 200:
            return {
                "id": case_id,
                "question": question,
                "answer": None,
                "sources": None,
                "duration_seconds": duration_seconds,
                "citation_ok": False,
                "terms_ok": False,
                "forbidden_ok": False,
                "passed": False,
                "error": f"HTTP {response.status_code}: {response.text[:500]}",
            }
        body = response.json()
    except Exception as e:
        duration_seconds = time.monotonic() - start_time
        return {
            "id": case_id,
            "question": question,
            "answer": None,
            "sources": None,
            "duration_seconds": duration_seconds,
            "citation_ok": False,
            "terms_ok": False,
            "forbidden_ok": False,
            "passed": False,
            "error": str(e),
        }

    answer = body.get("answer") or ""
    sources = body.get("sources") or []

    citation_ok = citation_overlap(sources, case["expected_time_range"])
    terms_ok = answer_terms_ok(answer, case["expected_answer"])
    forbidden_ok = forbidden_claims_ok(answer, case.get("what_must_not_be_claimed", []))

    return {
        "id": case_id,
        "question": question,
        "answer": answer,
        "sources": sources,
        "duration_seconds": duration_seconds,
        "citation_ok": citation_ok,
        "terms_ok": terms_ok,
        "forbidden_ok": forbidden_ok,
        "passed": citation_ok and terms_ok and forbidden_ok,
        "error": None,
    }


def main() -> int:
    if os.environ.get("LOCAL_MODE") != "true":
        print(
            "LOCAL_MODE is not set to 'true'. This harness drives the real "
            "/api/chat/ endpoint in-process against the local SQLite store -- "
            "running it without LOCAL_MODE=true risks hitting a remote "
            "Supabase project instead. Run with:\n\n"
            "    LOCAL_MODE=true python evals/evaluate_chat.py\n"
        )
        return 1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default="evals/chat_cases.json",
        help="Path to the chat cases JSON file (default: evals/chat_cases.json)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider to force (default: None, uses DEFAULT_LLM_PROVIDER)",
    )
    parser.add_argument(
        "--out",
        default="evals/chat_eval_results.json",
        help="Path to write full per-case results JSON (default: evals/chat_eval_results.json)",
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
        case_id = case.get("id", f"case[{i}]") if isinstance(case, dict) else f"case[{i}]"
        for problem in validate_case(case):
            all_problems.append(f"{case_id}: {problem}")

    if all_problems:
        print(f"Invalid cases in {cases_path}:")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1

    # Deferred import: pulls in the full FastAPI app (model preloader, DB
    # clients, LLM services). Must only happen after the LOCAL_MODE check
    # above, and must not happen at module import time -- otherwise
    # `test_evaluate_chat.py` couldn't import the pure scoring functions
    # above without LOCAL_MODE/network/the whole app.
    #
    # See _SyncASGIClient's docstring for why this isn't
    # fastapi.testclient.TestClient.
    from main import app

    client = _SyncASGIClient(app)

    results = [run_case(case, client, args.provider) for case in cases]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        line = (
            f"[{status}] {result['id']} "
            f"citation_ok={result['citation_ok']} terms_ok={result['terms_ok']} "
            f"forbidden_ok={result['forbidden_ok']} ({result['duration_seconds']:.1f}s)"
        )
        if result["error"]:
            line += f" error={result['error']}"
        print(line)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    terms_rate = (sum(1 for r in results if r["terms_ok"]) / total * 100) if total else 0.0
    citation_rate = (sum(1 for r in results if r["citation_ok"]) / total * 100) if total else 0.0

    print()
    print(f"Total cases:               {total}")
    print(f"Passed:                    {passed}")
    print(f"Failed:                    {failed}")
    print(f"Answer-correctness rate:   {terms_rate:.1f}% (terms_ok)")
    print(f"Citation-correctness rate: {citation_rate:.1f}% (citation_ok)")
    print(f"Full results written to:   {out_path}")

    if failed:
        print()
        print("Failed case details:")
        cases_by_id = {c["id"]: c for c in cases if isinstance(c, dict) and "id" in c}
        for result in results:
            if result["passed"]:
                continue
            case = cases_by_id.get(result["id"], {})
            print(f"\n--- {result['id']} ---")
            print(f"Question:            {result['question']}")
            print(f"Expected answer:     {case.get('expected_answer')}")
            print(f"Expected time range: {case.get('expected_time_range')}")
            if result["error"]:
                print(f"Error:               {result['error']}")
            print(f"Actual answer:\n{result['answer']}")
            print(f"Actual sources:\n{json.dumps(result['sources'], indent=2)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
