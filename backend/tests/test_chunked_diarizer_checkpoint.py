import asyncio
import os

import numpy as np
import pytest

from checkpoint_fakes import FakeCache
from services.transcription_checkpoint import ContinuationRequested, StageCheckpoint, TimeBudget
from speaker_diarization import ChunkedSpeakerDiarizer

# Two speakers who swap local labels between groups, so only embedding
# matching across all groups can label them consistently.
VOICE_A = [1.0, 0.0]
VOICE_B = [0.0, 1.0]
GROUP_VOICES = [
    {"SPEAKER_00": VOICE_A, "SPEAKER_01": VOICE_B},
    {"SPEAKER_00": VOICE_B, "SPEAKER_01": VOICE_A},
    {"SPEAKER_00": VOICE_A},
]


class StopBeforeGroup(StageCheckpoint):
    def __init__(self, cache, stop_before=None):
        super().__init__(cache, "user", "hash", "diarization_group:k:")
        self.stop_before = stop_before

    def before_unit(self, kind, index):
        if kind == "segments" and index == self.stop_before:
            raise ContinuationRequested("out of budget")


@pytest.fixture
def diarizer(monkeypatch, tmp_path):
    instance = ChunkedSpeakerDiarizer(chunk_duration=600)
    instance.calls = {"diarize": [], "embed": [], "pipeline_loads": 0, "concat": []}

    def load_pipeline():
        instance.calls["pipeline_loads"] += 1
        instance.pipeline = object()

    def diarize(concat_audio_path, is_temp, time_offset, **_speakers):
        group = int(time_offset // 600)
        instance.calls["diarize"].append(group)
        return {
            "time_offset": time_offset,
            "segments": [
                {"start": time_offset + i, "end": time_offset + i + 1, "speaker": speaker,
                 "local_start": float(i), "local_end": float(i + 1)}
                for i, speaker in enumerate(GROUP_VOICES[group])
            ],
            "audio_path": concat_audio_path,
            "is_temp": is_temp,
            "speaker_embeddings": {},
        }

    def embed(audio_path, segments):
        group = int(segments[0]["start"] // 600)
        instance.calls["embed"].append(group)
        return {speaker: np.array(vector) for speaker, vector in GROUP_VOICES[group].items()}

    def concat(audio_files, output_path):
        instance.calls["concat"].append(output_path)

    monkeypatch.setattr(instance, "load_pipeline", load_pipeline)
    monkeypatch.setattr(instance, "load_embedding_model", lambda: None)
    monkeypatch.setattr(instance, "unload_embedding_model", lambda: None)
    monkeypatch.setattr(instance, "_diarize_group_with_preconcat", diarize)
    monkeypatch.setattr(instance, "_extract_speaker_embeddings", embed)
    monkeypatch.setattr(instance, "_concatenate_audio_files", concat)
    return instance


def _chunks(count=6):
    return [f"audio_{index:03d}.wav" for index in range(count)]


def _speaker_at(segments, start):
    return next(segment["speaker"] for segment in segments if segment["start"] == start)


def _canonical_turns(segments):
    labels = {}
    return [
        (segment["start"], segment["end"], labels.setdefault(segment["speaker"], len(labels)))
        for segment in segments
    ]


def test_without_checkpoint_all_groups_are_diarized(diarizer):
    segments = diarizer.diarize_chunked(_chunks(), chunk_duration=300)

    assert diarizer.calls["diarize"] == [0, 1, 2]
    assert diarizer.calls["embed"] == [0, 1, 2]
    assert len(segments) == 5


def test_early_stop_keeps_finished_groups_and_removes_temp_audio(diarizer):
    cache = FakeCache()

    with pytest.raises(ContinuationRequested):
        diarizer.diarize_chunked(
            _chunks(), chunk_duration=300, checkpoint=StopBeforeGroup(cache, stop_before=1)
        )

    assert diarizer.calls["diarize"] == [0]
    assert [key[2] for key in cache.rows] == ["diarization_group:k:segments:0000"]
    assert len(diarizer.calls["concat"]) == 3
    assert not any(os.path.exists(path) for path in diarizer.calls["concat"])


def test_resume_skips_cached_groups_and_matches_speakers_across_all_groups(diarizer):
    cache = FakeCache()
    with pytest.raises(ContinuationRequested):
        diarizer.diarize_chunked(
            _chunks(), chunk_duration=300, checkpoint=StopBeforeGroup(cache, stop_before=2)
        )
    assert diarizer.calls["diarize"] == [0, 1]
    assert diarizer.calls["embed"] == []          # embeddings come after every group is diarized

    diarizer.calls["diarize"].clear()
    segments = diarizer.diarize_chunked(
        _chunks(), chunk_duration=300, checkpoint=StopBeforeGroup(cache)
    )

    assert diarizer.calls["diarize"] == [2]       # groups 0 and 1 came from the checkpoint
    assert diarizer.calls["embed"] == [0, 1, 2]

    # Voice A is local SPEAKER_00 in groups 0 and 2 but SPEAKER_01 in group 1.
    voice_a = _speaker_at(segments, 0)
    assert _speaker_at(segments, 601) == voice_a
    assert _speaker_at(segments, 1200) == voice_a
    assert _speaker_at(segments, 1) == _speaker_at(segments, 600) != voice_a
    assert {segment["speaker"] for segment in segments} == {"SPEAKER_00", "SPEAKER_01"}

    uninterrupted = diarizer.diarize_chunked(_chunks(), chunk_duration=300)
    assert _canonical_turns(segments) == _canonical_turns(uninterrupted)


def test_fully_cached_run_needs_no_models_or_audio(diarizer):
    cache = FakeCache()
    first = diarizer.diarize_chunked(
        _chunks(), chunk_duration=300, checkpoint=StopBeforeGroup(cache)
    )
    loads = diarizer.calls["pipeline_loads"]
    for name in ("diarize", "embed", "concat"):
        diarizer.calls[name].clear()

    second = diarizer.diarize_chunked(
        _chunks(), chunk_duration=300, checkpoint=StopBeforeGroup(cache)
    )

    assert second == first
    assert diarizer.calls["pipeline_loads"] == loads
    assert diarizer.calls["diarize"] == [] and diarizer.calls["embed"] == []
    assert diarizer.calls["concat"] == []


def test_worker_keeps_groups_until_final_save_and_then_uses_final_cache(monkeypatch, diarizer):
    from services import background_worker as worker

    cache = FakeCache()
    monkeypatch.setattr(worker, "PipelineCacheService", cache)
    monkeypatch.setattr(worker, "ChunkedSpeakerDiarizer", lambda **kwargs: diarizer)
    monkeypatch.setattr(worker.settings, "ENABLE_SPEAKER_DIARIZATION", True)
    monkeypatch.setattr(worker.settings, "USE_CHUNKED_DIARIZATION_ABOVE", 600)
    monkeypatch.setattr(worker.settings, "DIARIZATION_CHUNK_DURATION", 600)
    monkeypatch.setattr(worker, "_check_cancelled", lambda job_id: None)
    monkeypatch.setattr(worker.JobQueueService, "update_progress", lambda *args: None)

    def run(budget, cached=None):
        return asyncio.run(worker._run_diarization_stage(
            job_id="job", user_id="user", video_hash="hash", audio_chunks=_chunks(),
            full_audio_path=None, formatted_segments=[{"start": 0, "end": 1, "text": "Hi"}],
            cached_diarization=cached, speaker_bounds={},
            diarization_param_key=worker._diarization_param_key(None, None, None), budget=budget,
        ))

    budget = TimeBudget(3600)
    monkeypatch.setattr(budget, "fits", lambda *args: budget.units_done < 2)
    with pytest.raises(ContinuationRequested):
        run(budget)
    assert diarizer.calls["diarize"] == [0, 1]
    assert len(cache.rows) == 2

    with monkeypatch.context() as patch:
        save = cache.save_cache

        def fail_final_save(owner, media, stage, data):
            if stage == "diarization":
                return False
            return save(owner, media, stage, data)

        patch.setattr(cache, "save_cache", fail_final_save)
        expected = run(TimeBudget(3600))
    assert diarizer.calls["diarize"] == [0, 1, 2]
    assert diarizer.calls["embed"] == [0, 1, 2]
    assert len(cache.rows) == 6

    assert run(TimeBudget(3600)) == expected
    final_key = ("user", "hash", "diarization")
    assert set(cache.rows) == {final_key}
    assert expected[0]["speaker"] == cache.rows[final_key]["speaker_segments"][0]["speaker"]
    assert run(TimeBudget(0), cached=cache.rows[final_key]) == expected
    assert diarizer.calls["diarize"] == [0, 1, 2]
    assert diarizer.calls["embed"] == [0, 1, 2]
