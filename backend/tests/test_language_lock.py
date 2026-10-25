from services.language_lock import detect_dominant_language, pick_dominant_language, _sample_chunks


def test_music_opening_guessed_english_does_not_outvote_dialogue():
    votes = [("en", 0.55), ("it", 0.98), ("it", 0.97), ("ko", 0.4), ("it", 0.95)]
    assert pick_dominant_language(votes) == "it"


def test_all_weak_votes_returns_none():
    assert pick_dominant_language([("en", 0.3), ("ko", 0.2)]) is None


def test_sampling_is_capped_and_spread():
    chunks = [str(i) for i in range(40)]
    sampled = _sample_chunks(chunks)
    assert len(sampled) == 8 and sampled[0] == "0" and sampled[-1] == "35"


def test_detection_uses_vad_options_and_recovers_from_a_failed_chunk(monkeypatch):
    import faster_whisper
    from faster_whisper.vad import VadOptions

    monkeypatch.setattr(faster_whisper, "decode_audio", lambda path: path)
    calls = []

    class Whisper:
        def detect_language(self, audio, **kwargs):
            calls.append(audio)
            assert kwargs["vad_filter"] is True
            assert kwargs["language_detection_segments"] == 3
            options = kwargs["vad_parameters"]
            assert isinstance(options, VadOptions)
            assert options.min_silence_duration_ms == 500
            assert options.threshold == 0.4
            if audio == "corrupt":
                raise ValueError("bad audio")
            return "cs", 0.97, [("cs", 0.97)]

    language = detect_dominant_language(
        Whisper(), ["corrupt", "dialogue"],
        {"min_silence_duration_ms": 500, "threshold": 0.4},
    )

    assert language == "cs"
    assert calls == ["corrupt", "dialogue"]
