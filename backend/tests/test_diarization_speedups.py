import asyncio
from pathlib import Path

import speaker_diarization
from services import background_worker as worker

BACKEND = Path(__file__).resolve().parents[1]


def test_both_diarizers_load_the_pipeline_with_larger_batches(monkeypatch):
    class FakePipeline:
        segmentation_batch_size = 32
        embedding_batch_size = 32

    monkeypatch.setattr(speaker_diarization.Pipeline, "from_pretrained", lambda *a, **k: FakePipeline())
    monkeypatch.setattr(speaker_diarization.settings, "DIARIZATION_BATCH_SIZE", 128)

    pipeline = speaker_diarization.load_diarization_pipeline("token")
    assert (pipeline.segmentation_batch_size, pipeline.embedding_batch_size) == (128, 128)

    source = (BACKEND / "speaker_diarization.py").read_text(encoding="utf-8")
    assert source.count("load_diarization_pipeline(self.use_auth_token)") == 2
    assert source.count("Pipeline.from_pretrained(") == 1


def test_a_45_minute_episode_is_diarized_in_one_group():
    assert worker.settings.DIARIZATION_CHUNK_DURATION == 2700
    diarizer = speaker_diarization.ChunkedSpeakerDiarizer(
        chunk_duration=worker.settings.DIARIZATION_CHUNK_DURATION, use_auth_token=None,
    )
    assert len(diarizer._group_chunks([f"c{i}.wav" for i in range(9)], 300)) == 1


def test_longer_videos_are_split_into_even_groups():
    diarizer = speaker_diarization.ChunkedSpeakerDiarizer(chunk_duration=2700, use_auth_token=None)

    def sizes(chunk_count):
        return [len(g["chunks"]) for g in diarizer._group_chunks([f"c{i}" for i in range(chunk_count)], 300)]

    assert sizes(14) == [7, 7]
    assert sizes(10) == [5, 5]
    assert sizes(19) == [7, 7, 5]
    groups = diarizer._group_chunks([f"c{i}" for i in range(14)], 300)
    assert [g["time_offset"] for g in groups] == [0, 2100]


def test_missing_screenshot_timestamps_are_new_starts_only_once():
    segments = [{"start": 1.0}, {"start": 2.5}, {"start": 2.5}, {"start": 4.0}]
    assert worker._missing_screenshot_timestamps(segments, {1.0: "u", 4.0: "u"}) == [2.5]


def test_screenshots_are_extracted_while_diarizing_and_cancelled_on_exit():
    source = (BACKEND / "services" / "background_worker.py").read_text(encoding="utf-8")
    started = source.index("screenshot_task = asyncio.create_task(_extract_and_upload_screenshots(")
    assert started < source.index("chunked_diarizer.diarize_chunked")
    assert started < source.index("SpeakerService.add_speaker_labels")
    assert source.index("screenshot_urls = await screenshot_task") < source.index("seg['screenshot_url'] = screenshot_url")
    final = source[source.rindex("        finally:", 0, source.index("def _hand_over_to_continuation")):]
    assert "screenshot_task.cancel()" in final


def test_screenshot_helper_uploads_and_removes_local_files(monkeypatch, tmp_path):
    shot = tmp_path / "a.jpg"
    shot.write_bytes(b"x")

    class Storage:
        def upload_screenshots_batch(self, screenshot_paths, video_hash, user_id):
            return {ts: f"url{ts}" for ts, path in screenshot_paths.items() if path}

    monkeypatch.setattr(worker.VideoService, "extract_screenshots_parallel_from_url",
                        staticmethod(lambda **kwargs: {1.0: str(shot), 2.0: None}))
    monkeypatch.setattr(worker, "get_media_storage", lambda: Storage())

    urls = asyncio.run(worker._extract_and_upload_screenshots("video.mp4", [1.0, 2.0], str(tmp_path), "h", "u"))
    assert urls == {1.0: "url1.0"}
    assert not shot.exists()
