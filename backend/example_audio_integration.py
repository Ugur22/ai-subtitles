"""
Example: Integrating audio_analyzer with existing AI-Subs transcription pipeline

This example shows how to enhance transcription results with audio analysis.
"""

from typing import List, Dict
from audio_analyzer import analyze_audio_segment, get_simplified_events


# ============================================================================
# Example 1: Basic Integration with Transcription
# ============================================================================

def enhance_transcription_with_audio_analysis(
    transcription_segments: List[Dict],
    audio_path: str,
    confidence_threshold: float = 0.2
) -> List[Dict]:
    """
    Enhance transcription segments with audio analysis data.

    Args:
        transcription_segments: List of transcription segments with 'start', 'end', 'text'
        audio_path: Path to the audio file
        confidence_threshold: Threshold for audio event detection

    Returns:
        Enhanced segments with audio analysis data
    """
    enhanced_segments = []

    for segment in transcription_segments:
        # Run audio analysis
        analysis = analyze_audio_segment(
            audio_path,
            segment['start'],
            segment['end'],
            threshold=confidence_threshold
        )

        # Create enhanced segment
        enhanced = {
            **segment,  # Original data (start, end, text, speaker, etc.)
            'audio_analysis': {
                'has_speech': analysis['has_speech'],
                'energy_level': analysis['energy_level'],
                'emotion': None,
                'top_events': []
            }
        }

        # Add emotion if detected
        if analysis['speech_emotion']:
            enhanced['audio_analysis']['emotion'] = {
                'primary': analysis['speech_emotion']['emotion'],
                'confidence': analysis['speech_emotion']['confidence']
            }

        # Add top 3 audio events
        if analysis['audio_events']:
            enhanced['audio_analysis']['top_events'] = get_simplified_events(
                analysis['audio_events'],
                top_n=3
            )

        enhanced_segments.append(enhanced)

    return enhanced_segments


# ============================================================================
# Example 2: Detecting Highlights in Video
# ============================================================================

def detect_video_highlights(
    audio_path: str,
    duration: float,
    segment_duration: float = 5.0
) -> List[Dict]:
    """
    Detect interesting moments in video based on audio analysis.

    Args:
        audio_path: Path to audio file
        duration: Total duration in seconds
        segment_duration: Length of each analysis segment

    Returns:
        List of highlight moments
    """
    highlights = []

    current_time = 0.0
    while current_time < duration:
        end_time = min(current_time + segment_duration, duration)

        # Analyze segment
        analysis = analyze_audio_segment(
            audio_path,
            current_time,
            end_time,
            threshold=0.2
        )

        # Criteria for highlights
        is_highlight = False
        highlight_type = None
        reason = []

        # High energy moment
        if analysis['energy_level'] > 0.7:
            is_highlight = True
            highlight_type = 'high_energy'
            reason.append(f"High energy ({analysis['energy_level']:.2f})")

        # Strong emotion
        if analysis['speech_emotion']:
            emotion = analysis['speech_emotion']['emotion']
            confidence = analysis['speech_emotion']['confidence']
            if emotion in ['happy', 'surprised', 'angry'] and confidence > 0.7:
                is_highlight = True
                highlight_type = 'emotional'
                reason.append(f"Strong {emotion} ({confidence:.2f})")

        # Interesting events
        interesting_events = ['laughter', 'applause', 'cheering', 'screaming', 'music']
        detected_interesting = [
            e['event_type'] for e in analysis['audio_events']
            if e['event_type'] in interesting_events and e['confidence'] > 0.5
        ]
        if detected_interesting:
            is_highlight = True
            highlight_type = 'event'
            reason.append(f"Events: {', '.join(detected_interesting)}")

        if is_highlight:
            highlights.append({
                'start': current_time,
                'end': end_time,
                'type': highlight_type,
                'reason': ' | '.join(reason),
                'energy': analysis['energy_level'],
                'events': get_simplified_events(analysis['audio_events'], top_n=3)
            })

        current_time = end_time

    return highlights


# ============================================================================
# Example 3: Content Categorization
# ============================================================================

