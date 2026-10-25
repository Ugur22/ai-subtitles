"""
Unit tests for evals/eval_history_db.py -- the local SQLite store for
evaluate_chat.py run history.

No network, no LLM calls, no real chat requests: every test builds fake
run_case()-shaped result dicts by hand and exercises the DB layer against a
throwaway SQLite file in a temp directory.

Run: python -m pytest tests/test_eval_history_db.py -q  (from backend/)
"""
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals"))

import eval_history_db  # noqa: E402


@pytest.fixture()
def db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test_eval_history.db")


def _result(case_id="c1", question="why?", passed=True, terms_ok=True, citation_ok=True,
            forbidden_ok=True, error=None, duration=1.0, answer="because", sources=None):
    return {
        "id": case_id,
        "question": question,
        "answer": None if error else answer,
        "sources": None if error else (sources if sources is not None else [{"start": 1.0, "end": 2.0}]),
        "provider_used": None if error else "groq",
        "duration_seconds": duration,
        "citation_ok": False if error else citation_ok,
        "terms_ok": False if error else terms_ok,
        "forbidden_ok": False if error else forbidden_ok,
        "passed": False if error else (terms_ok and citation_ok and forbidden_ok),
        "error": error,
    }


def _cases(video_hash="hash-1"):
    return [{"id": "c1", "video_hash": video_hash}, {"id": "c2", "video_hash": video_hash}]


def _run_record(results, cases=None, **overrides):
    base = eval_history_db.build_run_record(
        results,
        label="test-run",
        git_commit="abc123",
        case_file="evals/chat_cases.json",
        cases=cases if cases is not None else _cases(),
        provider="groq",
        model="llama-3.3-70b-versatile",
        index_config=None,
        top_k=8,
    )
    base.update(overrides)
    return base


# --- schema creation --------------------------------------------------------


def test_schema_creates_expected_tables_and_indexes(db_path):
    conn = eval_history_db.get_connection(db_path)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"eval_runs", "eval_case_results"} <= tables

        run_indexes = {row["name"] for row in conn.execute("PRAGMA index_list(eval_runs)").fetchall()}
        case_indexes = {row["name"] for row in conn.execute("PRAGMA index_list(eval_case_results)").fetchall()}
        assert any("case_file" in name for name in run_indexes) or run_indexes
        assert any("run_id" in name for name in case_indexes)
        assert any("status" in name for name in case_indexes)
    finally:
        conn.close()


# --- storing a complete run --------------------------------------------------


def test_save_run_stores_run_and_all_case_rows(db_path):
    results = [_result("c1", passed=True), _result("c2", passed=False, terms_ok=False)]
    run_record = _run_record(results)

    run_id = eval_history_db.save_run(db_path, run_record, results)

    conn = eval_history_db.get_connection(db_path)
    try:
        run = eval_history_db.get_run(conn, run_id)
        assert run["case_file"] == "evals/chat_cases.json"
        assert run["total_cases"] == 2
        assert run["passed"] == 1
        assert run["failed"] == 1
        assert run["errors"] == 0

        case_rows = eval_history_db.get_case_results(conn, run_id)
        assert {row["case_id"] for row in case_rows} == {"c1", "c2"}
        c1 = next(row for row in case_rows if row["case_id"] == "c1")
        assert c1["status"] == "passed"
        assert c1["generated_answer"] == "because"
        assert c1["citations"] == "[{\"start\": 1.0, \"end\": 2.0}]"
    finally:
        conn.close()


# --- run-to-case relationship / FK behavior ---------------------------------


def test_case_rows_reference_correct_run_id_and_cascade_on_delete(db_path):
    results_a = [_result("c1")]
    results_b = [_result("c1"), _result("c2")]
    run_a = eval_history_db.save_run(db_path, _run_record(results_a), results_a)
    run_b = eval_history_db.save_run(db_path, _run_record(results_b), results_b)

    conn = eval_history_db.get_connection(db_path)
    try:
        assert len(eval_history_db.get_case_results(conn, run_a)) == 1
        assert len(eval_history_db.get_case_results(conn, run_b)) == 2

        conn.execute("DELETE FROM eval_runs WHERE id = ?", [run_a])
        conn.commit()
        assert eval_history_db.get_case_results(conn, run_a) == []
        # Unrelated run's cases must survive the cascade.
        assert len(eval_history_db.get_case_results(conn, run_b)) == 2
    finally:
        conn.close()


# --- passed/failed/error separation -----------------------------------------


def test_classify_status_separates_error_from_failed():
    assert eval_history_db.classify_status(_result(passed=True)) == "passed"
    assert eval_history_db.classify_status(_result(passed=False, terms_ok=False)) == "failed"
    assert eval_history_db.classify_status(_result(error="HTTP 500: boom")) == "error"


def test_build_run_record_counts_are_correctly_separated():
    results = [
        _result("c1", passed=True),
        _result("c2", passed=False, citation_ok=False),
        _result("c3", error="HTTP 500: boom"),
    ]
    run_record = _run_record(results)
    assert run_record["total_cases"] == 3
    assert run_record["passed"] == 1
    assert run_record["failed"] == 1
    assert run_record["errors"] == 1


# --- comparing two runs -----------------------------------------------------


