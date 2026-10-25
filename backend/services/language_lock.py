"""Pick one spoken language for a whole file so chunked Whisper runs can't drift."""
from collections import defaultdict
from typing import Iterable, List, Optional, Tuple

MAX_SAMPLED_CHUNKS = 8
MIN_CONFIDENCE = 0.5


def pick_dominant_language(votes: Iterable[Tuple[str, float]]) -> Optional[str]:
    """Return the language with the highest summed probability, ignoring weak votes."""
    totals = defaultdict(float)
    for lang, prob in votes:
        if lang and prob >= MIN_CONFIDENCE:
            totals[lang] += prob
    if not totals:
        return None
    return max(totals, key=totals.get)


def _sample_chunks(chunks: List[str]) -> List[str]:
    if len(chunks) <= MAX_SAMPLED_CHUNKS:
        return list(chunks)
    step = len(chunks) / MAX_SAMPLED_CHUNKS
    return [chunks[int(i * step)] for i in range(MAX_SAMPLED_CHUNKS)]


def detect_dominant_language(whisper_model, audio_chunks: List[str], vad_parameters: dict) -> Optional[str]:
    """Vote on language across evenly spaced chunks.

    VAD is applied so music/silence-only openings (which make Whisper guess
    English) don't outvote the actual dialogue.
    """
    from faster_whisper import decode_audio
    from faster_whisper.vad import VadOptions

    # transcribe() accepts a dict, but detect_language() reads attributes off it.
    vad_options = VadOptions(**vad_parameters)
    votes = []
    for path in _sample_chunks(audio_chunks):
        try:
            lang, prob, _ = whisper_model.detect_language(
                decode_audio(path),
                vad_filter=True,
                vad_parameters=vad_options,
                language_detection_segments=3,
            )
            votes.append((lang, prob))
        except Exception as e:
            print(f"[LanguageLock] Detection failed for {path}: {e}")
    print(f"[LanguageLock] Votes: {votes}")
    return pick_dominant_language(votes)
