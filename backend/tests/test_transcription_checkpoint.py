from pathlib import Path
from types import SimpleNamespace

import pytest

from checkpoint_fakes import FakeCache
from config import settings
from middleware import quota
from services import job_queue_service
from services.job_queue_service import JobQueueService
from services.transcription_checkpoint import (
    BudgetedCheckpoint,
    ContinuationRequested,
    StageCheckpoint,
    TRANSCRIPTION_CHUNK_SECONDS,
    TRANSCRIPTION_PREFIX,
    TimeBudget,
    merge_chunks,
    resolve_budget_seconds,
    settings_key,
    stage_prefix,
)

BACKEND = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _run_transcription(cache, clock, budget_seconds, total_chunks, seconds_per_chunk, key="k"):
    """Mirror of the worker's chunk loop: returns (chunk indexes transcribed, merged or None)."""
    budget = TimeBudget(budget_seconds, started_at=clock.now, clock=clock)
    checkpoint = BudgetedCheckpoint(
        cache, "user", "hash", stage_prefix(TRANSCRIPTION_PREFIX, key),
        budget=budget, initial_estimates={"chunk": seconds_per_chunk},
    )
    transcribed, results = [], {}
    try:
        for index in range(total_chunks):
            cached = checkpoint.load("chunk", index)
            if cached is not None:
                results[index] = cached
                continue
            checkpoint.before_unit("chunk", index)
            clock.now += seconds_per_chunk
            results[index] = {
                "segments": [{"start": 1.0, "end": 2.5, "text": f"chunk {index}"}],
                "language": "it",
            }
            checkpoint.save("chunk", index, results[index])
            checkpoint.after_unit("chunk", index, seconds_per_chunk)
            transcribed.append(index)
    except ContinuationRequested:
        return transcribed, None
    return transcribed, merge_chunks(results, total_chunks)


def test_settings_key_is_stable_and_tracks_every_output_setting():
    base = dict(model="large-v3", language="it", chunk_seconds=300, params={"beam_size": 5})
    assert settings_key(**base) == settings_key(**dict(reversed(list(base.items()))))
    for change in (
        {"model": "small"}, {"language": "en"}, {"chunk_seconds": 600},
        {"params": {"beam_size": 1}},
    ):
        assert settings_key(**{**base, **change}) != settings_key(**base)


def test_merge_applies_chunk_offsets_in_order():
    segments, language = merge_chunks({
        1: {"segments": [{"start": 0.5, "end": 2.0, "text": "b"}], "language": "it"},
        0: {"segments": [{"start": 10.0, "end": 12.0, "text": "a"}], "language": None},
        2: {"segments": [], "language": "en"},
    }, total_chunks=3)

    assert segments == [
        {"start": 10.0, "end": 12.0, "text": "a"},
        {"start": TRANSCRIPTION_CHUNK_SECONDS + 0.5, "end": TRANSCRIPTION_CHUNK_SECONDS + 2.0, "text": "b"},
    ]
    assert language == "it"


def test_merge_refuses_an_incomplete_set():
    with pytest.raises(ValueError, match=r"missing chunks \[1\]"):
        merge_chunks({0: {"segments": []}, 2: {"segments": []}}, total_chunks=3)


def test_budget_is_derived_from_task_timeout_unless_set_explicitly():
    assert resolve_budget_seconds(0, 3600) == 3000
    assert resolve_budget_seconds(1200, 3600) == 1200
    assert resolve_budget_seconds(0, 0) == 3000
    assert resolve_budget_seconds(0, 500) == 300


def test_budget_uses_slowest_observed_unit_with_headroom():
    clock = Clock()
    budget = TimeBudget(1000, started_at=0.0, clock=clock)
    assert budget.fits("chunk", 100)

    budget.record("chunk", 200)
    budget.record("chunk", 50)
    clock.now = 650
    assert budget.fits("chunk", 100)        # 350s left, needs 200 * 1.5 = 300
    clock.now = 701
    assert not budget.fits("chunk", 100)    # 299s left
    assert budget.fits("other", 100)        # kinds are estimated separately


def test_run_stops_cleanly_when_next_chunk_would_not_fit_then_resumes():
    cache, clock = FakeCache(), Clock()

    first, merged = _run_transcription(cache, clock, budget_seconds=500, total_chunks=6, seconds_per_chunk=100)
    assert merged is None
    assert first == [0, 1, 2, 3]            # after 4 chunks 100s are left, 150s is needed
    assert len(cache.rows) == 4

    first_run_rows = dict(cache.rows)
    second, merged = _run_transcription(cache, clock, budget_seconds=500, total_chunks=6, seconds_per_chunk=100)
    assert second == [4, 5]                 # nothing already checkpointed is redone
    assert {key: cache.rows[key] for key in first_run_rows} == first_run_rows

    segments, language = merged
    assert [segment["text"] for segment in segments] == [f"chunk {i}" for i in range(6)]
    assert [segment["start"] for segment in segments] == [i * 300 + 1.0 for i in range(6)]
    assert language == "it"


def test_changed_settings_do_not_reuse_other_chunks():
    cache, clock = FakeCache(), Clock()
    _run_transcription(cache, clock, 10_000, total_chunks=2, seconds_per_chunk=10, key="model-a")

    transcribed, _ = _run_transcription(cache, clock, 10_000, total_chunks=2, seconds_per_chunk=10, key="model-b")

    assert transcribed == [0, 1]


