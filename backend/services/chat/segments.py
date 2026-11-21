"""Transcript segment accessors shared by text retrieval and comparison."""


def _format_segment_time(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _segment_text(segment: dict) -> str:
    """Return the transcript text used for chat context."""
    return (segment.get("translation") or segment.get("text") or "").strip()


def _segment_bounds(segment: dict) -> tuple[float, float, str, str]:
    start = float(segment.get("start", 0) or 0)
    end = float(segment.get("end", start) or start)
    return (
        start,
        end,
        segment.get("start_time") or _format_segment_time(start),
        segment.get("end_time") or _format_segment_time(end),
    )


def _segment_key(segment: dict) -> tuple[float, float, str]:
    start, end, _, _ = _segment_bounds(segment)
    return (round(start, 3), round(end, 3), _segment_text(segment)[:80])


def _segment_as_search_result(video_hash: str, segment: dict) -> dict:
    text = _segment_text(segment)
    start, end, start_time, end_time = _segment_bounds(segment)
    speaker = segment.get("speaker") or "SPEAKER_00"
    return {
        "text": text,
        "metadata": {
            "video_hash": video_hash,
            "start": start,
            "end": end,
            "start_time": start_time,
            "end_time": end_time,
            "speaker": speaker,
        },
        "distance": None,
    }
