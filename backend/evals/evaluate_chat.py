"""Evaluate authenticated POST /api/chat/ responses against reviewed cases.

This developer tool makes real LLM calls to an explicitly selected backend.
Set EVAL_BASE_URL, EVAL_USER_ID and EVAL_AUTH_TOKEN (the auth_token cookie)
in the environment. The session owner is verified before any chat requests.

Usage from backend/:
    python evals/evaluate_chat.py --cases evals/chat_cases.json --provider grok
    python evals/evaluate_chat.py --base-url https://your-staging-backend --top-k 5
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# Direct CLI runs and package imports must resolve the same history module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_history_db

# Best-effort model-name lookup per provider, read only from env vars that
# already control which model each provider in llm_providers.py uses. Never
# reads/stores API keys or any other secret -- just the model name string.
_PROVIDER_MODEL_ENV = {
    "groq": "GROQ_MODEL",
    "grok": "XAI_MODEL",
    "openai": "OPENAI_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
    "deepseek": "DEEPSEEK_MODEL",
    "ollama": "OLLAMA_MODEL",
}


def _get_git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def _get_effective_provider(results: List[Dict[str, Any]], requested_provider: Optional[str]) -> Optional[str]:
    for result in results:
        if result.get("provider_used"):
            return result["provider_used"]
    return requested_provider or "default"

REQUIRED_FIELDS = (
    "id",
    "video_hash",
    "user_id",
    "question",
    "expected_answer",
    "expected_time_range",
    "required_terms",
)
STRING_FIELDS = ("id", "video_hash", "user_id", "question", "expected_answer")
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

    if "required_terms" in case:
        required_terms = case["required_terms"]

        def _entry_ok(entry: Any) -> bool:
            if isinstance(entry, str):
                return bool(entry.strip())
            if isinstance(entry, list):
                # "any of these" synonym group -- at least one non-empty string.
                return bool(entry) and all(isinstance(x, str) and x.strip() for x in entry)
            return False

        if (
            not isinstance(required_terms, list)
            or not required_terms
            or not all(_entry_ok(x) for x in required_terms)
        ):
            problems.append(
                "field 'required_terms' must be a non-empty list where each entry is either a "
                "non-empty string (strict, must appear) or a non-empty list of non-empty strings "
                "(an 'any of these' synonym group, at least one must appear) -- "
                "pick 2-3 distinctive facts by hand, don't derive them from expected_answer"
            )

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


def answer_terms_ok(answer: str, required_terms: List[Any]) -> bool:
    """True iff every hand-picked required term appears in answer.

    required_terms are curated per-case (2-3 distinctive facts a correct
    answer must state), not derived from expected_answer's full wording --
    deriving from prose let a good paraphrase fail on wrong-word matches and
    let a vague answer pass on unimportant-word matches.

    Each entry is either a plain string (strict -- must appear verbatim) or
    a list of strings (an "any of these" synonym group -- at least one must
    appear). Groups exist for facts the model may correctly phrase multiple
    defensible ways -- e.g. a character named only via ambiguous diarization
    might correctly be called "the visiting spirit" instead of asserting an
    unconfirmed name -- without loosening genuinely load-bearing single facts
    (a plain string still requires an exact match).
    """
    if not required_terms:
        return True
    answer_lower = (answer or "").lower()
    for term in required_terms:
        if isinstance(term, list):
            if not any(t.lower() in answer_lower for t in term):
                return False
        elif term.lower() not in answer_lower:
            return False
    return True


def forbidden_claims_ok(answer: str, what_must_not_be_claimed: List[str]) -> bool:
    """True (pass) if none of the forbidden substrings appear in answer."""
    answer_lower = (answer or "").lower()
    return not any(forbidden.lower() in answer_lower for forbidden in (what_must_not_be_claimed or []))


class _AuthenticatedHTTPClient:
    def __init__(self, base_url: str, auth_token: str, refresh_token: Optional[str] = None):
        import httpx

        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("EVAL_BASE_URL must be an HTTP(S) origin without credentials or a path")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote evaluation requires HTTPS to protect the session cookie")
        if not auth_token or not auth_token.strip():
            raise ValueError("EVAL_AUTH_TOKEN is required")
        cookies = {"auth_token": auth_token}
        if refresh_token:
            cookies["auth_refresh_token"] = refresh_token
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), cookies=cookies, timeout=300.0,
            follow_redirects=False,
        )

    def verify_owner(self, user_id: str) -> None:
        response = self._client.get("/api/auth/me")
        if response.status_code != 200:
            raise ValueError(f"Session verification failed (HTTP {response.status_code})")
        if response.json().get("user_id") != user_id:
            raise ValueError("The authenticated session does not match the evaluation owner")

    def post(self, url: str, json: Dict[str, Any]):
        return self._client.post(url, json=json)

    def close(self) -> None:
        self._client.close()


def run_case(
    case: Dict[str, Any], client, provider: Optional[str], top_k: Optional[int] = None
) -> Dict[str, Any]:
    case_id = case["id"]
    question = case["question"]
    payload: Dict[str, Any] = {
        "question": question,
        "video_hash": case["video_hash"],
        "provider": provider,
    }
    if top_k is not None:
        payload["n_results"] = top_k

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
                "provider_used": None,
                "duration_seconds": duration_seconds,
                "citation_ok": False,
                "terms_ok": False,
                "forbidden_ok": False,
                "passed": False,
                "error": f"HTTP {response.status_code}",
            }
        body = response.json()
    except Exception as e:
        duration_seconds = time.monotonic() - start_time
        return {
            "id": case_id,
            "question": question,
            "answer": None,
            "sources": None,
            "provider_used": None,
            "duration_seconds": duration_seconds,
            "citation_ok": False,
            "terms_ok": False,
            "forbidden_ok": False,
            "passed": False,
            "error": f"Request failed ({type(e).__name__})",
        }

    answer = body.get("answer") or ""
    sources = body.get("sources") or []

    citation_ok = citation_overlap(sources, case["expected_time_range"])
    terms_ok = answer_terms_ok(answer, case["required_terms"])
    forbidden_ok = forbidden_claims_ok(answer, case.get("what_must_not_be_claimed", []))

    return {
        "id": case_id,
        "question": question,
        "answer": answer,
        "sources": sources,
        "provider_used": body.get("provider_used"),
        "duration_seconds": duration_seconds,
        "citation_ok": citation_ok,
        "terms_ok": terms_ok,
        "forbidden_ok": forbidden_ok,
        "passed": citation_ok and terms_ok and forbidden_ok,
        "error": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("EVAL_BASE_URL"),
                        help="Explicit backend origin (or EVAL_BASE_URL)")
    parser.add_argument("--user-id", default=os.environ.get("EVAL_USER_ID"),
                        help="Expected authenticated owner (or EVAL_USER_ID)")
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
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Retrieval top_k to pass as n_results on each chat request "
        "(default: None, so /api/chat/ falls back to its own default of 8)",
    )
    parser.add_argument(
        "--history-db",
        default="evals/eval_history.db",
        help="Path to the local SQLite evaluation-history database "
        "(default: evals/eval_history.db)",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Optional free-form label to attach to this run in the history db "
        "(e.g. 'movie-2-after-context-fix')",
    )
    parser.add_argument(
        "--no-save-history",
        action="store_true",
        help="Skip saving this run to the history db",
    )
    parser.add_argument(
        "--index-config",
        default=None,
        help="Optional free-form tag identifying the retrieval/index configuration "
        "in use, recorded on the history db run row for later comparison",
    )
    args = parser.parse_args()
    if not args.base_url or not args.user_id or not os.environ.get("EVAL_AUTH_TOKEN"):
        print("Set EVAL_BASE_URL, EVAL_USER_ID and EVAL_AUTH_TOKEN before evaluating chat")
        return 1
    if args.top_k is not None and args.top_k <= 0:
        print("--top-k must be positive")
        return 1

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

    if any(case["user_id"] != args.user_id for case in cases):
        print("Every case must belong to the explicit evaluation owner")
        return 1

    client = None
    try:
        client = _AuthenticatedHTTPClient(
            args.base_url, os.environ["EVAL_AUTH_TOKEN"],
            os.environ.get("EVAL_AUTH_REFRESH_TOKEN"),
        )
        client.verify_owner(args.user_id)
        results = [run_case(case, client, args.provider, args.top_k) for case in cases]
    except ValueError as error:
        print(str(error))
        return 1
    except Exception as error:
        print(f"Session verification failed ({type(error).__name__})")
        return 1
    finally:
        if client is not None:
            client.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)

    run_id = None
    if not args.no_save_history:
        try:
            effective_provider = _get_effective_provider(results, args.provider)
            model = os.environ.get(_PROVIDER_MODEL_ENV.get(effective_provider, ""))
            run_record = eval_history_db.build_run_record(
                results,
                label=args.run_label,
                git_commit=_get_git_commit(),
                case_file=args.cases,
                cases=cases,
                provider=effective_provider,
                model=model,
                index_config=args.index_config,
                top_k=args.top_k,
            )
            run_id = eval_history_db.save_run(args.history_db, run_record, results)
        except Exception as e:
            print(f"[WARN] Failed to save eval history: {e}")

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
    if run_id is not None:
        print(f"Eval run saved to history db: id={run_id} ({args.history_db})")

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
            print(f"Required terms:      {case.get('required_terms')}")
            print(f"Expected time range: {case.get('expected_time_range')}")
            if result["error"]:
                print(f"Error:               {result['error']}")
            print(f"Actual answer:\n{result['answer']}")
            print(f"Actual sources:\n{json.dumps(result['sources'], indent=2)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