def categorize_video_content(
    audio_path: str,
    duration: float,
    sample_interval: float = 10.0
) -> Dict[str, float]:
    """
    Categorize video content based on audio analysis.

    Args:
        audio_path: Path to audio file
        duration: Total duration in seconds
        sample_interval: Interval between samples

    Returns:
        Dictionary with content categories and percentages
    """
    categories = {
        'speech': 0,
        'music': 0,
        'laughter': 0,
        'ambient': 0,
        'silence': 0
    }

    total_samples = 0
    current_time = 0.0

    while current_time < duration:
        end_time = min(current_time + sample_interval, duration)

        analysis = analyze_audio_segment(
            audio_path,
            current_time,
            end_time,
            threshold=0.2
        )

        total_samples += 1

        # Categorize based on dominant content
        if analysis['has_speech']:
            categories['speech'] += 1
        elif analysis['energy_level'] < 0.1:
            categories['silence'] += 1
        elif analysis['audio_events']:
            # Check for music
            if any(e['event_type'] == 'music' for e in analysis['audio_events']):
                categories['music'] += 1
            # Check for laughter
            elif any(e['event_type'] == 'laughter' for e in analysis['audio_events']):
                categories['laughter'] += 1
            else:
                categories['ambient'] += 1
        else:
            categories['ambient'] += 1

        current_time = end_time

    # Convert to percentages
    if total_samples > 0:
        return {k: (v / total_samples) * 100 for k, v in categories.items()}
    return categories


# ============================================================================
# Example 4: Emotion Timeline
# ============================================================================

def create_emotion_timeline(
    transcription_segments: List[Dict],
    audio_path: str
) -> List[Dict]:
    """
    Create a timeline of emotions throughout the video.

    Args:
        transcription_segments: Segments with timestamps
        audio_path: Path to audio file

    Returns:
        Timeline of emotion changes
    """
    timeline = []
    previous_emotion = None

    for segment in transcription_segments:
        analysis = analyze_audio_segment(
            audio_path,
            segment['start'],
            segment['end']
        )

        if analysis['speech_emotion']:
            current_emotion = analysis['speech_emotion']['emotion']
            confidence = analysis['speech_emotion']['confidence']

            # Only track if high confidence and emotion changed
            if confidence > 0.6 and current_emotion != previous_emotion:
                timeline.append({
                    'timestamp': segment['start'],
                    'emotion': current_emotion,
                    'confidence': confidence,
                    'text': segment.get('text', '')[:100]  # First 100 chars
                })
                previous_emotion = current_emotion

    return timeline


# ============================================================================
# Example 5: Silent Segment Detection
# ============================================================================

def detect_silent_segments(
    audio_path: str,
    duration: float,
    min_silence_duration: float = 2.0,
    energy_threshold: float = 0.1
) -> List[Dict]:
    """
    Detect silent or low-activity segments in audio.

    Useful for identifying editing points or dead air.

    Args:
        audio_path: Path to audio file
        duration: Total duration
        min_silence_duration: Minimum silence duration to report
        energy_threshold: Energy level below which is considered silent

    Returns:
        List of silent segments
    """
    silent_segments = []
    silence_start = None
    sample_interval = 1.0  # 1 second samples

    current_time = 0.0
    while current_time < duration:
        end_time = min(current_time + sample_interval, duration)

        analysis = analyze_audio_segment(
            audio_path,
            current_time,
            end_time,
            threshold=0.5
        )

        is_silent = (
            not analysis['has_speech'] and
            analysis['energy_level'] < energy_threshold
        )

        if is_silent:
            if silence_start is None:
                silence_start = current_time
        else:
            if silence_start is not None:
                silence_duration = current_time - silence_start
                if silence_duration >= min_silence_duration:
                    silent_segments.append({
                        'start': silence_start,
                        'end': current_time,
                        'duration': silence_duration
                    })
                silence_start = None

        current_time = end_time

    # Handle silence at the end
    if silence_start is not None:
        silence_duration = duration - silence_start
        if silence_duration >= min_silence_duration:
            silent_segments.append({
                'start': silence_start,
                'end': duration,
                'duration': silence_duration
            })

    return silent_segments


# ============================================================================
# Example 6: Quality Metrics
# ============================================================================

