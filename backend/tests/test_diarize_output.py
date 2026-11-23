from types import SimpleNamespace

from pyannote.core import Annotation, Segment

import speaker_diarization


def _output(turns):
    annotation = Annotation()
    for start, end, speaker in turns:
        annotation[Segment(start, end)] = speaker
    return SimpleNamespace(speaker_diarization=annotation, exclusive_speaker_diarization=Annotation())


class FakePipeline:
    def __init__(self, turns):
        self.turns = turns
        self.calls = []

    def __call__(self, path, **params):
        self.calls.append((path, params))
        return _output(self.turns)


def test_pipeline_loads_community_1_with_token(monkeypatch):
    seen = {}

    def from_pretrained(name, **kwargs):
        seen.update(name=name, **kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(speaker_diarization.Pipeline, "from_pretrained", from_pretrained)
    speaker_diarization.load_diarization_pipeline("hf-token")
    assert seen == {"name": "pyannote/speaker-diarization-community-1", "token": "hf-token"}


def test_full_audio_diarization_reads_speaker_diarization():
    diarizer = speaker_diarization.SpeakerDiarizer(use_auth_token=None)
    diarizer.pipeline = FakePipeline([(0.0, 4.0, "SPEAKER_00"), (4.0, 9.0, "SPEAKER_01")])

    segments = diarizer.diarize("audio.wav", min_speakers=1, max_speakers=3)

    assert segments == [
        {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"},
        {"start": 4.0, "end": 9.0, "speaker": "SPEAKER_01"},
    ]
    assert diarizer.pipeline.calls == [("audio.wav", {"min_speakers": 1, "max_speakers": 3})]


def test_group_diarization_offsets_speaker_diarization_turns():
    diarizer = speaker_diarization.ChunkedSpeakerDiarizer(chunk_duration=900, use_auth_token=None)
    diarizer.pipeline = FakePipeline([(1.0, 3.0, "SPEAKER_00")])

    result = diarizer._diarize_group_segments_only(["chunk.wav"], time_offset=600.0)

    assert result["segments"][0] == {
        "start": 601.0, "end": 603.0, "speaker": "SPEAKER_00", "local_start": 1.0, "local_end": 3.0,
    }
