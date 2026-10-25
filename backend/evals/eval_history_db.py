"""
Local SQLite history store for `evaluate_chat.py` runs.

Turns individual chat-eval runs into a queryable history so models,
providers, top_k settings, and movies can be compared over time -- pass/fail
rates, latency, provider errors, and regressions. This is local developer
tooling only: it stores synthetic eval-case data (questions, generated
answers, citations), never real user conversations, API keys, or env dumps.

Two tables:
    eval_runs         -- one row per `evaluate_chat.py` invocation
    eval_case_results  -- one row per case within a run (FK -> eval_runs.id)

Usage:
    run_id = save_run("evals/eval_history.db", run_record, results)
    conn = get_connection("evals/eval_history.db")
    latest = get_latest_run(conn)
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    label TEXT,
    git_commit TEXT,
    case_file TEXT NOT NULL,
    video_hash TEXT,
    provider TEXT,
    model TEXT,
    index_config TEXT,
    top_k INTEGER,
    total_cases INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    answer_correctness_rate REAL NOT NULL,
    citation_correctness_rate REAL NOT NULL,
    total_duration_seconds REAL NOT NULL,
    average_duration_seconds REAL NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    estimated_cost REAL
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created_at ON eval_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_eval_runs_case_file ON eval_runs(case_file);

CREATE TABLE IF NOT EXISTS eval_case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('passed', 'failed', 'error')),
    terms_ok INTEGER,
    citation_ok INTEGER,
    forbidden_ok INTEGER,
    duration_seconds REAL,
    generated_answer TEXT,
    citations TEXT,
    failure_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_case_results_run_id ON eval_case_results(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_case_results_case_id ON eval_case_results(case_id);
CREATE INDEX IF NOT EXISTS idx_eval_case_results_status ON eval_case_results(status);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_SQL)
    return conn


# ---------------------------------------------------------------------------
# Pure helpers: mapping a run_case() result dict onto DB rows.
# ---------------------------------------------------------------------------

def classify_status(result: Dict[str, Any]) -> str:
    """'error' on transport/HTTP failure, else 'passed'/'failed' from the assertion result."""
    if result.get("error"):
        return "error"
    return "passed" if result.get("passed") else "failed"


def build_failure_reason(result: Dict[str, Any]) -> Optional[str]:
    """None when passed; the transport error string on error; else which checks failed."""
    status = classify_status(result)
    if status == "passed":
        return None
    if status == "error":
        return result.get("error")
    failed_checks = [
        name
        for name, ok_key in (
            ("citation_ok", "citation_ok"),
            ("terms_ok", "terms_ok"),
            ("forbidden_ok", "forbidden_ok"),
        )
        if not result.get(ok_key)
    ]
    return "; ".join(f"{name} failed" for name in failed_checks) or None


def case_result_to_row(result: Dict[str, Any]) -> Dict[str, Any]:
    """Map one run_case() result dict to an eval_case_results row dict (run_id added by caller)."""
    return {
        "case_id": result["id"],
        "question": result["question"],
        "status": classify_status(result),
        "terms_ok": result.get("terms_ok"),
        "citation_ok": result.get("citation_ok"),
        "forbidden_ok": result.get("forbidden_ok"),
        "duration_seconds": result.get("duration_seconds"),
        "generated_answer": result.get("answer"),
        "citations": json.dumps(result["sources"]) if result.get("sources") is not None else None,
        "failure_reason": build_failure_reason(result),
    }


def build_run_record(
    results: List[Dict[str, Any]],
    *,
    label: Optional[str],
    git_commit: Optional[str],
    case_file: str,
    cases: List[Dict[str, Any]],
    provider: Optional[str],
    model: Optional[str],
    index_config: Optional[str],
    top_k: Optional[int],
) -> Dict[str, Any]:
    """Pure aggregation of a completed run into an eval_runs row dict.

    Deliberately mirrors the pass/fail/rate math already printed by
    evaluate_chat.py's main(), but additionally separates 'error' out of
    'failed' via classify_status (main()'s own `failed` counter conflates
    the two, since a transport error also sets passed=False).
    """
    total_cases = len(results)
    passed = sum(1 for r in results if classify_status(r) == "passed")
    failed = sum(1 for r in results if classify_status(r) == "failed")
    errors = sum(1 for r in results if classify_status(r) == "error")

    terms_rate = (sum(1 for r in results if r.get("terms_ok")) / total_cases * 100) if total_cases else 0.0
    citation_rate = (sum(1 for r in results if r.get("citation_ok")) / total_cases * 100) if total_cases else 0.0

    durations = [r.get("duration_seconds") or 0.0 for r in results]
    total_duration = sum(durations)
    average_duration = (total_duration / total_cases) if total_cases else 0.0

    video_hashes = {c.get("video_hash") for c in cases if isinstance(c, dict) and c.get("video_hash")}
    if len(video_hashes) == 1:
        video_hash = next(iter(video_hashes))
    elif len(video_hashes) > 1:
        video_hash = "multiple"
    else:
        video_hash = None

    return {
        "label": label,
        "git_commit": git_commit,
        "case_file": case_file,
        "video_hash": video_hash,
        "provider": provider,
        "model": model,
        "index_config": index_config,
        "top_k": top_k,
        "total_cases": total_cases,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "answer_correctness_rate": terms_rate,
        "citation_correctness_rate": citation_rate,
        "total_duration_seconds": total_duration,
        "average_duration_seconds": average_duration,
        "prompt_tokens": None,
        "completion_tokens": None,
        "estimated_cost": None,
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

_RUN_COLUMNS = (
    "label", "git_commit", "case_file", "video_hash", "provider", "model",
    "index_config", "top_k", "total_cases", "passed", "failed", "errors",
    "answer_correctness_rate", "citation_correctness_rate",
    "total_duration_seconds", "average_duration_seconds",
    "prompt_tokens", "completion_tokens", "estimated_cost",
)

_CASE_COLUMNS = (
    "run_id", "case_id", "question", "status", "terms_ok", "citation_ok",
    "forbidden_ok", "duration_seconds", "generated_answer", "citations",
    "failure_reason",
)


def save_run(db_path: str, run_record: Dict[str, Any], results: List[Dict[str, Any]]) -> int:
    """Persist one run + all its case results atomically. Returns the new run_id.

    Uses sqlite3's connection-as-context-manager transaction: commits on
    normal exit, rolls back automatically if any statement raises -- so a
    bad case row can never leave a run row with no case rows (or vice versa).
    Raises on failure after rollback; callers should decide whether to warn
    or abort.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                f"INSERT INTO eval_runs ({', '.join(_RUN_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _RUN_COLUMNS)})",
                [run_record[col] for col in _RUN_COLUMNS],
            )
            run_id = cur.lastrowid

            case_rows = []
            for result in results:
                row = case_result_to_row(result)
                row["run_id"] = run_id
                case_rows.append([row[col] for col in _CASE_COLUMNS])

            conn.executemany(
                f"INSERT INTO eval_case_results ({', '.join(_CASE_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _CASE_COLUMNS)})",
                case_rows,
            )
        return run_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reading / single-run lookups
