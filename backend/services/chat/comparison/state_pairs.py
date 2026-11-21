"""Chooses which two appearances best answer a comparison question."""
import re
from typing import Optional
from services.chat.comparison.appearances import _comparison_appearance_key
from services.chat.visual_refs import _cosine_similarity


def _comparison_query_mode(query: str) -> str:
    """Return how strongly the user's wording should steer pair selection."""
    query_lower = (query or "").lower()
    has_early = bool(re.search(r"\b(start|starts|begin|beginning|early|opening|first)\b", query_lower))
    has_late = bool(re.search(r"\b(end|ends|ending|late|later|final|towards?\s+the\s+end|after)\b", query_lower))
    if has_early and has_late:
        return "early_late"
    if bool(re.search(r"\b(before\s+and\s+after|before.+(?:after|during|then|later)|compared|change(?:d)?)\b", query_lower)):
        return "temporal"
    return "contrast"


def _state_pair_score(first: dict, second: dict, video_duration: float, mode: str) -> float:
    face_a = first.get("face_embedding")
    face_b = second.get("face_embedding")
    scene_a = first.get("scene_embedding")
    scene_b = second.get("scene_embedding")
    d_face = 1.0 - _cosine_similarity(face_a, face_b) if face_a and face_b else 0.0
    d_scene = 1.0 - _cosine_similarity(scene_a, scene_b) if scene_a and scene_b else 0.0
    d_time = min(
        1.0,
        abs(float(first.get("start_time") or 0.0) - float(second.get("start_time") or 0.0)) / max(video_duration, 1.0),
    )
    avg_identity = (
        float(first.get("similarity") or 0.0) + float(second.get("similarity") or 0.0)
    ) / 2.0

    if mode == "early_late":
        return 0.42 * d_face + 0.28 * d_scene + 0.25 * d_time + 0.05 * avg_identity
    if mode == "temporal":
        return 0.40 * d_face + 0.25 * d_scene + 0.30 * d_time + 0.05 * avg_identity
    # Weights emphasize visible person-state change, then context, with time as a tie-breaker toward early/late moments.
    return 0.50 * d_face + 0.30 * d_scene + 0.15 * d_time + 0.05 * avg_identity


def _select_best_state_pair(
    candidates: list[dict],
    video_duration: float,
    mode: str,
) -> Optional[tuple[dict, dict]]:
    best_pair = None
    best_score = -1.0
    for i, first in enumerate(candidates):
        for second in candidates[i + 1:]:
            score = _state_pair_score(first, second, video_duration, mode)
            if score > best_score:
                best_score = score
                best_pair = (first, second)

    if not best_pair:
        return None
    return tuple(sorted(best_pair, key=lambda row: float(row.get("start_time") or 0.0)))


def _select_cross_state_pair(
    first_group: list[dict],
    second_group: list[dict],
    video_duration: float,
    mode: str,
) -> Optional[tuple[dict, dict]]:
    best_pair = None
    best_score = -1.0
    for first in first_group:
        for second in second_group:
            if first is second:
                continue
            score = _state_pair_score(first, second, video_duration, mode)
            if score > best_score:
                best_score = score
                best_pair = (first, second)

    if not best_pair:
        return None
    return tuple(sorted(best_pair, key=lambda row: float(row.get("start_time") or 0.0)))


