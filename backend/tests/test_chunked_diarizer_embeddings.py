import numpy as np

import speaker_diarization
from speaker_diarization import ChunkedSpeakerDiarizer


class _FakeInference:
    def __init__(self, vectors):
        self._vectors = list(vectors)
        self.calls = []

    def crop(self, audio_path, segment):
        self.calls.append((audio_path, segment))
        return self._vectors.pop(0)


def test_embedding_model_is_wrapped_in_whole_window_inference(monkeypatch):
    model = type("Model", (), {"to": lambda self, device: self})()
    captured = {}

    def fake_inference(wrapped, **kwargs):
        captured["wrapped"] = wrapped
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(speaker_diarization.Model, "from_pretrained", lambda *_a, **_k: model)
    monkeypatch.setattr(speaker_diarization, "Inference", fake_inference)

    diarizer = ChunkedSpeakerDiarizer(use_auth_token="token")
    diarizer.load_embedding_model()

    assert captured["wrapped"] is model
    assert captured["kwargs"]["window"] == "whole"
    assert diarizer.embedding_inference is not None

    diarizer.unload_embedding_model()
    assert diarizer.embedding_model is None
    assert diarizer.embedding_inference is None


def test_speaker_embedding_is_unit_norm_average_of_cropped_segments():
    diarizer = ChunkedSpeakerDiarizer()
    inference = _FakeInference([np.array([3.0, 0.0]), np.array([1.0, 0.0])])
    diarizer.embedding_inference = inference

    result = diarizer._extract_speaker_embeddings(
        "chunk.wav",
        [
            {"speaker": "SPEAKER_00", "local_start": 0.0, "local_end": 4.0},
            {"speaker": "SPEAKER_00", "local_start": 10.0, "local_end": 12.0},
        ],
    )

    assert [call[0] for call in inference.calls] == ["chunk.wav", "chunk.wav"]
    assert np.allclose(result["SPEAKER_00"], [1.0, 0.0], atol=1e-6)
    assert np.isclose(np.linalg.norm(result["SPEAKER_00"]), 1.0, atol=1e-6)


def test_failed_crop_leaves_speaker_without_embedding():
    class _Broken:
        def crop(self, *_args):
            raise RuntimeError("boom")

    diarizer = ChunkedSpeakerDiarizer()
    diarizer.embedding_inference = _Broken()

    result = diarizer._extract_speaker_embeddings(
        "chunk.wav",
        [{"speaker": "SPEAKER_01", "local_start": 0.0, "local_end": 3.0}],
    )

    assert result == {}
