from pathlib import Path

import numpy as np

import audio_analyzer
from services import transcript_embedding_service as tes

BACKEND = Path(__file__).resolve().parents[1]


def test_the_emotion_model_is_neither_baked_nor_verified():
    for name in ("download_models.py", "verify_models.py"):
        source = (BACKEND / name).read_text(encoding="utf-8")
        assert "wav2vec2" not in source and "EMOTION" not in source, name


def test_segment_analysis_returns_events_and_energy_only(monkeypatch):
    monkeypatch.setattr(audio_analyzer, "detect_audio_events", lambda path, threshold: [])
    monkeypatch.setattr(audio_analyzer, "calculate_energy_level", lambda path: 0.4)

    result = audio_analyzer.analyze_audio_segment_from_array(np.zeros(16000, dtype=np.float32), 16000, 0.0, 1.0)

    assert set(result) == {"has_speech", "audio_events", "energy_level", "duration"}
    assert result["energy_level"] == 0.4


def test_old_emotion_data_is_not_indexed_for_chat(monkeypatch):
    replaced = {}

    class Encoder:
        def encode(self, texts, convert_to_numpy):
            return np.zeros((len(texts), 3))

    service = tes.TranscriptEmbeddingService()
    service._embedding_model = Encoder()
    monkeypatch.setattr(tes, "supabase", lambda: object())
    monkeypatch.setattr(service, "_replace_index",
                        lambda client, kind, video_hash, user_id, records: replaced.setdefault("records", records) and len(records))

    legacy_segment = {
        "id": "s1", "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00",
        "audio_events": [{"event_type": "laughter", "confidence": 0.8}],
        "audio_analysis": {"has_speech": True, "speech_emotion": {"emotion": "sad", "confidence": 0.13}},
    }
    service.index_audio_events("h" * 64, [legacy_segment], user_id="u", force_reindex=True)

    [record] = replaced["records"]
    assert record["description"] == "laughter (80%)"
    assert "speech_emotion" not in record