def test_compare_runs_reports_summary_diffs(db_path):
    baseline_results = [_result("c1", passed=True), _result("c2", passed=True)]
    candidate_results = [_result("c1", passed=True), _result("c2", passed=False, terms_ok=False)]

    baseline_id = eval_history_db.save_run(db_path, _run_record(baseline_results), baseline_results)
    candidate_id = eval_history_db.save_run(db_path, _run_record(candidate_results), candidate_results)

    conn = eval_history_db.get_connection(db_path)
    try:
        comparison = eval_history_db.compare_runs(conn, baseline_id, candidate_id)
        assert comparison["baseline"]["id"] == baseline_id
        assert comparison["candidate"]["id"] == candidate_id
        assert comparison["regressed_cases"][0]["case_id"] == "c2"
    finally:
        conn.close()


# --- detecting fixed and regressed cases ------------------------------------


def test_compare_runs_detects_fixed_and_regressed_cases(db_path):
    baseline_results = [
        _result("c1", passed=False, terms_ok=False),  # will be fixed
        _result("c2", passed=True),                    # will regress
        _result("c3", passed=True),                     # stays passed
    ]
    candidate_results = [
        _result("c1", passed=True),
        _result("c2", passed=False, citation_ok=False),
        _result("c3", passed=True),
    ]

    baseline_id = eval_history_db.save_run(db_path, _run_record(baseline_results), baseline_results)
    candidate_id = eval_history_db.save_run(db_path, _run_record(candidate_results), candidate_results)

    conn = eval_history_db.get_connection(db_path)
    try:
        comparison = eval_history_db.compare_runs(conn, baseline_id, candidate_id)
        assert [e["case_id"] for e in comparison["fixed_cases"]] == ["c1"]
        assert [e["case_id"] for e in comparison["regressed_cases"]] == ["c2"]
    finally:
        conn.close()


def test_compare_runs_treats_provider_error_transitions_separately_from_regressions(db_path):
    baseline_results = [_result("c1", passed=True), _result("c2", error="HTTP 500: boom")]
    candidate_results = [_result("c1", error="HTTP 500: boom"), _result("c2", passed=True)]

    baseline_id = eval_history_db.save_run(db_path, _run_record(baseline_results), baseline_results)
    candidate_id = eval_history_db.save_run(db_path, _run_record(candidate_results), candidate_results)

    conn = eval_history_db.get_connection(db_path)
    try:
        comparison = eval_history_db.compare_runs(conn, baseline_id, candidate_id)
        # c1 flipped passed -> error: a provider error, not a quality regression.
        assert [e["case_id"] for e in comparison["new_provider_errors"]] == ["c1"]
        # c2 flipped error -> passed: a resolved provider error, not a "fixed" quality case.
        assert [e["case_id"] for e in comparison["resolved_provider_errors"]] == ["c2"]
        assert comparison["regressed_cases"] == []
        assert comparison["fixed_cases"] == []
    finally:
        conn.close()


# --- missing optional token/cost fields --------------------------------------


def test_missing_token_and_cost_fields_are_stored_and_read_as_none(db_path):
    results = [_result("c1", passed=True)]
    run_record = _run_record(results)
    assert run_record["prompt_tokens"] is None
    assert run_record["completion_tokens"] is None
    assert run_record["estimated_cost"] is None

    run_id = eval_history_db.save_run(db_path, run_record, results)

    conn = eval_history_db.get_connection(db_path)
    try:
        run = eval_history_db.get_run(conn, run_id)
        assert run["prompt_tokens"] is None
        assert run["completion_tokens"] is None
        assert run["estimated_cost"] is None
    finally:
        conn.close()


def test_compare_runs_token_cost_deltas_are_none_when_unavailable(db_path):
    results = [_result("c1", passed=True)]
    baseline_id = eval_history_db.save_run(db_path, _run_record(results), results)
    candidate_id = eval_history_db.save_run(db_path, _run_record(results), results)

    conn = eval_history_db.get_connection(db_path)
    try:
        comparison = eval_history_db.compare_runs(conn, baseline_id, candidate_id)
        assert comparison["prompt_tokens_delta"] is None
        assert comparison["completion_tokens_delta"] is None
        assert comparison["estimated_cost_delta"] is None
    finally:
        conn.close()


# --- transaction rollback on failure -----------------------------------------


def test_save_run_rolls_back_entirely_when_a_case_row_is_invalid(db_path):
    results = [_result("c1", passed=True)]
    run_record = _run_record(results)

    # 'bogus' violates the eval_case_results.status CHECK constraint, so the
    # executemany() call inside save_run()'s transaction must raise and roll
    # back the eval_runs insert made just before it in the same transaction.
    bad_results = [dict(results[0])]
    bad_results[0]["passed"] = True
    bad_results[0]["error"] = None

    original_classify = eval_history_db.classify_status
    try:
        eval_history_db.classify_status = lambda result: "bogus"
        with pytest.raises(sqlite3.IntegrityError):
            eval_history_db.save_run(db_path, run_record, bad_results)
    finally:
        eval_history_db.classify_status = original_classify

    conn = eval_history_db.get_connection(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM eval_runs").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM eval_case_results").fetchone()["n"] == 0
    finally:
        conn.close()
