"""
Audio Analysis Module for AI-Subs

This module provides advanced audio analysis capabilities including:
- Audio event detection using PANNs (Pretrained Audio Neural Networks)
- Speech emotion recognition using wav2vec2
- Energy level calculation using librosa

All models are lazy-loaded to avoid memory issues at startup.
"""

import os
import logging
import tempfile
import warnings
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import torch

# Suppress warnings from audio libraries
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# AudioSet Category Mapping
# ============================================================================

# Mapping from AudioSet classes to simplified event categories
AUDIOSET_CATEGORY_MAPPING = {
    # Emotional events
    "Laughter": "laughter",
    "Giggle": "laughter",
    "Chuckle, chortle": "laughter",
    "Belly laugh": "laughter",
    "Crying, sobbing": "crying",
    "Baby crying, infant cry": "crying",
    "Whimper": "crying",
    "Wail, moan": "crying",
    "Screaming": "screaming",
    "Scream": "screaming",
    "Shout": "screaming",
    "Yell": "screaming",
    "Sigh": "sigh",
    "Gasp": "gasp",
    "Snicker": "laughter",

    # Ambient events
    "Applause": "applause",
    "Clapping": "applause",
    "Cheering": "cheering",
    "Cheer": "cheering",
    "Music": "music",
    "Musical instrument": "music",
    "Singing": "music",
    "Piano": "music",
    "Guitar": "music",
    "Drum": "music",
    "Door": "door",
    "Knock": "knock",
    "Slam": "door",
    "Footsteps": "footsteps",
    "Walk, footsteps": "footsteps",
    "Run": "footsteps",
    "Silence": "silence",
    "Background noise": "ambient",

    # Speech-related
    "Speech": "speech",
    "Male speech, man speaking": "speech",
    "Female speech, woman speaking": "speech",
    "Child speech, kid speaking": "speech",
    "Conversation": "conversation",
    "Narration, monologue": "narration",
    "Speech synthesizer": "speech",
    "Whispering": "speech",
    "Shouting": "speech",

    # Other common events
    "Gunshot, gunfire": "gunshot",
    "Explosion": "explosion",
    "Glass": "glass",
    "Breaking": "breaking",
    "Crash": "crash",
    "Thunder": "thunder",
    "Rain": "rain",
    "Wind": "wind",
    "Fire": "fire",
    "Siren": "siren",
    "Car": "vehicle",
    "Vehicle": "vehicle",
    "Aircraft": "vehicle",
    "Train": "vehicle",
    "Dog": "animal",
    "Cat": "animal",
    "Bird": "animal",
    "Roar": "animal",
    "Bark": "animal",
    "Meow": "animal",
    "Chirp, tweet": "animal",
}


@dataclass
class AudioEvent:
    """Represents a detected audio event"""
    event_type: str
    confidence: float
    original_label: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SpeechEmotion:
    """Represents detected speech emotion"""
    emotion: str
    confidence: float
    all_emotions: Dict[str, float]

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AudioAnalysisResult:
    """Complete audio analysis result"""
    has_speech: bool
    audio_events: List[Dict]
    speech_emotion: Optional[Dict]
    energy_level: float
    duration: float

    def to_dict(self) -> Dict:
        return {
            "has_speech": self.has_speech,
            "audio_events": self.audio_events,
            "speech_emotion": self.speech_emotion,
            "energy_level": self.energy_level,
            "duration": self.duration
        }


# ============================================================================
# Model Manager - Handles lazy loading of models
# ============================================================================

