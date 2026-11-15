from services import background_worker as worker


def test_diarization_cache_key_changes_with_linking_settings(monkeypatch):
    monkeypatch.setattr(worker.settings, "DIARIZATION_LINK_MODEL", "pyannote/embedding")
    monkeypatch.setattr(worker.settings, "DIARIZATION_SIMILARITY_THRESHOLD", 0.7)
    old = worker._diarization_param_key(None, None, None)

    monkeypatch.setattr(worker.settings, "DIARIZATION_LINK_MODEL", "pyannote/wespeaker-voxceleb-resnet34-LM")
    new_model = worker._diarization_param_key(None, None, None)

    monkeypatch.setattr(worker.settings, "DIARIZATION_SIMILARITY_THRESHOLD", 0.5)
    new_threshold = worker._diarization_param_key(None, None, None)

    assert len({old, new_model, new_threshold}) == 3


def test_diarization_cache_key_still_changes_with_speaker_counts():
    assert worker._diarization_param_key(2, None, None) != worker._diarization_param_key(3, None, None)
