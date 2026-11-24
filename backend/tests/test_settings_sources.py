"""Settings sources: process environment, then backend/.env, then field defaults."""
from pathlib import Path

import pytest

import config
from config import Settings


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "CORS_ORIGINS", "LOCAL_MODE", "MAX_SPEAKERS", "GCS_BUCKET_NAME",
        "ENVIRONMENT", "FASTWHISPER_DEVICE", "FASTWHISPER_COMPUTE_TYPE", "DEEPSEEK_BASE_URL",
    ):
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


# Reads that used os.environ and only saw backend/.env when llm_providers had already
# called load_dotenv(). Each case builds a fresh Settings: assigning a field on the shared
# instance would mark it as explicitly set for the rest of the session.


@pytest.mark.parametrize(
    "file_text, env_value, expected",
    [
        ("", None, False),
        ("ENVIRONMENT=production\n", None, True),
        ("ENVIRONMENT=production\n", "development", False),
        ("", "production", True),
    ],
)
def test_is_production_reads_env_file_and_env(clean_env, tmp_path, file_text, env_value, expected):
    env_file = tmp_path / ".env"
    env_file.write_text(file_text, encoding="utf-8")
    if env_value is not None:
        clean_env.setenv("ENVIRONMENT", env_value)
    assert Settings(_env_file=env_file).is_production is expected


@pytest.mark.parametrize(
    "file_text, env_value, expected",
    [
        ("FASTWHISPER_DEVICE=cuda\n", None, "float16"),
        ("FASTWHISPER_DEVICE=cuda\nFASTWHISPER_COMPUTE_TYPE=int8\n", None, "int8"),
        ("FASTWHISPER_DEVICE=cuda\n", "float16", "float16"),
        ("FASTWHISPER_DEVICE=cuda\nFASTWHISPER_COMPUTE_TYPE=int8\n", "int8_float16", "int8_float16"),
        ("", None, "int8"),
    ],
)
def test_whisper_compute_type_honours_env_file(clean_env, tmp_path, file_text, env_value, expected):
    import dependencies

    env_file = tmp_path / ".env"
    env_file.write_text(file_text, encoding="utf-8")
    if env_value is not None:
        clean_env.setenv("FASTWHISPER_COMPUTE_TYPE", env_value)
    clean_env.setattr(dependencies, "settings", Settings(_env_file=env_file))
    assert dependencies.resolve_whisper_compute_type() == expected


def test_deepseek_model_listing_uses_settings_base_url(clean_env, tmp_path):
    import asyncio

    import httpx

    from services import model_catalog

    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_BASE_URL=https://deepseek.example/v1/\n", encoding="utf-8")
    clean_env.setattr(model_catalog, "settings", Settings(_env_file=env_file))
    clean_env.setattr(model_catalog, "_cache", {})
    clean_env.setattr(model_catalog, "_failures", {})
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-pro"}]})

    real_client = httpx.AsyncClient
    clean_env.setattr(
        model_catalog.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )

    assert asyncio.run(model_catalog.list_models("deepseek", "sk-test")) == ["deepseek-v4-pro"]
    assert seen == ["https://deepseek.example/v1/models"]