class ModelManager:
    """Manages lazy loading and caching of audio analysis models"""

    _panns_model = None
    _emotion_model = None
    _emotion_processor = None
    _librosa = None
    _soundfile = None

    @classmethod
    def get_panns_model(cls):
        """Lazy load PANNs model for audio event detection"""
        if cls._panns_model is None:
            try:
                logger.info("Loading PANNs model for audio event detection...")
                import panns_inference
                from panns_inference import AudioTagging

                # Initialize the model (will download if not cached)
                cls._panns_model = AudioTagging(checkpoint_path=None, device='cuda' if torch.cuda.is_available() else 'cpu')
                logger.info("PANNs model loaded successfully")
            except ImportError:
                logger.error("panns_inference not installed. Install with: pip install panns-inference")
                raise
            except Exception as e:
                logger.error(f"Failed to load PANNs model: {e}")
                raise

        return cls._panns_model

    @classmethod
    def get_emotion_model(cls):
        """Lazy load wav2vec2 emotion recognition model"""
        if cls._emotion_model is None or cls._emotion_processor is None:
            try:
                logger.info("Loading wav2vec2 emotion model...")
                from transformers import AutoModelForAudioClassification, AutoFeatureExtractor

                # Using a popular emotion recognition model
                model_name = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"

                logger.info(f"Loading feature extractor from {model_name}...")
                cls._emotion_processor = AutoFeatureExtractor.from_pretrained(model_name)

                logger.info(f"Loading model from {model_name}...")
                cls._emotion_model = AutoModelForAudioClassification.from_pretrained(model_name)

                # Move to GPU if available
                if torch.cuda.is_available():
                    logger.info("Moving emotion model to GPU...")
                    cls._emotion_model = cls._emotion_model.cuda()

                cls._emotion_model.eval()
                logger.info("Emotion model loaded successfully")
            except ImportError as e:
                logger.error(f"transformers not installed. Install with: pip install transformers - Error: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to load emotion model: {e}", exc_info=True)
                raise

        return cls._emotion_model, cls._emotion_processor

    @classmethod
    def get_librosa(cls):
        """Lazy load librosa library"""
        if cls._librosa is None:
            try:
                import librosa
                cls._librosa = librosa
            except ImportError:
                logger.error("librosa not installed. Install with: pip install librosa")
                raise
        return cls._librosa

    @classmethod
    def get_soundfile(cls):
        """Lazy load soundfile library"""
        if cls._soundfile is None:
            try:
                import soundfile
                cls._soundfile = soundfile
            except ImportError:
                logger.error("soundfile not installed. Install with: pip install soundfile")
                raise
        return cls._soundfile


# ============================================================================
# Audio Event Detection using PANNs
# ============================================================================

def detect_audio_events(audio_path: str, threshold: float = 0.3) -> List[AudioEvent]:
    """
    Detect audio events using PANNs model.

    Args:
        audio_path: Path to the audio file
        threshold: Confidence threshold for event detection (0-1)

    Returns:
        List of detected AudioEvent objects

    Raises:
        Exception: If model loading or inference fails
    """
    try:
        model = ModelManager.get_panns_model()
        librosa = ModelManager.get_librosa()

        # Load audio file - PANNs expects numpy array at 32000 Hz
        audio_data, _ = librosa.load(audio_path, sr=32000, mono=True)

        # PANNs expects shape (batch_size, samples), so add batch dimension
        audio_data = audio_data[np.newaxis, :]

        # Run inference
        clipwise_output, _ = model.inference(audio_data)

        # Get the labels (527 AudioSet classes)
        labels = model.labels

        # Find events above threshold
        detected_events = []
        for idx, confidence in enumerate(clipwise_output[0]):
            if confidence >= threshold:
                original_label = labels[idx]
                # Map to simplified category
                event_type = AUDIOSET_CATEGORY_MAPPING.get(original_label, "other")

                detected_events.append(AudioEvent(
                    event_type=event_type,
                    confidence=float(confidence),
                    original_label=original_label
                ))

        # Sort by confidence
        detected_events.sort(key=lambda x: x.confidence, reverse=True)

        logger.info(f"Detected {len(detected_events)} audio events above threshold {threshold}")
        return detected_events

    except Exception as e:
        logger.error(f"Error detecting audio events: {e}")
        # Return empty list instead of crashing
        return []


