"""
Pure unit tests for evals/evaluate_chat.py's standalone scoring functions and
validate_case -- no network, no LLM calls, no FastAPI TestClient, no
LOCAL_MODE. These functions are deliberately dependency-free so they can be
tested in isolation from the real chat endpoint.

Run: python -m pytest tests/test_evaluate_chat.py -q  (from backend/)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.evaluate_chat import (  # noqa: E402
    answer_terms_ok,
    citation_overlap,
    forbidden_claims_ok,
    validate_case,
)


def _case(**overrides):
    base = {
        "id": "case",
        "video_hash": "hash-1",
        "user_id": "user-1",
        "question": "why?",
        "expected_answer": "because reasons",
        "required_terms": ["reasons"],
        "expected_time_range": {"start": 100.0, "end": 110.0},
    }
    base.update(overrides)
    return base


# --- citation_overlap ---------------------------------------------------


def test_citation_overlap_true_when_source_fully_inside_expected_range():
    sources = [{"start": 102.0, "end": 105.0}]
    assert citation_overlap(sources, {"start": 100.0, "end": 110.0}) is True


def test_citation_overlap_true_when_source_partially_overlaps():
    sources = [{"start": 95.0, "end": 101.0}]
    assert citation_overlap(sources, {"start": 100.0, "end": 110.0}) is True


def test_citation_overlap_true_when_ranges_only_touch_at_edge():
    sources = [{"start": 90.0, "end": 100.0}]
    assert citation_overlap(sources, {"start": 100.0, "end": 110.0}) is True


def test_citation_overlap_false_when_ranges_do_not_overlap():
    sources = [{"start": 200.0, "end": 210.0}]
    assert citation_overlap(sources, {"start": 100.0, "end": 110.0}) is False


def test_citation_overlap_false_when_no_sources():
    assert citation_overlap([], {"start": 100.0, "end": 110.0}) is False


def test_citation_overlap_true_if_any_of_multiple_sources_overlaps():
    sources = [{"start": 0.0, "end": 1.0}, {"start": 105.0, "end": 106.0}]
    assert citation_overlap(sources, {"start": 100.0, "end": 110.0}) is True


def test_citation_overlap_ignores_sources_missing_start_or_end():
    sources = [{"start": None, "end": None}, {"start": 105.0, "end": 106.0}]
    assert citation_overlap(sources, {"start": 100.0, "end": 110.0}) is True


# --- answer_terms_ok ------------------------------------------------------


def test_answer_terms_ok_true_when_all_required_terms_present():
    answer = "Trust me, I saw you. I didn't see you at first."
    assert answer_terms_ok(answer, ["saw you", "trust me"]) is True


def test_answer_terms_ok_false_when_one_required_term_missing():
    answer = "Because people feel sorry for me."
    assert answer_terms_ok(answer, ["sorry", "differently"]) is False


def test_answer_terms_ok_false_when_answer_is_unrelated():
    answer = "The weather in the scene looks cold and snowy."
    assert answer_terms_ok(answer, ["sorry", "differently"]) is False


def test_answer_terms_ok_true_when_required_terms_is_empty():
    assert answer_terms_ok("anything at all", []) is True


def test_answer_terms_ok_case_insensitive():
    answer = "TRUFFLE was discovered by ACCIDENT, apparently."
    assert answer_terms_ok(answer, ["accident", "truffle"]) is True


# --- forbidden_claims_ok ---------------------------------------------------


def test_forbidden_claims_ok_true_when_list_is_empty():
    assert forbidden_claims_ok("any answer text", []) is True


def test_forbidden_claims_ok_true_when_forbidden_terms_absent():
    assert forbidden_claims_ok("a scene about trust and honesty", ["cafeteria", "girlfriend"]) is True


def test_forbidden_claims_ok_false_when_forbidden_term_present():
    assert forbidden_claims_ok("a girlfriend confrontation scene", ["girlfriend"]) is False


def test_forbidden_claims_ok_case_insensitive():
    assert forbidden_claims_ok("A CAFETERIA scene", ["cafeteria"]) is False


# --- validate_case ----------------------------------------------------------


def test_valid_case_has_no_validation_problems():
    assert validate_case(_case()) == []


def test_valid_case_with_what_must_not_be_claimed_has_no_problems():
    assert validate_case(_case(what_must_not_be_claimed=["foo", "bar"])) == []


def test_missing_field_fails_validation():
    case = _case()
    del case["expected_answer"]
    problems = validate_case(case)
    assert any("expected_answer" in p for p in problems)


def test_placeholder_field_fails_validation():
    problems = validate_case(_case(question="REPLACE_ME"))
    assert any("REPLACE_ME" in p for p in problems)


def test_non_dict_case_fails_validation():
    problems = validate_case(["not", "a", "dict"])
    assert len(problems) == 1


def test_expected_time_range_not_a_dict_fails_validation():
    problems = validate_case(_case(expected_time_range=[100, 110]))
    assert any("expected_time_range" in p for p in problems)


def test_expected_time_range_missing_key_fails_validation():
    problems = validate_case(_case(expected_time_range={"start": 100.0}))
    assert any("end" in p for p in problems)


def test_expected_time_range_non_numeric_value_fails_validation():
    problems = validate_case(_case(expected_time_range={"start": "soon", "end": 110.0}))
    assert any("expected_time_range.start" in p for p in problems)


def test_what_must_not_be_claimed_wrong_type_fails_validation():
    problems = validate_case(_case(what_must_not_be_claimed="not a list"))
    assert any("what_must_not_be_claimed" in p for p in problems)


def test_missing_required_terms_fails_validation():
    case = _case()
    del case["required_terms"]
    problems = validate_case(case)
    assert any("required_terms" in p for p in problems)


def test_empty_required_terms_fails_validation():
    problems = validate_case(_case(required_terms=[]))
    assert any("required_terms" in p for p in problems)


def test_required_terms_wrong_type_fails_validation():
    problems = validate_case(_case(required_terms="not a list"))
    assert any("required_terms" in p for p in problems)


def test_required_terms_with_blank_string_fails_validation():
    problems = validate_case(_case(required_terms=["ok", "  "]))
    assert any("required_terms" in p for p in problems)
