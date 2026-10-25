import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import settings
from evals.safety import require_remote_opt_in

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_retrieval_index.py"


class _Jobs:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "jobs"
        return _Jobs(self.rows)


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_MODE", False)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example-project.supabase.co")


def test_guard_refuses_without_flag_and_names_the_target(remote, capsys):
    with pytest.raises(SystemExit) as exit_info:
        require_remote_opt_in(False, "test action")

    assert exit_info.value.code == 2
    assert "example-project.supabase.co" in capsys.readouterr().out


def test_guard_allows_explicit_opt_in(remote):
    require_remote_opt_in(True, "test action")


def test_guard_skips_local_mode(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    require_remote_opt_in(False, "test action")


@pytest.fixture
def rebuild(monkeypatch, remote):
    from services import supabase_service, transcript_embedding_service, transcription_repository

    spec = importlib.util.spec_from_file_location("build_retrieval_index_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    calls = SimpleNamespace(chunks=[], audio=[], fail_for=set())
    jobs = [
        {"user_id": "owner-1", "video_hash": "video-1"},
        {"user_id": "owner-1", "video_hash": "video-1"},
        {"user_id": "owner-2", "video_hash": "video-2"},
        {"user_id": None, "video_hash": "ownerless"},
    ]

    def index_chunks(video_hash, _segments, user_id, **kwargs):
        if user_id in calls.fail_for:
            raise RuntimeError("embedding failed")
        calls.chunks.append((user_id, video_hash, kwargs))
        return 3

    def index_audio(video_hash, _segments, user_id, **kwargs):
        calls.audio.append((user_id, video_hash, kwargs))
        return 2

    monkeypatch.setattr(supabase_service, "supabase", lambda: _Client(jobs))
    monkeypatch.setattr(
        transcription_repository.transcription_repository, "get_transcription",
        lambda _video, _owner: {"transcription": {"segments": [{"text": "hello"}]}},
    )
    service = transcript_embedding_service.transcript_embedding_service
    monkeypatch.setattr(service, "index_transcript_chunks", index_chunks)
    monkeypatch.setattr(service, "index_audio_events", index_audio)
    return module, calls


def _run(monkeypatch, module, *argv, rebuild_all=True):
    monkeypatch.setattr(sys, "argv", ["script", *argv])
    return module.main(rebuild_all=rebuild_all)


def test_all_without_execute_lists_videos_and_writes_nothing(rebuild, monkeypatch, capsys):
    module, calls = rebuild

    assert _run(monkeypatch, module, "--all", "--allow-remote") == 0

    out = capsys.readouterr().out
    assert "Dry run: 2 video(s)" in out
    assert not calls.chunks and not calls.audio


def test_all_execute_rebuilds_each_completed_video_once(rebuild, monkeypatch):
    module, calls = rebuild

    assert _run(monkeypatch, module, "--all", "--execute", "--allow-remote") == 0

    assert [(owner, video) for owner, video, _ in calls.chunks] == [("owner-1", "video-1"), ("owner-2", "video-2")]
    assert all(kwargs["force_reindex"] is True for _, _, kwargs in calls.chunks)
    assert len(calls.audio) == 2


def test_all_keeps_going_after_a_failure_and_reports_it(rebuild, monkeypatch):
    module, calls = rebuild
    calls.fail_for.add("owner-1")

    assert _run(monkeypatch, module, "--all", "--execute", "--allow-remote") == 1

    assert [owner for owner, _, _ in calls.chunks] == ["owner-2"]


def test_rebuild_refuses_without_allow_remote(rebuild, monkeypatch):
    module, calls = rebuild

    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, module, "--all", "--execute")

    assert exit_info.value.code == 2
    assert not calls.chunks


def test_single_video_needs_owner_and_hash(rebuild, monkeypatch):
    module, _ = rebuild

    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, module, "--allow-remote")

    assert exit_info.value.code == 2


def test_build_script_has_no_all_mode(rebuild, monkeypatch):
    module, _ = rebuild

    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, module, "--all", "--allow-remote", rebuild_all=False)

    assert exit_info.value.code == 2


def test_eval_scripts_refuse_without_allow_remote(remote, monkeypatch, tmp_path):
    from evals.evaluate_retrieval import main as evaluate_retrieval_main
    from evals.generate_cases import main as generate_cases_main

    monkeypatch.setattr(sys, "argv", ["evaluate_retrieval.py", "--cases", str(tmp_path / "cases.json")])
    with pytest.raises(SystemExit) as retrieval_exit:
        evaluate_retrieval_main()

    monkeypatch.setattr(sys, "argv", ["generate_cases.py", "--video-hash", "hash-1", "--user-id", "user-1"])
    with pytest.raises(SystemExit) as generate_exit:
        generate_cases_main()

    assert retrieval_exit.value.code == 2 and generate_exit.value.code == 2
