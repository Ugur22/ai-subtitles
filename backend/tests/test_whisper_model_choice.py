from pathlib import Path

import pytest
from pydantic import ValidationError

import dependencies
from whisper_models import WHISPER_MODEL_CHOICES
from routers.jobs import JobSubmitRequest

MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "migrations"
_SUBMIT = dict(filename="a.mp4", gcs_path="uploads/u/a.mp4", file_size_bytes=1, video_hash="0" * 64)


def test_jobs_default_to_large_v3_and_reject_unknown_models():
    assert JobSubmitRequest(**_SUBMIT).model == "large-v3"
    assert JobSubmitRequest(**_SUBMIT, model="turbo").model == "turbo"
    with pytest.raises(ValidationError):
        JobSubmitRequest(**_SUBMIT, model="tiny")


def test_choice_resolves_to_a_baked_repo_except_in_local_mode(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "LOCAL_MODE", False)
    assert dependencies.resolve_whisper_model(None) == WHISPER_MODEL_CHOICES["large-v3"]
    assert dependencies.resolve_whisper_model("turbo") == WHISPER_MODEL_CHOICES["turbo"]

    monkeypatch.setattr(dependencies.settings, "LOCAL_MODE", True)
    monkeypatch.setattr(dependencies.settings, "FASTWHISPER_MODEL", "small")
    assert dependencies.resolve_whisper_model("turbo") == "small"


def test_asking_for_another_model_replaces_the_loaded_one(monkeypatch):
    loaded = []
    monkeypatch.setattr(dependencies, "WhisperModel", lambda name, **kwargs: loaded.append(name) or name)
    monkeypatch.setattr(dependencies, "_whisper_model", None)
    monkeypatch.setattr(dependencies, "_whisper_model_name", None)

    assert dependencies.get_whisper_model("a") == "a"
    assert dependencies.get_whisper_model("a") == "a"
    assert dependencies.get_whisper_model("b") == "b"
    assert loaded == ["a", "b"]


def test_dedup_only_returns_a_job_transcribed_with_the_same_model():
    sql = (MIGRATIONS / "024_job_dedup_by_model.sql").read_text(encoding="utf-8")
    dedup = sql[sql.index("SELECT * INTO v_existing"):sql.index("IF FOUND THEN")]
    assert "COALESCE(params->>'model', 'large-v3') = COALESCE(p_params->>'model', 'large-v3')" in dedup
    rollback = (MIGRATIONS / "024_job_dedup_by_model_rollback.sql").read_text(encoding="utf-8")
    assert "params->>'model'" not in rollback
    assert "DELETE FROM public.schema_migrations WHERE version = '024';" in rollback
