from utils.time_utils import fix_segment_durations


def test_fix_segment_durations_clamps_implausible_speech():
    segments = [{"start": 10.0, "end": 188.0, "text": "Yes.", "end_time": "00:03:08.000"}]

    result = fix_segment_durations(segments)

    assert result[0]["end"] == 12.0
    assert result[0]["end_time"] == "00:00:12.000"


def test_fix_segment_durations_preserves_normal_and_silent_segments():
    segments = [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 2.5, "end": 60.0, "text": "[No speech]", "is_silent": True},
    ]

    assert fix_segment_durations(segments) == segments
