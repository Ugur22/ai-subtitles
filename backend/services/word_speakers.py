import re
import uuid
from typing import Dict, List, Optional

from utils.time_utils import format_timestamp

UNKNOWN_SPEAKER = "UNKNOWN"

MERGE_FRAGMENTS_UNDER_WORDS = 3
_SENTENCE_END = re.compile(r"[.?!…][\"'»”’)\]]*$")


def _overlap(start: float, end: float, turn: Dict) -> float:
    return max(0.0, min(end, turn["end"]) - max(start, turn["start"]))


def _line_speaker(segment: Dict, speaker_segments: List[Dict]) -> str:
    start = segment.get("start", 0.0)
    end = segment.get("end", 0.0)
    mid = (start + end) / 2
    best_speaker = UNKNOWN_SPEAKER
    max_overlap = 0.0
    for turn in speaker_segments:
        overlap = _overlap(start, end, turn)
        if overlap > max_overlap:
            max_overlap = overlap
            best_speaker = turn["speaker"]
        if turn["start"] <= mid <= turn["end"]:
            return turn["speaker"]
    return best_speaker


def _word_speaker(word: Dict, speaker_segments: List[Dict]) -> str:
    best: Optional[Dict] = None
    max_overlap = 0.0
    for turn in speaker_segments:
        overlap = _overlap(word["start"], word["end"], turn)
        if overlap > max_overlap:
            max_overlap = overlap
            best = turn
    if best is None and speaker_segments:
        best = min(
            speaker_segments,
            key=lambda turn: max(turn["start"] - word["end"], word["start"] - turn["end"], 0.0),
        )
    return best["speaker"] if best else UNKNOWN_SPEAKER


def _runs(words: List[Dict], speakers: List[str]) -> List[List[int]]:
    runs: List[List[int]] = []
    for index, speaker in enumerate(speakers):
        if runs and speakers[runs[-1][0]] == speaker:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _ends_sentence(word: Dict) -> bool:
    return bool(_SENTENCE_END.search(word["word"].strip()))


def _is_utterance(run: List[int], words: List[Dict]) -> bool:
    starts_clean = run[0] == 0 or _ends_sentence(words[run[0] - 1])
    return starts_clean and _ends_sentence(words[run[-1]])


def _speech_time(run: List[int], words: List[Dict]) -> float:
    return sum(words[i]["end"] - words[i]["start"] for i in run)


def _smooth(words: List[Dict], speakers: List[str]) -> List[str]:
    speakers = list(speakers)
    while True:
        runs = _runs(words, speakers)
        if len(runs) < 2:
            return speakers
        for position, run in enumerate(runs):
            if len(run) >= MERGE_FRAGMENTS_UNDER_WORDS or _is_utterance(run, words):
                continue
            neighbours = [runs[p] for p in (position - 1, position + 1) if 0 <= p < len(runs)]
            target = max(neighbours, key=lambda r: _speech_time(r, words))
            for index in run:
                speakers[index] = speakers[target[0]]
            break
        else:
            return speakers


def _split(segment: Dict, words: List[Dict], speakers: List[str]) -> List[Dict]:
    base = {key: value for key, value in segment.items() if key != "words"}
    runs = _runs(words, speakers)
    if len(runs) == 1:
        return [{**base, "speaker": speakers[0]}]
    pieces = []
    for run in runs:
        start = words[run[0]]["start"]
        end = words[run[-1]]["end"]
        pieces.append({
            **base,
            "id": str(uuid.uuid4()),
            "start": start,
            "end": end,
            "start_time": format_timestamp(start),
            "end_time": format_timestamp(end),
            "text": "".join(words[i]["word"] for i in run).strip(),
            "translation": None,
            "speaker": speakers[run[0]],
        })
    return pieces


def assign_speakers(segments: List[Dict], speaker_segments: List[Dict]) -> List[Dict]:
    """Return new segments, each with one ``speaker``; segments with ``words`` may be split."""
    result: List[Dict] = []
    for segment in segments:
        words = segment.get("words") or []
        if not words:
            result.append({
                **{key: value for key, value in segment.items() if key != "words"},
                "speaker": _line_speaker(segment, speaker_segments),
            })
            continue
        speakers = _smooth(words, [_word_speaker(word, speaker_segments) for word in words])
        result.extend(_split(segment, words, speakers))
    return result
