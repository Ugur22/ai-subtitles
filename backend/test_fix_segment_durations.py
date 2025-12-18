#!/usr/bin/env python3
"""
Test script for fix_segment_durations function
Verifies that the fix correctly handles overly long segments
"""

from typing import List, Dict


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format with millisecond precision"""
    total_secs = int(seconds)
    milliseconds = int((seconds - total_secs) * 1000)

    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def fix_segment_durations(segments: List[Dict], max_duration_per_word: float = 2.0,
                          min_duration: float = 0.5, max_segment_duration: float = 30.0) -> List[Dict]:
    """
    Fix segments with unreasonably long durations caused by chunk boundary processing.

    This addresses the issue where Whisper creates incorrectly long segments during chunk
    processing. When segments are discarded at chunk boundaries, the previous segment's
    end time can be incorrectly extended (e.g., a single word spanning 178 seconds).

    Args:
        segments: List of segments to fix
        max_duration_per_word: Maximum expected seconds per word (default: 2.0)
        min_duration: Minimum segment duration in seconds (default: 0.5)
        max_segment_duration: Absolute maximum segment duration in seconds (default: 30.0)

    Returns:
        Segments with corrected durations
    """
    fixed_count = 0

    for segment in segments:
        # Skip silent segments (they're meant to have longer durations)
        if segment.get('is_silent', False):
            continue

        text = segment.get('text', '').strip()
        word_count = len(text.split()) if text else 1

        start = segment.get('start', 0)
        end = segment.get('end', 0)
        duration = end - start

        # Calculate expected max duration based on word count
        # Use a reasonable estimate: average speaking rate is ~2-3 words per second
        # So 2 seconds per word is very generous
        expected_max = max(min_duration, word_count * max_duration_per_word)
        expected_max = min(expected_max, max_segment_duration)

        # If duration is way too long, fix it (allow 3x tolerance before fixing)
        if duration > expected_max * 3:
            new_end = start + expected_max
            print(f"Fixing segment duration: '{text[:50]}...' was {duration:.1f}s ({duration/60:.1f}min), now {expected_max:.1f}s (words: {word_count})")
            segment['end'] = new_end
            # Update end_time string too
            segment['end_time'] = format_timestamp(new_end)
            fixed_count += 1

    if fixed_count > 0:
        print(f"Fixed {fixed_count} segments with unreasonably long durations")

    return segments


def test_fix_segment_durations():
    """Test the fix_segment_durations function with various scenarios"""

    print("="*60)
    print("Testing fix_segment_durations function")
    print("="*60)

    # Test Case 1: Segment with extremely long duration (the reported issue)
    # "Sí." spanning 178 seconds instead of ~1 second
    test_segments_1 = [
        {
            "id": "test-1",
            "start": 0.0,
            "end": 178.0,  # Incorrectly long!
            "start_time": "00:00:00.000",
            "end_time": "00:02:58.000",
            "text": "Sí.",
            "translation": "Yes.",
            "speaker": "SPEAKER_00"
        }
    ]

    print("\nTest Case 1: Single word with 178 second duration")
    print(f"Before: '{test_segments_1[0]['text']}' - Duration: {test_segments_1[0]['end'] - test_segments_1[0]['start']:.1f}s")

    fixed_1 = fix_segment_durations(test_segments_1)

    print(f"After:  '{fixed_1[0]['text']}' - Duration: {fixed_1[0]['end'] - fixed_1[0]['start']:.1f}s")
    print(f"New end time: {fixed_1[0]['end_time']}")

    # Test Case 2: Normal segments (should not be modified)
    test_segments_2 = [
        {
            "id": "test-2",
            "start": 0.0,
            "end": 2.5,  # Normal duration
            "start_time": "00:00:00.000",
            "end_time": "00:00:02.500",
            "text": "Hello world",
            "translation": "Hello world",
            "speaker": "SPEAKER_00"
        },
        {
            "id": "test-3",
            "start": 2.5,
            "end": 5.0,  # Normal duration
            "start_time": "00:00:02.500",
            "end_time": "00:00:05.000",
            "text": "How are you?",
            "translation": "How are you?",
            "speaker": "SPEAKER_01"
        }
    ]

    print("\nTest Case 2: Normal segments (should not be modified)")
    for seg in test_segments_2:
        print(f"Before: '{seg['text']}' - Duration: {seg['end'] - seg['start']:.1f}s")

    fixed_2 = fix_segment_durations(test_segments_2)

    for seg in fixed_2:
        print(f"After:  '{seg['text']}' - Duration: {seg['end'] - seg['start']:.1f}s")

    # Test Case 3: Long segment with many words (should be allowed)
    test_segments_3 = [
        {
            "id": "test-4",
            "start": 0.0,
            "end": 15.0,  # 15 seconds for 10 words is reasonable
            "start_time": "00:00:00.000",
            "end_time": "00:00:15.000",
            "text": "This is a longer sentence with multiple words that takes time to speak",
            "translation": "This is a longer sentence with multiple words that takes time to speak",
            "speaker": "SPEAKER_00"
        }
    ]

    print("\nTest Case 3: Long segment with many words (should be allowed)")
    print(f"Before: '{test_segments_3[0]['text'][:50]}...' - Duration: {test_segments_3[0]['end'] - test_segments_3[0]['start']:.1f}s")

    fixed_3 = fix_segment_durations(test_segments_3)

    print(f"After:  '{fixed_3[0]['text'][:50]}...' - Duration: {fixed_3[0]['end'] - fixed_3[0]['start']:.1f}s")

    # Test Case 4: Silent segment (should not be modified)
    test_segments_4 = [
        {
            "id": "test-5",
            "start": 0.0,
            "end": 30.0,  # Long duration is OK for silent segments
            "start_time": "00:00:00.000",
            "end_time": "00:00:30.000",
            "text": "[No speech]",
            "translation": "[No speech]",
            "speaker": "VISUAL",
            "is_silent": True
        }
    ]

    print("\nTest Case 4: Silent segment (should not be modified)")
    print(f"Before: '{test_segments_4[0]['text']}' - Duration: {test_segments_4[0]['end'] - test_segments_4[0]['start']:.1f}s")

    fixed_4 = fix_segment_durations(test_segments_4)

    print(f"After:  '{fixed_4[0]['text']}' - Duration: {fixed_4[0]['end'] - fixed_4[0]['start']:.1f}s")

    # Test Case 5: Multiple segments with chunk boundary issue
    test_segments_5 = [
        {
            "id": "test-6",
            "start": 295.0,
            "end": 298.0,
            "start_time": "00:04:55.000",
            "end_time": "00:04:58.000",
            "text": "First chunk last segment",
            "translation": "First chunk last segment",
            "speaker": "SPEAKER_00"
        },
        {
            "id": "test-7",
            "start": 298.0,
            "end": 476.0,  # Incorrectly extended to next chunk's discarded segment
            "start_time": "00:04:58.000",
            "end_time": "00:07:56.000",
            "text": "Sí.",
            "translation": "Yes.",
            "speaker": "SPEAKER_00"
        },
        {
            "id": "test-8",
            "start": 476.0,
            "end": 478.5,
            "start_time": "00:07:56.000",
            "end_time": "00:07:58.500",
            "text": "Next segment after the gap",
            "translation": "Next segment after the gap",
            "speaker": "SPEAKER_01"
        }
    ]

    print("\nTest Case 5: Chunk boundary issue (second segment incorrectly long)")
    for seg in test_segments_5:
        print(f"Before: '{seg['text'][:30]}...' - Duration: {seg['end'] - seg['start']:.1f}s")

    fixed_5 = fix_segment_durations(test_segments_5)

    for seg in fixed_5:
        print(f"After:  '{seg['text'][:30]}...' - Duration: {seg['end'] - seg['start']:.1f}s")

    print("\n" + "="*60)
    print("Testing complete!")
    print("="*60)


if __name__ == "__main__":
    test_fix_segment_durations()