# ---------------------------------------------------------------------------

def get_run(conn: sqlite3.Connection, run_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", [run_id]).fetchone()
    return dict(row) if row else None


def get_latest_run(conn: sqlite3.Connection, case_file: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if case_file:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE case_file = ? ORDER BY id DESC LIMIT 1",
            [case_file],
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_case_results(conn: sqlite3.Connection, run_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM eval_case_results WHERE run_id = ? ORDER BY case_id", [run_id]
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# SQL analysis -- named, readable queries across all runs.
# ---------------------------------------------------------------------------

def cases_failing_most_frequently(conn: sqlite3.Connection, limit: int = 10) -> List[Dict[str, Any]]:
    """Which cases fail or error most often, across every run recorded so far."""
    query = """
        SELECT
            case_id,
            question,
            COUNT(*) AS total_runs,
            SUM(CASE WHEN status != 'passed' THEN 1 ELSE 0 END) AS failure_count,
            ROUND(
                100.0 * SUM(CASE WHEN status != 'passed' THEN 1 ELSE 0 END) / COUNT(*), 1
            ) AS failure_rate_pct
        FROM eval_case_results
        GROUP BY case_id
        ORDER BY failure_count DESC, failure_rate_pct DESC
        LIMIT ?
    """
    rows = conn.execute(query, [limit]).fetchall()
    return [dict(row) for row in rows]


def results_by_movie(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Pass/fail/error totals and correctness rates grouped by movie (video_hash)."""
    query = """
        SELECT
            video_hash,
            COUNT(*) AS total_runs,
            SUM(passed) AS total_passed,
            SUM(failed) AS total_failed,
            SUM(errors) AS total_errors,
            ROUND(AVG(answer_correctness_rate), 1) AS avg_answer_correctness_rate,
            ROUND(AVG(citation_correctness_rate), 1) AS avg_citation_correctness_rate
        FROM eval_runs
        GROUP BY video_hash
        ORDER BY total_runs DESC
    """
    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def results_by_model_provider(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Pass/fail/error totals and correctness rates grouped by provider + model."""
    query = """
        SELECT
            provider,
            model,
            COUNT(*) AS total_runs,
            SUM(passed) AS total_passed,
            SUM(failed) AS total_failed,
            SUM(errors) AS total_errors,
            ROUND(AVG(answer_correctness_rate), 1) AS avg_answer_correctness_rate,
            ROUND(AVG(citation_correctness_rate), 1) AS avg_citation_correctness_rate
        FROM eval_runs
        GROUP BY provider, model
        ORDER BY total_runs DESC
    """
    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def average_latency_by_model(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Average per-case latency, grouped by provider + model, fastest first."""
    query = """
        SELECT
            provider,
            model,
            ROUND(AVG(average_duration_seconds), 3) AS avg_latency_seconds,
            COUNT(*) AS run_count
        FROM eval_runs
        GROUP BY provider, model
        ORDER BY avg_latency_seconds ASC
    """
    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def provider_error_rate(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Share of cases that ended in a transport/HTTP error (not an assertion failure), per provider."""
    query = """
        SELECT
            provider,
            SUM(errors) AS total_errors,
            SUM(total_cases) AS total_cases,
            ROUND(100.0 * SUM(errors) / NULLIF(SUM(total_cases), 0), 2) AS error_rate_pct
        FROM eval_runs
        GROUP BY provider
        ORDER BY error_rate_pct DESC
    """
    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def compare_runs(conn: sqlite3.Connection, baseline_id: int, candidate_id: int) -> Dict[str, Any]:
    """Compare two runs case-by-case.

    Provider errors are tracked separately from regressed_cases on purpose:
    a case flipping to/from 'error' is an infrastructure/transport signal,
    not an answer-quality regression, so it must never inflate the
    regression count.
    """
    baseline_run = get_run(conn, baseline_id)
    candidate_run = get_run(conn, candidate_id)
    if baseline_run is None:
        raise ValueError(f"No eval_runs row with id={baseline_id}")
    if candidate_run is None:
        raise ValueError(f"No eval_runs row with id={candidate_id}")

    baseline_cases = {row["case_id"]: row for row in get_case_results(conn, baseline_id)}
    candidate_cases = {row["case_id"]: row for row in get_case_results(conn, candidate_id)}

    fixed_cases: List[Dict[str, Any]] = []
    regressed_cases: List[Dict[str, Any]] = []
    new_provider_errors: List[Dict[str, Any]] = []
    resolved_provider_errors: List[Dict[str, Any]] = []

    for case_id, candidate_row in candidate_cases.items():
        baseline_row = baseline_cases.get(case_id)
        if baseline_row is None:
            continue

        base_status = baseline_row["status"]
        cand_status = candidate_row["status"]
        if base_status == cand_status:
            continue

        entry = {
            "case_id": case_id,
            "question": candidate_row["question"],
            "baseline_status": base_status,
            "candidate_status": cand_status,
        }

        if cand_status == "error" and base_status != "error":
            new_provider_errors.append(entry)
        elif base_status == "error" and cand_status != "error":
            resolved_provider_errors.append(entry)
        elif base_status in ("failed", "error") and cand_status == "passed":
            fixed_cases.append(entry)
        elif base_status == "passed" and cand_status == "failed":
            regressed_cases.append(entry)

    def _delta(field: str) -> Optional[float]:
        b, c = baseline_run.get(field), candidate_run.get(field)
        if b is None or c is None:
            return None
        return c - b

    return {
        "baseline": baseline_run,
        "candidate": candidate_run,
        "fixed_cases": fixed_cases,
        "regressed_cases": regressed_cases,
        "new_provider_errors": new_provider_errors,
        "resolved_provider_errors": resolved_provider_errors,
        "prompt_tokens_delta": _delta("prompt_tokens"),
        "completion_tokens_delta": _delta("completion_tokens"),
        "estimated_cost_delta": _delta("estimated_cost"),
    }