# ============================================================================
# Speech Emotion Recognition using wav2vec2
# ============================================================================

def detect_speech_emotion(audio_path: str) -> Optional[SpeechEmotion]:
    """
    Detect emotion in speech using wav2vec2 model.

    Args:
        audio_path: Path to the audio file

    Returns:
        SpeechEmotion object or None if detection fails

    Raises:
        Exception: If model loading fails (caught internally)
    """
    try:
        model, feature_extractor = ModelManager.get_emotion_model()
        librosa = ModelManager.get_librosa()

        # Load audio file at 16kHz (required for wav2vec2)
        speech, sampling_rate = librosa.load(audio_path, sr=16000)

        # Ensure audio is not empty
        if len(speech) == 0:
            logger.warning("Empty audio segment, cannot detect emotion")
            return None

        # Process audio with feature extractor
        inputs = feature_extractor(
            speech,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True
        )

        # Move to GPU if available
        if torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        # Run inference
        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits

        # Get probabilities
        probabilities = torch.nn.functional.softmax(logits, dim=-1)
        probabilities = probabilities.cpu().numpy()[0]

        # Emotion labels for this specific model
        # Based on: ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition
        emotion_labels = ['angry', 'calm', 'disgust', 'fearful', 'happy', 'neutral', 'sad', 'surprised']

        # Ensure we have the right number of labels
        if len(probabilities) != len(emotion_labels):
            logger.warning(f"Mismatch between probabilities ({len(probabilities)}) and labels ({len(emotion_labels)})")
            # Adjust labels if needed
            emotion_labels = [f"emotion_{i}" for i in range(len(probabilities))]

        # Create emotion dictionary
        all_emotions = {emotion_labels[i]: float(probabilities[i]) for i in range(len(probabilities))}

        # Get dominant emotion
        dominant_emotion_idx = np.argmax(probabilities)
        dominant_emotion = emotion_labels[dominant_emotion_idx]
        confidence = float(probabilities[dominant_emotion_idx])

        logger.info(f"Detected emotion: {dominant_emotion} (confidence: {confidence:.2f})")

        return SpeechEmotion(
            emotion=dominant_emotion,
            confidence=confidence,
            all_emotions=all_emotions
        )

    except Exception as e:
        logger.error(f"Error detecting speech emotion: {e}", exc_info=True)
        # Return None instead of crashing
        return None


# ============================================================================
# Energy Level Calculation
# ============================================================================

def calculate_energy_level(audio_path: str) -> float:
    """
    Calculate the energy level of an audio segment.

    Uses RMS (Root Mean Square) energy normalized to 0-1 range.

    Args:
        audio_path: Path to the audio file

    Returns:
        Energy level between 0 and 1

    Raises:
        Exception: If audio loading fails (caught internally)
    """
    try:
        librosa = ModelManager.get_librosa()

        # Load audio
        y, sr = librosa.load(audio_path, sr=None)

        # Calculate RMS energy
        rms = librosa.feature.rms(y=y)[0]

        # Get mean energy
        mean_energy = np.mean(rms)

        # Normalize to 0-1 range (assuming max RMS of 0.5 for normalization)
        # This is a heuristic - adjust based on your audio characteristics
        normalized_energy = min(mean_energy / 0.5, 1.0)

        logger.debug(f"Calculated energy level: {normalized_energy:.3f}")
        return float(normalized_energy)

    except Exception as e:
        logger.error(f"Error calculating energy level: {e}")
        # Return 0 instead of crashing
        return 0.0


# ============================================================================
# Audio Segment Extraction
# ============================================================================

