"""Detects person-comparison questions."""
import re
from dataclasses import dataclass
from typing import Optional
from services.chat.query import _clean_query_for_retrieval, _load_face_tag_names


@dataclass
class ComparisonIntent:
    person_name: Optional[str]
    unmatched_name: Optional[str] = None
    secondary_person_name: Optional[str] = None


def _detect_comparison_intent(query: str, video_hash: str) -> Optional[ComparisonIntent]:
    """
    Detect person state comparison questions without stealing unrelated
    comparison queries from normal RAG.
    """
    if not query:
        return None

    cleaned = _clean_query_for_retrieval(query)
    query_lower = cleaned.lower()
    has_comparison_phrase = bool(re.search(
        r"\b(compare|compared|comparing|contrast|versus|vs\.?|different|change(?:d)?|before and after)\b",
        query_lower,
    )) or bool(re.search(r"\bhow\s+did\b.+\bchange\b", query_lower)) or bool(re.search(
        r"\b(?:start|beginning|early)\b.+\b(?:end|ending|late|after)\b",
        query_lower,
    )) or bool(re.search(
        r"\bbefore\b.+\b(?:after|during|then|later)\b",
        query_lower,
    ))
    if not has_comparison_phrase:
        return None

    known_names = _load_face_tag_names(video_hash)
    normalized_query = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", query_lower.replace("'s", ""))).strip()
    matched_names: list[tuple[int, str]] = []
    for name in known_names:
        direct_match = re.search(rf"(?<!\w){re.escape(name.lower())}(?:'s)?(?!\w)", query_lower)
        if direct_match:
            matched_names.append((direct_match.start(), name))
            continue
        normalized_name = re.sub(
            r"\s+",
            " ",
            re.sub(r"[^\w\s]", " ", name.lower().replace("'s", "")),
        ).strip()
        normalized_index = f" {normalized_query} ".find(f" {normalized_name} ") if normalized_name else -1
        if normalized_index >= 0:
            matched_names.append((normalized_index, name))

    if matched_names:
        names_by_mention = [
            name for _, name in sorted(matched_names, key=lambda item: item[0])
        ]
        return ComparisonIntent(
            person_name=names_by_mention[0],
            secondary_person_name=names_by_mention[1] if len(names_by_mention) > 1 else None,
        )

    candidate_patterns = [
        r"\b(?:compare|compared|comparing|contrast)\s+([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|mom|mother|dad|father|wife|husband|son|daughter)){0,3})\b",
        r"\bhow\s+(?:did|does)\s+([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|mom|mother|dad|father|wife|husband|son|daughter)){0,3})\s+(?:change|start|begin)\b",
        r"\b([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|mom|mother|dad|father|wife|husband|son|daughter)){0,3})\s+(?:early|beginning|before|start)\s+(?:vs\.?|versus|and|compared|towards?)\s+(?:late|end|after)\b",
    ]
    stop_targets = {"the", "this", "that", "with", "against", "between", "book", "version", "video", "movie", "scene"}
    for pattern in candidate_patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ?.,:;!\"'")
        if not candidate:
            continue
        first = candidate.split()[0].lower()
        if first in stop_targets:
            continue
        return ComparisonIntent(person_name=None, unmatched_name=candidate)

    return None
