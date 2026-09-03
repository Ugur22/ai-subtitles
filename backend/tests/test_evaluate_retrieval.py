from unittest.mock import Mock

from evals.evaluate_retrieval import main, run_case, transcript_embedding_service, validate_case


def _case(**overrides):
    base = {
        "name": "case",
        "video_hash": "hash-1",
        "user_id": "user-1",
        "question": "why?",
        "expected_start_seconds": 100,
        "acceptable_window_seconds": 10,
    }
    base.update(overrides)
    return base


def _result(start):
    return {"metadata": {"start": start}}


def test_result_inside_window_passes(monkeypatch):
    monkeypatch.setattr(
        transcript_embedding_service, "search_transcript_chunks", Mock(return_value=[_result(105)])
    )
    result = run_case(_case(expected_start_seconds=100, acceptable_window_seconds=10), top_k=5)
    assert result["passed"] is True
    assert result["error"] is None


def test_result_outside_window_fails(monkeypatch):
    monkeypatch.setattr(
        transcript_embedding_service, "search_transcript_chunks", Mock(return_value=[_result(200)])
    )
    result = run_case(_case(expected_start_seconds=100, acceptable_window_seconds=10), top_k=5)
    assert result["passed"] is False


def test_one_valid_hit_among_multiple_results_passes(monkeypatch):
    monkeypatch.setattr(
        transcript_embedding_service,
        "search_transcript_chunks",
        Mock(return_value=[_result(500), _result(999), _result(101)]),
    )
    result = run_case(_case(expected_start_seconds=100, acceptable_window_seconds=10), top_k=5)
    assert result["passed"] is True


def test_placeholder_field_fails_validation():
    problems = validate_case(_case(video_hash="REPLACE_ME"))
    assert any("REPLACE_ME" in p for p in problems)


def test_missing_field_fails_validation():
    case = _case()
    del case["user_id"]
    problems = validate_case(case)
    assert any("user_id" in p for p in problems)


def test_valid_case_has_no_validation_problems():
    assert validate_case(_case()) == []


def test_retrieval_exception_does_not_prevent_later_cases(monkeypatch, tmp_path, capsys):
    def fake_search(video_hash, query, user_id, n_results=5):
        if video_hash == "broken":
            raise RuntimeError("Transcript chunk search failed")
        return [_result(100)]

    monkeypatch.setattr(transcript_embedding_service, "search_transcript_chunks", Mock(side_effect=fake_search))

    broken = _case(name="broken-case", video_hash="broken")
    ok = _case(name="ok-case")

    broken_result = run_case(broken, top_k=5)
    ok_result = run_case(ok, top_k=5)

    assert broken_result["passed"] is False
    assert "Transcript chunk search failed" in broken_result["error"]
    assert ok_result["passed"] is True
    assert ok_result["error"] is None


def test_main_exits_nonzero_when_a_case_fails(monkeypatch, tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"name": "fails", "video_hash": "hash-1", "user_id": "user-1", '
        '"question": "why?", "expected_start_seconds": 100, "acceptable_window_seconds": 10}]'
    )
    monkeypatch.setattr(
        transcript_embedding_service, "search_transcript_chunks", Mock(return_value=[_result(9999)])
    )
    monkeypatch.setattr("sys.argv", ["evaluate_retrieval.py", "--cases", str(cases_path)])

    assert main() == 1


def test_main_exits_zero_when_all_cases_pass(monkeypatch, tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"name": "passes", "video_hash": "hash-1", "user_id": "user-1", '
        '"question": "why?", "expected_start_seconds": 100, "acceptable_window_seconds": 10}]'
    )
    monkeypatch.setattr(
        transcript_embedding_service, "search_transcript_chunks", Mock(return_value=[_result(100)])
    )
    monkeypatch.setattr("sys.argv", ["evaluate_retrieval.py", "--cases", str(cases_path)])

    assert main() == 0


def test_main_fails_fast_on_invalid_case_without_calling_retrieval(monkeypatch, tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"name": "bad", "video_hash": "REPLACE_ME", "user_id": "user-1", '
        '"question": "why?", "expected_start_seconds": 100, "acceptable_window_seconds": 10}]'
    )
    search_mock = Mock(return_value=[_result(100)])
    monkeypatch.setattr(transcript_embedding_service, "search_transcript_chunks", search_mock)
    monkeypatch.setattr("sys.argv", ["evaluate_retrieval.py", "--cases", str(cases_path)])

    assert main() == 1
    search_mock.assert_not_called()