def test_cancellation_is_checked_before_each_new_unit():
    class Cancelled(Exception):
        pass

    def cancelled():
        raise Cancelled()

    checkpoint = BudgetedCheckpoint(
        FakeCache(), "user", "hash", "p:", budget=TimeBudget(1000),
        initial_estimates={}, check_cancelled=cancelled,
    )
    with pytest.raises(Cancelled):
        checkpoint.before_unit("chunk", 0)


def test_failed_checkpoint_write_is_not_treated_as_saved():
    cache = FakeCache()
    cache.fail_saves = True
    checkpoint = StageCheckpoint(cache, "user", "hash", "p:")

    checkpoint.save("chunk", 0, {"segments": []})

    assert checkpoint.load("chunk", 0) is None
    assert StageCheckpoint(cache, "user", "hash", "p:").count("chunk") == 0


def test_checkpoints_are_scoped_to_owner_and_video():
    cache = FakeCache()
    StageCheckpoint(cache, "user-a", "hash", "p:").save("chunk", 0, {"segments": []})

    assert StageCheckpoint(cache, "user-b", "hash", "p:").load("chunk", 0) is None
    assert StageCheckpoint(cache, "user-a", "other", "p:").load("chunk", 0) is None


def test_clear_removes_only_this_stage_prefix():
    cache = FakeCache()
    chunks = StageCheckpoint(cache, "user", "hash", "transcription_chunk:k:")
    chunks.save("chunk", 0, {"segments": []})
    cache.save_cache("user", "hash", "transcription", {"formatted_segments": []})

    chunks.clear()

    assert list(cache.rows) == [("user", "hash", "transcription")]
    assert chunks.load("chunk", 0) is None


def test_request_continuation_passes_cap_and_returns_outcome(monkeypatch):
    calls = []

    class Client:
        def rpc(self, name, params):
            calls.append((name, params))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data="continue"))

    monkeypatch.setattr(job_queue_service, "supabase", lambda: Client())

    assert JobQueueService.request_continuation("job-a", 12.5, 12) == "continue"
    assert calls == [("requeue_job_for_continuation", {
        "p_job_id": "job-a", "p_max_continuations": 12, "p_gpu_seconds": 12.5,
    })]


def test_long_files_log_a_warning_but_tier_caps_are_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(settings, "WORKER_TIME_BUDGET_SECONDS", 3000)
    monkeypatch.setattr(settings, "MAX_JOB_CONTINUATIONS", 12)
    monkeypatch.setattr(settings, "PROCESSING_REALTIME_FACTOR", 0.35)

    assert quota.warn_if_processing_time_unrealistic(30 * 60) is None
    assert "about 3 worker executions" in quota.warn_if_processing_time_unrealistic(6 * 60 * 60)

    monkeypatch.setattr(settings, "PROCESSING_REALTIME_FACTOR", 10.0)
    assert "unlikely to finish" in quota.warn_if_processing_time_unrealistic(6 * 60 * 60)
    assert "[Quota] WARNING" in capsys.readouterr().out

    assert quota.PLAN_LIMITS["pro"]["max_file_duration_seconds"] == 3 * 60 * 60
    assert quota.PLAN_LIMITS["studio"]["max_file_duration_seconds"] == 6 * 60 * 60


def test_continuation_migration_contract():
    migration = (BACKEND / "sql/migrations/018_job_continuations.sql").read_text(encoding="utf-8")
    requeue = migration[migration.index("FUNCTION requeue_job_for_continuation"):]
    requeue = requeue[:requeue.index("CREATE OR REPLACE FUNCTION claim_job")]

    assert "continuation_count INTEGER NOT NULL DEFAULT 0" in migration
    assert "pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0))" in requeue
    assert "v_job.status <> 'processing'" in requeue
    assert "error_code = 'max_continuations_reached'" in requeue
    # The hand-over branch keeps the reservation; only the exhausted branch releases it.
    handover = requeue[requeue.index("status = 'pending', stage = 'continuing'"):]
    assert "quota_reserved_seconds" not in handover
    assert "retry_count" not in requeue
    assert "continuation_count = 0" in migration[migration.index("FUNCTION retry_job_secure"):]
    assert "FROM PUBLIC, anon, authenticated" in migration
    assert "TO service_role" in migration


def test_worker_checkpoints_each_chunk_and_hands_over_through_the_dispatcher():
    source = (BACKEND / "services/background_worker.py").read_text(encoding="utf-8")
    loop = source[source.index("for i, chunk_path in enumerate(audio_chunks):"):]
    loop = loop[:loop.index("merge_chunks(")]

    assert loop.index('transcription_checkpoint.load("chunk", i)') < loop.index(
        'transcription_checkpoint.before_unit("chunk", i)'
    ) < loop.index("_transcribe_chunk") < loop.index('transcription_checkpoint.save("chunk", i')
    assert "segment_duration=TRANSCRIPTION_CHUNK_SECONDS" in source
    assert 'PipelineCacheService.save_cache(user_id, video_hash, "transcription"' in source

    handover = source[source.index("def _hand_over_to_continuation"):]
    handover = handover[:handover.index("async def _resume_finalization")]
    assert "settings.MAX_JOB_CONTINUATIONS" in handover
    assert "JobQueueService.trigger_worker_job(job_id)" in handover
    assert "mark_failed" not in handover
    assert "except (JobCancelled, ContinuationRequested):" in source
