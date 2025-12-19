"""
Test script for audio_analyzer module

This script demonstrates how to use the audio analyzer in the AI-Subs application.
"""

import sys
import json
from pathlib import Path

# Import the audio analyzer
from audio_analyzer import (
    analyze_audio_segment,
    format_analysis_summary,
    get_simplified_events
)


def test_basic_analysis(audio_path: str, start: float = 0.0, end: float = None):
    """Test basic audio analysis functionality"""
    print(f"\n{'='*70}")
    print(f"Testing Audio Analyzer")
    print(f"{'='*70}")
    print(f"Audio file: {audio_path}")
    print(f"Time range: {start}s to {end if end else 'end'}s")
    print(f"{'='*70}\n")

    # If end time not specified, use a large value
    if end is None:
        end = float('inf')

    # Run analysis with default threshold
    print("Running analysis with threshold=0.3...")
    result = analyze_audio_segment(audio_path, start, end, threshold=0.3)

    # Print formatted summary
    print("\n" + "="*70)
    print("ANALYSIS SUMMARY")
    print("="*70)
    print(format_analysis_summary(result))
    print("="*70)

    # Print detailed results
    print("\n" + "="*70)
    print("DETAILED RESULTS")
    print("="*70)

    # Speech detection
    print(f"\nSpeech Detected: {result['has_speech']}")

    # Emotion analysis
    if result['speech_emotion']:
        emotion = result['speech_emotion']
        print(f"\nDominant Emotion: {emotion['emotion']} (confidence: {emotion['confidence']:.2f})")
        print("\nAll Emotions:")
        for emo, conf in sorted(emotion['all_emotions'].items(), key=lambda x: x[1], reverse=True):
            bar = '█' * int(conf * 40)
            print(f"  {emo:12s}: {conf:.3f} {bar}")
    else:
        print("\nNo speech emotion detected (likely no speech in segment)")

    # Audio events
    if result['audio_events']:
        print(f"\nDetected {len(result['audio_events'])} audio events:")
        print("\nTop 10 Events:")
        for i, event in enumerate(result['audio_events'][:10], 1):
            bar = '█' * int(event['confidence'] * 40)
            print(f"  {i:2d}. {event['original_label']:45s} ({event['event_type']:15s}) {event['confidence']:.3f} {bar}")

        # Get simplified event list
        top_events = get_simplified_events(result['audio_events'], top_n=5)
        print(f"\nTop 5 Simplified Events: {', '.join(top_events)}")
    else:
        print("\nNo audio events detected above threshold")

    # Energy level
    print(f"\nEnergy Level: {result['energy_level']:.3f}")
    energy_bar = '█' * int(result['energy_level'] * 50)
    print(f"Energy: {energy_bar}")

    # Save to JSON for inspection
    output_file = Path(audio_path).stem + "_analysis.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\nFull results saved to: {output_file}")

    return result


def test_multiple_thresholds(audio_path: str, start: float = 0.0, end: float = None):
    """Test with different confidence thresholds"""
    print(f"\n{'='*70}")
    print(f"Testing Multiple Thresholds")
    print(f"{'='*70}\n")

    if end is None:
        end = float('inf')

    thresholds = [0.1, 0.3, 0.5, 0.7]

    for threshold in thresholds:
        print(f"\nThreshold: {threshold}")
        result = analyze_audio_segment(audio_path, start, end, threshold=threshold)
        event_count = len(result['audio_events'])
        top_events = get_simplified_events(result['audio_events'], top_n=3)
        print(f"  Events detected: {event_count}")
        print(f"  Top events: {', '.join(top_events) if top_events else 'None'}")


def test_segment_analysis(audio_path: str, segment_duration: float = 5.0):
    """Test analysis on multiple segments"""
    print(f"\n{'='*70}")
    print(f"Testing Segment Analysis (analyzing {segment_duration}s segments)")
    print(f"{'='*70}\n")

    # Analyze first few segments
    num_segments = 3
    for i in range(num_segments):
        start = i * segment_duration
        end = (i + 1) * segment_duration

        print(f"\nSegment {i+1}: {start}s - {end}s")
        print("-" * 70)

        result = analyze_audio_segment(audio_path, start, end, threshold=0.3)

        # Print compact summary
        print(f"  Speech: {'Yes' if result['has_speech'] else 'No':3s} | "
              f"Energy: {result['energy_level']:.2f} | "
              f"Events: {len(result['audio_events'])}")

        if result['speech_emotion']:
            print(f"  Emotion: {result['speech_emotion']['emotion']} "
                  f"({result['speech_emotion']['confidence']:.2f})")

        if result['audio_events']:
            top_events = get_simplified_events(result['audio_events'], top_n=3)
            print(f"  Top events: {', '.join(top_events)}")


def main():
    """Main test function"""
    if len(sys.argv) < 2:
        print("Usage: python test_audio_analyzer.py <audio_file> [start_time] [end_time]")
        print("\nExample:")
        print("  python test_audio_analyzer.py sample.wav")
        print("  python test_audio_analyzer.py sample.wav 10 20")
        print("  python test_audio_analyzer.py sample.wav 0 5")
        sys.exit(1)

    audio_file = sys.argv[1]
    start_time = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    end_time = float(sys.argv[3]) if len(sys.argv) > 3 else None

    # Check if file exists
    if not Path(audio_file).exists():
        print(f"Error: Audio file not found: {audio_file}")
        sys.exit(1)

    try:
        # Run basic analysis
        result = test_basic_analysis(audio_file, start_time, end_time)

        # Optionally run additional tests
        print("\n" + "="*70)
        response = input("\nRun threshold comparison tests? (y/n): ")
        if response.lower() == 'y':
            test_multiple_thresholds(audio_file, start_time, end_time)

        print("\n" + "="*70)
        response = input("\nRun segment analysis tests? (y/n): ")
        if response.lower() == 'y':
            test_segment_analysis(audio_file, segment_duration=5.0)

        print("\n" + "="*70)
        print("Testing complete!")
        print("="*70 + "\n")

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
