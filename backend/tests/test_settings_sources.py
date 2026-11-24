"""Settings sources: process environment, then backend/.env, then field defaults."""
from pathlib import Path

import pytest

import config
from config import Settings


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("CORS_ORIGINS", "LOCAL_MODE", "MAX_SPEAKERS", "GCS_BUCKET_NAME"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_env_file_is_resolved_from_config_not_the_working_directory():
    assert config.ENV_FILE == Path(config.__file__).resolve().parent / ".env"
    assert Settings.model_config["env_file"] == config.ENV_FILE


def test_defaults_apply_without_env_or_env_file(clean_env):
    s = Settings(_env_file=None)
    assert s.LOCAL_MODE is False
    assert s.MAX_SPEAKERS == 0
    assert s.CORS_ORIGINS == ["http://localhost:5173"]


def test_env_file_values_are_read_and_process_env_wins(clean_env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'LOCAL_MODE=true\nMAX_SPEAKERS=4\nGCS_BUCKET_NAME=from-file\n'
        'CORS_ORIGINS=["https://file.example"]\n',
        encoding="utf-8",
    )
    clean_env.setenv("GCS_BUCKET_NAME", "from-env")

    s = Settings(_env_file=env_file)

    assert s.LOCAL_MODE is True
    assert s.MAX_SPEAKERS == 4
    assert s.GCS_BUCKET_NAME == "from-env"
    assert s.CORS_ORIGINS == ["https://file.example"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('["https://a.example","https://b.example"]', ["https://a.example", "https://b.example"]),
        ('"https://a.example"', ["http://localhost:5173"]),
        ("not json", ["http://localhost:5173"]),
        ("", ["http://localhost:5173"]),
    ],
)
def test_cors_origins_from_environment(clean_env, raw, expected):
    clean_env.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).CORS_ORIGINS == expected