def calculate_audio_quality_metrics(
    audio_path: str,
    duration: float,
    sample_interval: float = 5.0
) -> Dict:
    """
    Calculate overall audio quality metrics.

    Args:
        audio_path: Path to audio file
        duration: Total duration
        sample_interval: Sampling interval

    Returns:
        Quality metrics dictionary
    """
    metrics = {
        'average_energy': 0.0,
        'speech_percentage': 0.0,
        'emotion_diversity': 0,
        'event_diversity': 0,
        'total_samples': 0
    }

    energy_sum = 0.0
    speech_count = 0
    emotions = set()
    events = set()

    current_time = 0.0
    while current_time < duration:
        end_time = min(current_time + sample_interval, duration)

        analysis = analyze_audio_segment(
            audio_path,
            current_time,
            end_time
        )

        metrics['total_samples'] += 1
        energy_sum += analysis['energy_level']

        if analysis['has_speech']:
            speech_count += 1

        if analysis['speech_emotion']:
            emotions.add(analysis['speech_emotion']['emotion'])

        for event in analysis['audio_events']:
            events.add(event['event_type'])

        current_time = end_time

    # Calculate final metrics
    if metrics['total_samples'] > 0:
        metrics['average_energy'] = energy_sum / metrics['total_samples']
        metrics['speech_percentage'] = (speech_count / metrics['total_samples']) * 100

    metrics['emotion_diversity'] = len(emotions)
    metrics['event_diversity'] = len(events)

    return metrics


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Example transcription segments (as would come from faster-whisper)
    sample_segments = [
        {'start': 0.0, 'end': 5.0, 'text': 'Hello everyone!', 'speaker': 'SPEAKER_00'},
        {'start': 5.5, 'end': 10.0, 'text': 'This is a great day.', 'speaker': 'SPEAKER_00'},
        {'start': 10.5, 'end': 15.0, 'text': 'Let me show you something.', 'speaker': 'SPEAKER_00'},
    ]

    audio_file = "sample_audio.wav"
    total_duration = 60.0  # 60 seconds

    print("Example 1: Enhanced Transcription")
    print("=" * 70)
    # enhanced = enhance_transcription_with_audio_analysis(sample_segments, audio_file)
    # for seg in enhanced:
    #     print(f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")
    #     print(f"  Emotion: {seg['audio_analysis']['emotion']}")
    #     print(f"  Events: {seg['audio_analysis']['top_events']}")
    #     print(f"  Energy: {seg['audio_analysis']['energy_level']:.2f}")
    print("(Uncomment code to run)")

    print("\nExample 2: Highlight Detection")
    print("=" * 70)
    # highlights = detect_video_highlights(audio_file, total_duration)
    # for i, h in enumerate(highlights, 1):
    #     print(f"{i}. [{h['start']:.1f}s - {h['end']:.1f}s] {h['type']}")
    #     print(f"   Reason: {h['reason']}")
    print("(Uncomment code to run)")

    print("\nExample 3: Content Categorization")
    print("=" * 70)
    # categories = categorize_video_content(audio_file, total_duration)
    # for category, percentage in categories.items():
    #     print(f"{category:15s}: {percentage:5.1f}%")
    print("(Uncomment code to run)")

    print("\nExample 4: Emotion Timeline")
    print("=" * 70)
    # timeline = create_emotion_timeline(sample_segments, audio_file)
    # for event in timeline:
    #     print(f"[{event['timestamp']:.1f}s] {event['emotion']} ({event['confidence']:.2f})")
    #     print(f"   '{event['text']}'")
    print("(Uncomment code to run)")

    print("\nExample 5: Silent Segments")
    print("=" * 70)
    # silent = detect_silent_segments(audio_file, total_duration)
    # for seg in silent:
    #     print(f"Silence: {seg['start']:.1f}s - {seg['end']:.1f}s ({seg['duration']:.1f}s)")
    print("(Uncomment code to run)")

    print("\nExample 6: Quality Metrics")
    print("=" * 70)
    # metrics = calculate_audio_quality_metrics(audio_file, total_duration)
    # print(f"Average Energy: {metrics['average_energy']:.2f}")
    # print(f"Speech Coverage: {metrics['speech_percentage']:.1f}%")
    # print(f"Emotion Diversity: {metrics['emotion_diversity']} unique emotions")
    # print(f"Event Diversity: {metrics['event_diversity']} unique events")
    print("(Uncomment code to run)")

    print("\n" + "=" * 70)
    print("Note: Uncomment examples above with real audio file to test")
    print("=" * 70)
