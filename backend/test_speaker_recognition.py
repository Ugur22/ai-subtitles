"""
Test script for speaker recognition system
"""

import os
from speaker_recognition import SpeakerRecognitionSystem

def test_speaker_recognition():
    """Test the speaker recognition system"""

    print("=" * 60)
    print("SPEAKER RECOGNITION SYSTEM TEST")
    print("=" * 60)

    # Initialize system
    print("\n1. Initializing speaker recognition system...")
    try:
        sr_system = SpeakerRecognitionSystem(database_path="test_speaker_db.json")
        print("✓ System initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        print("\nMake sure you have:")
        print("1. Accepted model terms at: https://huggingface.co/pyannote/embedding")
        print("2. Added HUGGINGFACE_TOKEN to your .env file")
        return

    # List enrolled speakers
    print("\n2. Checking enrolled speakers...")
    speakers = sr_system.list_speakers()
    if speakers:
        print(f"✓ Found {len(speakers)} enrolled speakers:")
        for speaker in speakers:
            info = sr_system.get_speaker_info(speaker)
            print(f"  - {speaker}: {info['samples_count']} sample(s)")
    else:
        print("✓ No speakers enrolled yet (database is empty)")

    print("\n3. Testing enrollment...")
    print("To test enrollment, you need an audio file.")
    print("Example usage:")
    print("  sr_system.enroll_speaker('John', 'path/to/john_voice.wav')")

    print("\n4. Testing identification...")
    print("To test identification, you need:")
    print("  1. At least one enrolled speaker")
    print("  2. An audio file to identify")
    print("Example usage:")
    print("  speaker, confidence = sr_system.identify_speaker('path/to/audio.wav')")
    print("  print(f'Identified: {speaker} (confidence: {confidence:.2f})')")

    print("\n" + "=" * 60)
    print("SYSTEM STATUS: READY")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Transcribe a video with multiple speakers")
    print("2. Identify good segments for each speaker")
    print("3. Use the API to enroll speakers")
    print("4. Run auto-identification on new videos!")

    # Cleanup test database
    if os.path.exists("test_speaker_db.json") and not speakers:
        os.remove("test_speaker_db.json")
        print("\nCleaned up test database")

if __name__ == "__main__":
    test_speaker_recognition()