def _select_boundary_state_pair(
    appearances: list[dict],
    video_duration: float,
) -> Optional[tuple[dict, dict]]:
    """For explicit beginning/end wording, use earliest/latest reliable appearances."""
    reliable = sorted(
        appearances,
        key=lambda row: row.get("similarity", 0.0),
        reverse=True,
    )[:200]
    by_time = sorted(reliable, key=lambda row: float(row.get("start_time") or 0.0))
    if len(by_time) < 2:
        return None

    earliest_time = float(by_time[0].get("start_time") or 0.0)
    latest_time = float(by_time[-1].get("start_time") or 0.0)
    boundary_window = max(180.0, video_duration * 0.05)
    early = [
        row for row in by_time
        if float(row.get("start_time") or 0.0) <= earliest_time + boundary_window
    ]
    late = [
        row for row in by_time
        if float(row.get("start_time") or 0.0) >= latest_time - boundary_window
    ]
    if not early or not late:
        group_size = min(12, max(2, len(by_time) // 5))
        early = by_time[:group_size]
        late = by_time[-group_size:]

    first = max(early, key=lambda row: row.get("similarity", 0.0))
    second = max(late, key=lambda row: row.get("similarity", 0.0))
    if first is second:
        return None
    print(
        "[Chat] Face comparison selected boundary state pair "
        f"early={float(first.get('start_time') or 0.0):.2f}s "
        f"late={float(second.get('start_time') or 0.0):.2f}s"
    )
    return tuple(sorted((first, second), key=lambda row: float(row.get("start_time") or 0.0)))


# Words that mean "a moment in time" rather than a visible state — these belong
# to the early/late path, not query-aware visual matching.
_TEMPORAL_PHRASE_WORDS = {
    "start", "starts", "beginning", "begin", "early", "earlier", "opening",
    "first", "end", "ends", "ending", "late", "later", "latest", "final",
    "finally", "before", "after", "then", "during", "now", "younger", "older",
}


# Filler/structural words to drop when isolating the descriptive state phrase.
_STATE_PHRASE_STOPWORDS = {
    "the", "a", "an", "her", "his", "their", "him", "she", "he", "them", "it",
    "is", "was", "are", "were", "being", "been", "get", "gets", "got",
    "looks", "look", "looking", "appears", "appear", "appearing",
    "scene", "scenes", "version", "shot", "frame", "frames", "moment", "part",
    "state", "states", "when", "where", "while", "with", "and", "of", "in",
    "on", "at", "to", "compare", "compared", "comparing", "contrast",
    "contrasted", "show", "see", "versus", "vs", "person",
}


def _extract_state_phrases(
    query: str,
    person_names: Optional[list[str]] = None,
) -> Optional[tuple[str, str]]:
    """Pull two contrasting *visual-state* phrases from a comparison query.

    'compare <person> calm vs angry' -> ('calm', 'angry'). Returns None for
    temporal wording (beginning/end) or when no clear visual pair is present, so
    those queries fall through to the existing early/late + difference logic.
    """
    if not query:
        return None
    q = " " + query.lower().replace("'s", " ") + " "
    for name in (person_names or []):
        if name:
            q = re.sub(rf"\b{re.escape(name.lower())}\b", " ", q)

    m = re.search(r"(.+?)\b(?:versus|vs\.?|compared to|against|or|rather than)\b(.+)", q)
    if not m:
        return None

    def _side(text: str, take_last: bool) -> str:
        words = [w for w in re.findall(r"[a-z]+", text) if w not in _STATE_PHRASE_STOPWORDS]
        if not words:
            return ""
        words = words[-2:] if take_last else words[:2]
        return " ".join(words)

    left = _side(m.group(1), take_last=True)
    right = _side(m.group(2), take_last=False)
    if not left or not right or left == right:
        return None
    if (set(left.split()) | set(right.split())) & _TEMPORAL_PHRASE_WORDS:
        return None
    return (left, right)


_CLIP_PROMPT_TEMPLATES = ("{p}", "a photo of a person {p}", "a {p} person")


def _clip_text_embeddings(phrases: list[str]) -> Optional[list[list]]:
    """One averaged CLIP text embedding per phrase, all encoded in a single batch.

    Averages a few prompt templates — absolute CLIP text/image cosine is low and
    noisy, so the ensemble + contrast scoring (see caller) is what gives signal.
    """
    try:
        import numpy as np
        from services.image_embedding_service import image_embedding_service
        n = len(_CLIP_PROMPT_TEMPLATES)
        prompts = [t.format(p=p) for p in phrases for t in _CLIP_PROMPT_TEMPLATES]
        vecs = np.asarray(
            image_embedding_service.clip_model.encode(prompts, convert_to_numpy=True),
            dtype=np.float32,
        )
        return [vecs[i * n:(i + 1) * n].mean(axis=0).tolist() for i in range(len(phrases))]
    except Exception as e:
        print(f"[Chat] CLIP text embedding failed for {phrases}: {e}")
        return None


def _select_query_aware_state_pair(
    appearances: list[dict],
    phrase_a: str,
    phrase_b: str,
) -> Optional[tuple[dict, dict]]:
    """Pick endpoints by how well each frame's scene matches the user's two state
    phrases. Returns (A, B) in PHRASE order: A = most phrase_a, B = most phrase_b.

    Uses *contrast* scoring (sim_b - sim_a) rather than absolute similarity:
    CLIP text/image cosine is flat in absolute terms (~0.25 for everything), but
    the difference between the two phrases separates frames reliably (validated:
    'dark outfit vs light outfit' correctly lands B on the light-outfit scene).
    """
    candidates = [a for a in appearances if a.get("scene_embedding")]
    if len(candidates) < 2:
        return None
    texts = _clip_text_embeddings([phrase_a, phrase_b])
    if not texts:
        return None
    text_a, text_b = texts

    scored = [
        (
            a,
            _cosine_similarity(text_b, a.get("scene_embedding"))
            - _cosine_similarity(text_a, a.get("scene_embedding")),
        )
        for a in candidates
    ]
    frame_b = max(scored, key=lambda s: s[1])[0]  # most phrase_b vs phrase_a
    frame_a = min(scored, key=lambda s: s[1])[0]  # most phrase_a vs phrase_b
    if frame_a is frame_b:
        return None
    print(
        f"[Chat] Face comparison used query-aware pair: A~'{phrase_a}' "
        f"@{float(frame_a.get('start_time') or 0.0):.1f}s, B~'{phrase_b}' "
        f"@{float(frame_b.get('start_time') or 0.0):.1f}s"
    )
    return (frame_a, frame_b)


def _select_state_pair(
    appearances: list[dict],
    video_duration: float,
    query: str = "",
    person_names: Optional[list[str]] = None,
) -> Optional[tuple[dict, dict]]:
    """Select two appearances, using comparison wording to steer temporal vs contrast emphasis."""
    if len(appearances) < 2:
        return None

    # Query-aware: if the user named two visible states ("dark outfit vs light outfit"),
    # pick the frames that best match each phrase rather than generic difference.
    phrases = _extract_state_phrases(query, person_names)
    if phrases:
        pair = _select_query_aware_state_pair(appearances, phrases[0], phrases[1])
        if pair:
            return pair

    mode = _comparison_query_mode(query)
    candidates = sorted(
        appearances,
        key=lambda row: row.get("similarity", 0.0),
        reverse=True,
    )[:80 if mode in ("early_late", "temporal") else 30]

    if mode == "early_late":
        pair = _select_boundary_state_pair(appearances, video_duration)
        if pair:
            return pair

        early_cutoff = video_duration * 0.35
        late_cutoff = video_duration * 0.65
        early = [row for row in candidates if float(row.get("start_time") or 0.0) <= early_cutoff]
        late = [row for row in candidates if float(row.get("start_time") or 0.0) >= late_cutoff]
        if not early or not late:
            midpoint = video_duration * 0.5
            early = [row for row in candidates if float(row.get("start_time") or 0.0) <= midpoint]
            late = [row for row in candidates if float(row.get("start_time") or 0.0) > midpoint]
        if early and late:
            pair = _select_cross_state_pair(early, late, video_duration, mode)
            if pair:
                print("[Chat] Face comparison selected early/late state pair from query wording")
                return pair

    pair = _select_best_state_pair(candidates, video_duration, mode)
    if pair:
        print(f"[Chat] Face comparison selected state pair using mode={mode}")
    return pair


def _same_comparison_frame(first: dict, second: dict, tolerance_seconds: float = 2.0) -> bool:
    first_key = _comparison_appearance_key(first)
    second_key = _comparison_appearance_key(second)
    if first_key and second_key and first_key == second_key:
        return True
    return abs(
        float(first.get("start_time") or 0.0) - float(second.get("start_time") or 0.0)
    ) <= tolerance_seconds


def _with_comparison_people(appearance: dict, people: list[tuple[str, Optional[dict]]], label: str) -> dict:
    enriched = dict(appearance)
    enriched["people"] = [name for name, _ in people]
    enriched["label"] = label
    enriched["bboxes"] = [
        {"person": name, "bbox": bbox}
        for name, bbox in people
        if bbox
    ]
    return enriched


def _select_multi_person_state_pair(
    primary_appearances: list[dict],
    secondary_appearances: list[dict],
    video_duration: float,
    query: str,
    primary_person: str,
    secondary_person: str,
) -> Optional[tuple[dict, dict]]:
    """Select Frame A with both people and Frame B with the primary person later/changed."""
    if not primary_appearances or not secondary_appearances:
        return None

    joint_candidates = []
    for primary in primary_appearances:
        for secondary in secondary_appearances:
            if not _same_comparison_frame(primary, secondary):
                continue
            joint_candidates.append(
                _with_comparison_people(
                    primary,
                    [
                        (primary_person, primary.get("bbox")),
                        (secondary_person, secondary.get("bbox")),
                    ],
                    f"{primary_person} with {secondary_person}",
                )
            )
            break

    if not joint_candidates:
        print(
            f"[Chat] Face comparison found no shared frames for "
            f"'{primary_person}' + '{secondary_person}'"
        )
        return None

    mode = _comparison_query_mode(query)
    primary_candidates = sorted(
        primary_appearances,
        key=lambda row: row.get("similarity", 0.0),
        reverse=True,
    )[:120]
    best_pair = None
    best_score = -1.0
    for first in joint_candidates:
        first_time = float(first.get("start_time") or 0.0)
        for second in primary_candidates:
            second_time = float(second.get("start_time") or 0.0)
            if _same_comparison_frame(first, second):
                continue
            if mode in ("early_late", "temporal") and second_time <= first_time:
                continue
            score = _state_pair_score(first, second, video_duration, mode)
            if mode in ("early_late", "temporal"):
                score += 0.25 * min(1.0, max(0.0, (second_time - first_time) / max(video_duration, 1.0)))
            if score > best_score:
                best_score = score
                best_pair = (
                    first,
                    _with_comparison_people(
                        second,
                        [(primary_person, second.get("bbox"))],
                        f"{primary_person} later",
                    ),
                )

    if not best_pair:
        return None
    print(
        f"[Chat] Face comparison selected multi-person pair "
        f"primary='{primary_person}' secondary='{secondary_person}' "
        f"joint_candidates={len(joint_candidates)}"
    )
    return tuple(sorted(best_pair, key=lambda row: float(row.get("start_time") or 0.0)))