def extract_audio_segment(audio_path: str, start: float, end: float) -> Optional[str]:
    """
    Extract a segment from an audio file.

    Args:
        audio_path: Path to the source audio file
        start: Start time in seconds
        end: End time in seconds

    Returns:
        Path to the extracted segment (temporary file) or None if extraction fails

    Raises:
        Exception: If extraction fails (caught internally)
    """
    try:
        librosa = ModelManager.get_librosa()
        soundfile = ModelManager.get_soundfile()

        # Load the full audio file
        y, sr = librosa.load(audio_path, sr=None)

        # Convert time to samples
        start_sample = int(start * sr)
        end_sample = int(end * sr)

        # Extract segment
        segment = y[start_sample:end_sample]

        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        soundfile.write(temp_file.name, segment, sr)

        logger.debug(f"Extracted segment from {start}s to {end}s -> {temp_file.name}")
        return temp_file.name

    except Exception as e:
        logger.error(f"Error extracting audio segment: {e}")
        return None


# ============================================================================
# Main Analysis Function
# ============================================================================

def analyze_audio_segment(
    audio_path: str,
    start: float,
    end: float,
    threshold: float = 0.3
) -> Dict:
    """
    Perform comprehensive audio analysis on a segment.

    This is the main function that orchestrates all audio analysis:
    - Audio event detection using PANNs
    - Speech emotion recognition using wav2vec2
    - Energy level calculation using librosa

    Args:
        audio_path: Path to the audio file
        start: Start time in seconds
        end: End time in seconds
        threshold: Confidence threshold for event detection (default: 0.3)

    Returns:
        Dictionary containing:
        {
            "has_speech": bool,
            "audio_events": [{"event_type": str, "confidence": float, "original_label": str}],
            "speech_emotion": {"emotion": str, "confidence": float, "all_emotions": dict} or None,
            "energy_level": float (0-1),
            "duration": float
        }

    Example:
        >>> result = analyze_audio_segment("audio.wav", 0.0, 5.0)
        >>> print(f"Speech detected: {result['has_speech']}")
        >>> print(f"Energy level: {result['energy_level']:.2f}")
        >>> for event in result['audio_events']:
        ...     print(f"Event: {event['event_type']} ({event['confidence']:.2f})")

    Notes:
        - Models are lazy-loaded on first use
        - Errors in individual components don't crash the entire analysis
        - Returns partial results if some components fail
        - Temporary segment file is automatically cleaned up
    """
    logger.info(f"Analyzing audio segment: {audio_path} [{start}s - {end}s]")

    segment_path = None
    try:
        # Calculate duration
        duration = end - start

        # Extract the audio segment if start/end are specified
        if start > 0 or end < float('inf'):
            segment_path = extract_audio_segment(audio_path, start, end)
            if segment_path is None:
                logger.error("Failed to extract audio segment, using full audio file")
                segment_path = audio_path
        else:
            segment_path = audio_path

        # Detect audio events
        audio_events = detect_audio_events(segment_path, threshold)

        # Check if speech is detected
        has_speech = any(event.event_type in ['speech', 'conversation', 'narration']
                        for event in audio_events)

        # Detect speech emotion (only if speech is detected)
        speech_emotion = None
        if has_speech:
            emotion_result = detect_speech_emotion(segment_path)
            if emotion_result:
                speech_emotion = emotion_result.to_dict()

        # Calculate energy level
        energy_level = calculate_energy_level(segment_path)

        # Build result
        result = AudioAnalysisResult(
            has_speech=has_speech,
            audio_events=[event.to_dict() for event in audio_events],
            speech_emotion=speech_emotion,
            energy_level=energy_level,
            duration=duration
        )

        logger.info(f"Analysis complete: {len(audio_events)} events, "
                   f"speech={has_speech}, energy={energy_level:.2f}")

        return result.to_dict()

    except Exception as e:
        logger.error(f"Error in analyze_audio_segment: {e}", exc_info=True)
        # Return minimal result on error
        return {
            "has_speech": False,
            "audio_events": [],
            "speech_emotion": None,
            "energy_level": 0.0,
            "duration": end - start
        }

    finally:
        # Clean up temporary segment file
        if segment_path and segment_path != audio_path and os.path.exists(segment_path):
            try:
                os.unlink(segment_path)
                logger.debug(f"Cleaned up temporary segment: {segment_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file {segment_path}: {e}")


