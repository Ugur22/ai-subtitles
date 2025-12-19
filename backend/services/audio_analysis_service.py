"""
Audio analysis service for enhanced transcription segments
"""
import os
import traceback
from typing import List, Dict, Optional
from collections import Counter

from config import settings

try:
    from audio_analyzer import analyze_audio_segment, get_simplified_events
    AUDIO_ANALYZER_AVAILABLE = True
except ImportError:
    AUDIO_ANALYZER_AVAILABLE = False


class AudioAnalysisService:
    """Service for audio analysis operations on transcription segments"""

    @staticmethod
    def analyze_segments(
        audio_path: str,
        segments: List[Dict],
        video_hash: str,
        threshold: Optional[float] = None
    ) -> List[Dict]:
        """
        Enrich transcription segments with audio analysis data.

        This method takes transcription segments and adds audio event detection,
        speech emotion recognition, and energy level analysis to each segment.

        Args:
            audio_path: Path to the audio file
            segments: List of transcription segments (dicts with 'start', 'end', 'text', etc.)
            video_hash: Hash identifier for the video (for logging/debugging)
            threshold: Optional confidence threshold for event detection (default from settings)

        Returns:
            List of segments enriched with audio analysis fields:
            - audio_events: List of detected audio events
            - speech_emotion: Detected emotion in speech (if any)
            - energy_level: Audio energy level (0-1)
            - audio_analysis: Full analysis result dict

        Notes:
            - Respects ENABLE_AUDIO_ANALYSIS setting
            - Handles errors gracefully on a per-segment basis
            - Failed segments get empty/default audio analysis fields
        """
        # Check if audio analysis is enabled
        if not settings.ENABLE_AUDIO_ANALYSIS:
            print("Audio analysis disabled in settings, skipping...")
            return segments

        if not AUDIO_ANALYZER_AVAILABLE:
            print("Audio analyzer module not available, skipping audio analysis...")
            return segments

        if not audio_path or not os.path.exists(audio_path):
            print(f"Audio file not found: {audio_path}, skipping audio analysis...")
            return segments

        print(f"\n{'='*60}")
        print(f"Starting audio analysis for {len(segments)} segments...")
        print(f"Video hash: {video_hash}")
        print(f"Audio path: {audio_path}")
        print(f"{'='*60}")

        # Use threshold from settings if not provided
        if threshold is None:
            threshold = settings.AUDIO_EVENT_THRESHOLD

        enriched_segments = []
        successful_analyses = 0
        failed_analyses = 0

        for idx, segment in enumerate(segments):
            try:
                # Extract segment timing
                start = segment.get('start', 0)
                end = segment.get('end', 0)

                if start >= end:
                    print(f"Warning: Invalid segment timing for segment {idx}: start={start}, end={end}")
                    # Add empty analysis
                    segment['audio_events'] = []
                    segment['speech_emotion'] = None
                    segment['energy_level'] = 0.0
                    segment['audio_analysis'] = None
                    enriched_segments.append(segment)
                    failed_analyses += 1
                    continue

                # Perform audio analysis
                analysis_result = analyze_audio_segment(
                    audio_path=audio_path,
                    start=start,
                    end=end,
                    threshold=threshold
                )

                # Add analysis fields to segment
                segment['audio_events'] = analysis_result.get('audio_events', [])
                segment['speech_emotion'] = analysis_result.get('speech_emotion')
                segment['energy_level'] = analysis_result.get('energy_level', 0.0)
                segment['audio_analysis'] = analysis_result

                enriched_segments.append(segment)
                successful_analyses += 1

                # Log progress every 10 segments
                if (idx + 1) % 10 == 0:
                    print(f"Progress: Analyzed {idx + 1}/{len(segments)} segments...")

            except Exception as e:
                print(f"Error analyzing segment {idx} (start={segment.get('start')}, end={segment.get('end')}): {str(e)}")
                traceback.print_exc()

                # Add empty analysis on error
                segment['audio_events'] = []
                segment['speech_emotion'] = None
                segment['energy_level'] = 0.0
                segment['audio_analysis'] = None
                enriched_segments.append(segment)
                failed_analyses += 1

        # Print summary statistics
        print(f"\n{'='*60}")
        print(f"Audio analysis complete!")
        print(f"Successful: {successful_analyses}/{len(segments)} segments")
        print(f"Failed: {failed_analyses}/{len(segments)} segments")
        print(f"{'='*60}\n")

        return enriched_segments

    @staticmethod
    def analyze_silent_segments(
        audio_path: str,
        segments: List[Dict],
        threshold: Optional[float] = None
    ) -> List[Dict]:
        """
        Analyze segments marked as silent to detect ambient sounds.

        This method specifically targets segments that were marked as silent
        or containing no speech during transcription, and attempts to identify
        ambient sounds or background audio events in those segments.

        Args:
            audio_path: Path to the audio file
            segments: List of transcription segments
            threshold: Optional confidence threshold for event detection (default from settings)

        Returns:
            List of segments with updated speaker labels and audio events for silent segments

        Notes:
            - Only processes segments with is_silent=True or text="[No speech]"
            - Updates speaker to "AMBIENT" if no speech detected
            - Adds ambient audio events to segment data
            - Respects ENABLE_AUDIO_ANALYSIS setting
        """
        # Check if audio analysis is enabled
        if not settings.ENABLE_AUDIO_ANALYSIS:
            print("Audio analysis disabled in settings, skipping silent segment analysis...")
            return segments

        if not AUDIO_ANALYZER_AVAILABLE:
            print("Audio analyzer module not available, skipping silent segment analysis...")
            return segments

        if not audio_path or not os.path.exists(audio_path):
            print(f"Audio file not found: {audio_path}, skipping silent segment analysis...")
            return segments

        # Use threshold from settings if not provided
        if threshold is None:
            threshold = settings.AUDIO_EVENT_THRESHOLD

        # Find silent segments
        silent_segments = [
            (idx, seg) for idx, seg in enumerate(segments)
            if seg.get('is_silent', False) or seg.get('text', '').strip() == '[No speech]'
        ]

        if not silent_segments:
            print("No silent segments found, skipping silent segment analysis...")
            return segments

        print(f"\n{'='*60}")
        print(f"Analyzing {len(silent_segments)} silent segments for ambient sounds...")
        print(f"{'='*60}")

        processed_count = 0

        for idx, segment in silent_segments:
            try:
                start = segment.get('start', 0)
                end = segment.get('end', 0)

                if start >= end:
                    print(f"Warning: Invalid silent segment timing: start={start}, end={end}")
                    continue

                # Perform audio analysis
                analysis_result = analyze_audio_segment(
                    audio_path=audio_path,
                    start=start,
                    end=end,
                    threshold=threshold
                )

                # Check if speech was detected
                has_speech = analysis_result.get('has_speech', False)

                if not has_speech:
                    # Update speaker to AMBIENT
                    segment['speaker'] = "AMBIENT"

                    # Add audio events if not already present
                    if 'audio_events' not in segment or not segment['audio_events']:
                        segment['audio_events'] = analysis_result.get('audio_events', [])

                    # Add energy level if not already present
                    if 'energy_level' not in segment:
                        segment['energy_level'] = analysis_result.get('energy_level', 0.0)

                    # Get top ambient events for logging
                    events = get_simplified_events(segment['audio_events'], top_n=3)
                    if events:
                        print(f"Segment {idx}: Detected ambient sounds: {', '.join(events)}")

                processed_count += 1

            except Exception as e:
                print(f"Error analyzing silent segment {idx}: {str(e)}")
                traceback.print_exc()
                continue

        print(f"\n{'='*60}")
        print(f"Silent segment analysis complete!")
        print(f"Processed: {processed_count}/{len(silent_segments)} silent segments")
        print(f"{'='*60}\n")

        return segments

    @staticmethod
    def create_audio_summary(segments: List[Dict]) -> Dict:
        """
        Create a summary of audio events across all segments.

        Aggregates audio analysis data from all segments to provide
        an overview of the audio content in the entire transcription.

        Args:
            segments: List of transcription segments with audio analysis data

        Returns:
            Dictionary containing:
            - total_segments: Total number of segments
            - segments_with_audio_events: Number of segments with detected events
            - event_counts: Counter of event types across all segments
            - dominant_events: Top N most common event types
            - emotion_distribution: Distribution of speech emotions
            - dominant_emotions: Top N most common emotions
            - average_energy: Average energy level across all segments
            - high_energy_segments: Count of segments with high energy (>0.7)
            - low_energy_segments: Count of segments with low energy (<0.3)
            - speech_segments: Number of segments with detected speech
            - silent_segments: Number of segments with no speech

        Example:
            >>> summary = AudioAnalysisService.create_audio_summary(segments)
            >>> print(f"Dominant events: {summary['dominant_events']}")
            >>> print(f"Average energy: {summary['average_energy']:.2f}")
        """
        if not segments:
            return {
                'total_segments': 0,
                'segments_with_audio_events': 0,
                'event_counts': {},
                'dominant_events': [],
                'emotion_distribution': {},
                'dominant_emotions': [],
                'average_energy': 0.0,
                'high_energy_segments': 0,
                'low_energy_segments': 0,
                'speech_segments': 0,
                'silent_segments': 0
            }

        # Initialize counters
        event_counter = Counter()
        emotion_counter = Counter()
        total_energy = 0.0
        energy_count = 0
        high_energy_count = 0
        low_energy_count = 0
        speech_count = 0
        silent_count = 0
        segments_with_events = 0

        # Analyze each segment
        for segment in segments:
            # Count audio events
            audio_events = segment.get('audio_events', [])
            if audio_events:
                segments_with_events += 1
                for event in audio_events:
                    event_type = event.get('event_type', 'unknown')
                    event_counter[event_type] += 1

            # Count speech emotions
            speech_emotion = segment.get('speech_emotion')
            if speech_emotion:
                emotion = speech_emotion.get('emotion')
                if emotion:
                    emotion_counter[emotion] += 1

            # Aggregate energy levels
            energy_level = segment.get('energy_level', 0.0)
            if energy_level is not None:
                total_energy += energy_level
                energy_count += 1

                if energy_level > 0.7:
                    high_energy_count += 1
                elif energy_level < 0.3:
                    low_energy_count += 1

            # Count speech vs silent
            audio_analysis = segment.get('audio_analysis')
            if audio_analysis:
                if audio_analysis.get('has_speech', False):
                    speech_count += 1
                else:
                    silent_count += 1

        # Calculate averages and top items
        average_energy = total_energy / energy_count if energy_count > 0 else 0.0

        # Get top 5 events and emotions
        dominant_events = [
            {'event_type': event, 'count': count}
            for event, count in event_counter.most_common(5)
        ]

        dominant_emotions = [
            {'emotion': emotion, 'count': count}
            for emotion, count in emotion_counter.most_common(5)
        ]

        # Build summary
        summary = {
            'total_segments': len(segments),
            'segments_with_audio_events': segments_with_events,
            'event_counts': dict(event_counter),
            'dominant_events': dominant_events,
            'emotion_distribution': dict(emotion_counter),
            'dominant_emotions': dominant_emotions,
            'average_energy': round(average_energy, 3),
            'high_energy_segments': high_energy_count,
            'low_energy_segments': low_energy_count,
            'speech_segments': speech_count,
            'silent_segments': silent_count
        }

        # Print summary
        print(f"\n{'='*60}")
        print("Audio Analysis Summary")
        print(f"{'='*60}")
        print(f"Total segments: {summary['total_segments']}")
        print(f"Segments with audio events: {summary['segments_with_audio_events']}")
        print(f"Speech segments: {summary['speech_segments']}")
        print(f"Silent segments: {summary['silent_segments']}")
        print(f"Average energy: {summary['average_energy']:.3f}")
        print(f"High energy segments: {summary['high_energy_segments']}")
        print(f"Low energy segments: {summary['low_energy_segments']}")

        if dominant_events:
            print("\nTop audio events:")
            for item in dominant_events[:3]:
                print(f"  - {item['event_type']}: {item['count']} occurrences")

        if dominant_emotions:
            print("\nTop emotions:")
            for item in dominant_emotions[:3]:
                print(f"  - {item['emotion']}: {item['count']} occurrences")

        print(f"{'='*60}\n")

        return summary
