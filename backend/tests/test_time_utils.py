from datetime import datetime, timezone

import pytest

from utils.time_utils import fix_segment_durations, parse_db_timestamp


@pytest.mark.parametrize("value, microsecond", [
    ("2026-10-26T10:36:31.33511+00:00", 335110),   # Postgres trims trailing zeros
    ("2026-10-26T10:36:31.3+00:00", 300000),
    ("2026-10-26T10:36:31.335110+00:00", 335110),
    ("2026-10-26T10:36:31.1234567+00:00", 123456),
    ("2026-10-26T10:36:31Z", 0),
    ("2026-10-26T10:36:31+00:00", 0),
])
def test_parse_db_timestamp_accepts_any_fraction_length(value, microsecond):
    expected = datetime(2026, 10, 26, 10, 36, 31, microsecond, tzinfo=timezone.utc)

    assert parse_db_timestamp(value) == expected


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
