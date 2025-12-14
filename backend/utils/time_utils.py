"""
Time and timestamp formatting utilities
"""


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format with millisecond precision"""
    # Use int() and modulo to handle any duration correctly
    total_secs = int(seconds)
    milliseconds = int((seconds - total_secs) * 1000)

    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    # Return format with milliseconds for better subtitle sync
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT subtitle format (HH:MM:SS,mmm)"""
    total_secs = int(seconds)
    milliseconds = int((seconds - total_secs) * 1000)

    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    # SRT format uses comma for milliseconds
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def format_eta(seconds: float) -> str:
    """Format seconds into human-readable ETA string"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def time_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS time string to seconds"""
    try:
        parts = time_str.split(':')
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        return 0.0
    except Exception:
        return 0.0


def time_diff_minutes(start_time: str, end_time: str) -> float:
    """Calculate the difference between two timestamps in minutes"""
    try:
        start_seconds = time_to_seconds(start_time)
        end_seconds = time_to_seconds(end_time)
        return (end_seconds - start_seconds) / 60
    except Exception as e:
        print(f"Error calculating time difference: {str(e)}")
        return 0.0
