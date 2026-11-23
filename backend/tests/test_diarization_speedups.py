import asyncio
import threading

import speaker_diarization
from services import background_worker as worker


def test_the_pipeline_loads_with_larger_batches(monkeypatch):
    class FakePipeline:
        segmentation_batch_size = 32
        embedding_batch_size = 32

    monkeypatch.setattr(speaker_diarization.Pipeline, "from_pretrained", lambda *a, **k: FakePipeline())
    monkeypatch.setattr(speaker_diarization.settings, "DIARIZATION_BATCH_SIZE", 128)

    pipeline = speaker_diarization.load_diarization_pipeline("token")
    assert (pipeline.segmentation_batch_size, pipeline.embedding_batch_size) == (128, 128)


def test_videos_are_split_into_even_groups_of_at_most_45_minutes():
    diarizer = speaker_diarization.ChunkedSpeakerDiarizer(chunk_duration=2700, use_auth_token=None)

    def sizes(chunk_count):
        return [len(g["chunks"]) for g in diarizer._group_chunks([f"c{i}" for i in range(chunk_count)], 300)]

    assert sizes(9) == [9]
    assert sizes(14) == [7, 7]
    assert sizes(10) == [5, 5]
    assert sizes(19) == [7, 7, 5]
    assert sizes(0) == []
    groups = diarizer._group_chunks([f"c{i}" for i in range(14)], 300)
    assert [g["time_offset"] for g in groups] == [0, 2100]


def test_a_single_group_skips_the_embedding_model(monkeypatch, tmp_path):
    diarizer = speaker_diarization.ChunkedSpeakerDiarizer(chunk_duration=2700, use_auth_token=None)
    segments = [
        {"start": 0.0, "end": 30.0, "speaker": "SPEAKER_01", "local_start": 0.0, "local_end": 30.0},
        {"start": 30.0, "end": 60.0, "speaker": "SPEAKER_00", "local_start": 30.0, "local_end": 60.0},
    ]
    monkeypatch.setattr(diarizer, "load_pipeline", lambda: None)
    monkeypatch.setattr(diarizer, "_concatenate_audio_files", lambda files, out: None)
    monkeypatch.setattr(diarizer, "_diarize_group_with_preconcat", lambda *a, **k: {
        "time_offset": 0, "segments": segments, "audio_path": "a.wav", "is_temp": False, "speaker_embeddings": {},
    })
    monkeypatch.setattr(diarizer, "load_embedding_model", lambda: (_ for _ in ()).throw(AssertionError("loaded")))

    result = diarizer.diarize_chunked([str(tmp_path / "c0.wav")], chunk_duration=300)
    assert [s["speaker"] for s in result] == ["SPEAKER_00", "SPEAKER_01"]


def test_starts_added_by_speaker_split_are_new_starts_only_once():
    segments = [{"start": 1.0}, {"start": 2.5}, {"start": 2.5}, {"start": 4.0}]
    assert worker._starts_added_by_speaker_split(segments, {1.0: "u", 4.0: "u"}) == [2.5]


def test_screenshots_run_while_the_gpu_executor_is_busy(monkeypatch, tmp_path):
    shot = tmp_path / "a.jpg"
    shot.write_bytes(b"x")
    uploaded = {}

    class Storage:
        def upload_screenshots_batch(self, screenshot_paths, video_hash, user_id):
            uploaded.update(screenshot_paths)
            return {ts: f"url{ts}" for ts in screenshot_paths}

    monkeypatch.setattr(worker.VideoService, "extract_screenshots_parallel_from_url",
                        staticmethod(lambda **kwargs: {1.0: str(shot), 2.0: None}))
    monkeypatch.setattr(worker, "get_media_storage", lambda: Storage())

    release = threading.Event()

    async def scenario():
        diarizing = asyncio.ensure_future(worker._run_in_executor(release.wait, 5))
        urls = await asyncio.wait_for(
            worker._extract_and_upload_screenshots("video.mp4", [1.0, 2.0], str(tmp_path), "h", "u"), timeout=2,
        )
        release.set()
        await diarizing
        return urls

    assert asyncio.run(scenario()) == {1.0: "url1.0"}
    assert uploaded == {1.0: str(shot)}
    assert not shot.exists()


def test_diarization_defaults_match_the_measured_settings():
    import re
    from pathlib import Path

    config = (Path(__file__).resolve().parents[1] / "config.py").read_text(encoding="utf-8")
    defaults = dict(re.findall(r'os\.getenv\("(DIARIZATION_CHUNK_DURATION|DIARIZATION_BATCH_SIZE)", "(\d+)"\)', config))
    assert defaults == {"DIARIZATION_CHUNK_DURATION": "900", "DIARIZATION_BATCH_SIZE": "32"}, (
        "v0.1.6 measured on a 45-min episode: one 2700 s pass did not finish in 18 min, "
        "and batch 128 was no faster than 32"
    )
