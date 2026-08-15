import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.transcription_repository import TranscriptionRepository


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _value):
        return self

    def execute(self):
        matches = [
            row for row in self.rows
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        return SimpleNamespace(data=matches)


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "jobs"
        return _Query(self.rows)


def test_owned_transcription_isolated_by_user(monkeypatch):
    rows = [
        {
            "id": "job-a",
            "user_id": "user-a",
            "video_hash": "same-hash",
            "status": "completed",
            "result_json": {"transcription": {"segments": [{"text": "private-a"}]}},
        },
        {
            "id": "job-b",
            "user_id": "user-b",
            "video_hash": "same-hash",
            "status": "completed",
            "result_json": {"transcription": {"segments": [{"text": "private-b"}]}},
        },
    ]
    repository = TranscriptionRepository(lambda: _Client(rows))
    result = repository.get_transcription("same-hash", "user-b")

    assert result["user_id"] == "user-b"
    assert result["transcription"]["segments"][0]["text"] == "private-b"


def test_diagnostics_routes_require_admin_and_do_not_expose_token_material():
    source = (Path(__file__).parents[1] / "routers" / "diagnostics.py").read_text()
    tree = ast.parse(source)
    endpoint_names = {
        "check_diarization_status",
        "check_audio_analysis_status",
        "check_system_status",
    }
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in endpoint_names:
        decorators = {ast.unparse(item) for item in functions[name].decorator_list}
        assert "require_admin" in decorators

    assert "token_prefix" not in source
    assert "get_speaker_diarizer(" not in source
    assert "get_audio_analyzer(" not in source


def test_speaker_recognition_never_logs_token_prefix():
    source = (Path(__file__).parents[1] / "speaker_recognition.py").read_text()
    assert "Using token" not in source
    assert "hf_token[:" not in source


def test_hash_resources_fail_closed_for_null_owner(monkeypatch):
    rows = [
        {"video_hash": "hash", "user_id": "user-a"},
        {"video_hash": "hash", "user_id": None},
    ]
    repository = TranscriptionRepository(lambda: _Client(rows))
    assert not repository.hash_resources_are_owner_exclusive("hash", "user-a")


def test_legacy_transcription_routes_are_absent():
    source = (Path(__file__).parents[1] / "routers" / "transcription.py").read_text()
    for symbol in (
        '"/transcribe/"',
        '"/transcribe_local/"',
        '"/transcribe_local_stream/"',
        "transcribe_video",
        "transcribe_local",
        "transcribe_local_stream",
        "transcribe_gcs_stream",
    ):
        assert symbol not in source


def test_face_service_rejects_arbitrary_http_sources():
    from services.face_service import FaceService

    assert FaceService()._download_image_to_temp("https://attacker.example/internal") is None


def test_face_tag_source_rejects_url_not_in_owned_transcript(monkeypatch):
    module_path = Path(__file__).parents[1] / "routers" / "face_tags.py"
    spec = importlib.util.spec_from_file_location("test_face_tags_module", module_path)
    face_tags = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(face_tags)

    monkeypatch.setattr(
        face_tags.transcription_repository,
        "get_transcription",
        lambda _video_hash, _user_id: {
            "transcription": {
                "segments": [{
                    "screenshot_url": (
                        "https://storage.googleapis.com/ai-subs-uploads/"
                        "screenshots/video-a/1.0.jpg?X-Goog-Signature=owned"
                    )
                }]
            }
        },
    )
    monkeypatch.setattr(
        face_tags.transcription_repository,
        "hash_resources_are_owner_exclusive",
        lambda *_args: True,
    )
    request = SimpleNamespace(state=SimpleNamespace(profile={"id": "user-a"}))

    with pytest.raises(HTTPException) as exc:
        face_tags._owned_screenshot_source(
            request,
            "video-a",
            "https://attacker.example/metadata",
        )

    assert exc.value.status_code == 400
