import json
from pathlib import Path

import pytest

from services.transcription_checkpoint import merge_chunks
from services.word_speakers import assign_speakers

FIXTURE = Path(__file__).parent / "fixtures" / "per_word_speaker_scene.json"
needs_scene = pytest.mark.skipif(not FIXTURE.exists(), reason="scene fixture is local-only, not in git")


def _scene():
    data = json.loads(FIXTURE.read_text())
    segments, truth = [], []
    for index, line in enumerate(data["lines"]):
        segments.append({
            "id": f"line-{index}",
            "start": line["start"],
            "end": line["end"],
            "text": line["text"],
            "translation": None,
            # faster-whisper words carry their own leading space
            "words": [
                {"start": w["start"], "end": w["end"], "word": " " + w["word"]}
                for w in line["words"]
            ],
        })
        truth.extend((w["start"], w["speaker_truth"]) for w in line["words"])
    return data["speakers"], segments, truth


def _speaker_at(segments, word_start):
    for segment in segments:
        if segment["start"] <= word_start <= segment["end"]:
            return segment["speaker"]
    raise AssertionError(f"no segment covers {word_start}")


@needs_scene
def test_scene_word_errors_at_most_three():
    speakers, segments, truth = _scene()
    result = assign_speakers(segments, speakers)
    wrong = [start for start, speaker in truth if _speaker_at(result, start) != speaker]
    assert len(wrong) <= 3, wrong


@needs_scene
def test_scene_keeps_no_tu_line_whole():
    speakers, segments, _ = _scene()
    result = assign_speakers(segments, speakers)
    assert any(s["text"] == "No, tú no tienes la culpa." for s in result)


@needs_scene
def test_scene_splits_mixed_lines_into_clean_text():
    speakers, segments, _ = _scene()
    result = assign_speakers(segments, speakers)
    texts = [s["text"] for s in result]
    assert "a su lado, el día que murió." in texts
    assert "Cuando mi padre estaba ingresado en la clínica," in texts
    assert all(s["end"] - s["start"] >= 0.3 for s in result)
    assert all("words" not in s for s in result)
    assert len({s["id"] for s in result}) == len(result)


def _words(pairs):
    return [
        {"start": i * 0.4, "end": i * 0.4 + 0.3, "word": " " + text, "speaker": speaker}
        for i, (text, speaker) in enumerate(pairs)
    ]


def _turns(words):
    return [{"start": w["start"], "end": w["end"], "speaker": w["speaker"]} for w in words]


def _segment(words, id_="seg"):
    return {
        "id": id_, "start": words[0]["start"], "end": words[-1]["end"],
        "text": "".join(w["word"] for w in words), "translation": None,
        "words": [{k: w[k] for k in ("start", "end", "word")} for w in words],
    }


def test_one_word_reply_is_kept():
    words = _words([
        ("Te", "A"), ("llamé", "A"), ("ayer.", "A"), ("¿Sí?", "B"), ("No", "A"), ("contestaste.", "A"),
    ])
    result = assign_speakers([_segment(words)], _turns(words))
    assert [(s["speaker"], s["text"]) for s in result] == [
        ("A", "Te llamé ayer."), ("B", "¿Sí?"), ("A", "No contestaste."),
    ]


def test_short_fragment_is_absorbed():
    words = _words([("Pues", "A"), ("yo", "B"), ("creo", "A"), ("que", "A"), ("sí.", "A")])
    result = assign_speakers([_segment(words)], _turns(words))
    assert [(s["speaker"], s["text"].strip()) for s in result] == [("A", "Pues yo creo que sí.")]


def test_single_speaker_segment_keeps_id():
    words = _words([("Hola", "A"), ("a", "A"), ("todos.", "A")])
    result = assign_speakers([_segment(words, "keep-me")], _turns(words))
    assert result[0]["id"] == "keep-me"
    assert result[0]["speaker"] == "A"


def test_segment_without_words_uses_line_speaker():
    turns = [{"start": 0.0, "end": 1.0, "speaker": "A"}, {"start": 1.0, "end": 5.0, "speaker": "B"}]
    result = assign_speakers([{"id": "x", "start": 0.0, "end": 4.0, "text": "hi"}], turns)
    assert result == [{"id": "x", "start": 0.0, "end": 4.0, "text": "hi", "speaker": "B"}]


def test_word_outside_every_turn_gets_nearest_speaker():
    turns = [{"start": 0.0, "end": 1.0, "speaker": "A"}, {"start": 5.0, "end": 6.0, "speaker": "B"}]
    segment = {
        "id": "x", "start": 4.0, "end": 4.6, "text": " ok",
        "words": [{"start": 4.0, "end": 4.6, "word": " ok"}],
    }
    assert assign_speakers([segment], turns)[0]["speaker"] == "B"


def test_no_turns_gives_unknown():
    words = _words([("Hola", "A")])
    assert assign_speakers([_segment(words)], [])[0]["speaker"] == "UNKNOWN"


def test_merge_chunks_offsets_word_times():
    chunks = {
        0: {"segments": [], "language": "es"},
        1: {"segments": [{
            "start": 1.0, "end": 2.0, "text": " hola",
            "words": [{"start": 1.0, "end": 1.5, "word": " hola"}],
        }]},
    }
    segments, _ = merge_chunks(chunks, 2, chunk_seconds=300)
    assert segments[0]["words"] == [{"start": 301.0, "end": 301.5, "word": " hola"}]