# ============================================================================
# Utility Functions
# ============================================================================

def get_simplified_events(audio_events: List[Dict], top_n: int = 5) -> List[str]:
    """
    Get simplified list of top N event types from analysis results.

    Args:
        audio_events: List of audio events from analysis
        top_n: Number of top events to return

    Returns:
        List of event type strings
    """
    if not audio_events:
        return []

    # Sort by confidence and get top N unique event types
    sorted_events = sorted(audio_events, key=lambda x: x['confidence'], reverse=True)
    seen_types = set()
    result = []

    for event in sorted_events:
        event_type = event['event_type']
        if event_type not in seen_types and event_type != 'other':
            seen_types.add(event_type)
            result.append(event_type)
            if len(result) >= top_n:
                break

    return result


def format_analysis_summary(analysis_result: Dict) -> str:
    """
    Format analysis result as a human-readable summary.

    Args:
        analysis_result: Result from analyze_audio_segment

    Returns:
        Formatted string summary
    """
    lines = []
    lines.append(f"Duration: {analysis_result['duration']:.2f}s")
    lines.append(f"Energy Level: {analysis_result['energy_level']:.2f}")
    lines.append(f"Speech Detected: {analysis_result['has_speech']}")

    if analysis_result['speech_emotion']:
        emotion = analysis_result['speech_emotion']
        lines.append(f"Emotion: {emotion['emotion']} ({emotion['confidence']:.2f})")

    if analysis_result['audio_events']:
        top_events = get_simplified_events(analysis_result['audio_events'], top_n=3)
        lines.append(f"Top Events: {', '.join(top_events)}")

    return "\n".join(lines)


# ============================================================================
# AudioAnalyzer Class (Wrapper for dependency injection)
# ============================================================================

class AudioAnalyzer:
    """
    Audio analyzer class for dependency injection compatibility.

    This class wraps the module-level functions to provide a class-based
    interface that can be used with FastAPI's dependency injection system.
    """

    def __init__(self):
        """Initialize the audio analyzer."""
        logger.info("AudioAnalyzer initialized")

    def analyze_segment(
        self,
        audio_path: str,
        start: float,
        end: float,
        threshold: float = 0.3
    ) -> Dict:
        """
        Analyze an audio segment.

        Args:
            audio_path: Path to the audio file
            start: Start time in seconds
            end: End time in seconds
            threshold: Confidence threshold for event detection

        Returns:
            Dictionary with analysis results
        """
        return analyze_audio_segment(audio_path, start, end, threshold)

    def get_simplified_events(self, audio_events: List[Dict], top_n: int = 5) -> List[str]:
        """Get simplified list of top N event types."""
        return get_simplified_events(audio_events, top_n)

    def format_summary(self, analysis_result: Dict) -> str:
        """Format analysis result as a human-readable summary."""
        return format_analysis_summary(analysis_result)


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python audio_analyzer.py <audio_file> [start_time] [end_time]")
        sys.exit(1)

    audio_file = sys.argv[1]
    start_time = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    end_time = float(sys.argv[3]) if len(sys.argv) > 3 else float('inf')

    # Run analysis
    result = analyze_audio_segment(audio_file, start_time, end_time)

    # Print results
    print("\n" + "="*60)
    print("AUDIO ANALYSIS RESULTS")
    print("="*60)
    print(format_analysis_summary(result))
    print("="*60)

    # Print detailed events
    if result['audio_events']:
        print("\nDetailed Events:")
        for event in result['audio_events'][:10]:  # Top 10
            print(f"  - {event['original_label']:40s} ({event['event_type']:15s}) {event['confidence']:.3f}")

    # Print all emotions
    if result['speech_emotion']:
        print("\nAll Emotions:")
        for emotion, conf in result['speech_emotion']['all_emotions'].items():
            print(f"  - {emotion:12s}: {conf:.3f}")
