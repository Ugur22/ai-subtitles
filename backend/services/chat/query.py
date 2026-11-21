"""Question normalisation, visual-term matching and follow-up resolution."""
from typing import List, Optional
from services.chat.context import _chat_user_id, _hash_resources_allowed, get_transcription_from_any_source


def _extract_all_speakers_from_query(query: str, video_hash: str) -> List[str]:
    """
    Extract ALL speaker names from query by checking against enrolled speakers
    and segment speaker labels.

    Args:
        query: User's question/query
        video_hash: Video hash to get segments from

    Returns:
        List of speaker names/labels found in query
    """
    if not query:
        return []

    query_lower = query.lower()
    found_speakers = []

    def add_if_mentioned(name: Optional[str], source: str) -> None:
        if not name:
            return
        if name.lower() in query_lower and not any(
            existing.lower() == name.lower() for existing in found_speakers
        ):
            print(f"Found {source} in query: {name}")
            found_speakers.append(name)

    # First, check enrolled speakers (e.g., "Alex", "John")
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()
        user_id = _chat_user_id.get()
        enrolled_speakers = sr_system.list_speakers(user_id) if user_id else []

        for speaker_name in enrolled_speakers:
            add_if_mentioned(speaker_name, "enrolled speaker")
    except Exception as e:
        print(f"Could not load speaker recognition system: {e}")

    if not _hash_resources_allowed.get():
        return found_speakers

    # Check manually tagged face/person names. The frontend exposes these names
    # in @mention autocomplete, so chat retrieval must recognize them too.
    try:
        from services.supabase_service import supabase as get_supabase
        client = get_supabase()
        user_id = _chat_user_id.get()
        if not user_id:
            return found_speakers
        result = (
            client.table("face_tags")
            .select("speaker_name")
            .eq("user_id", user_id)
            .eq("video_hash", video_hash)
            .execute()
        )
        for row in result.data or []:
            add_if_mentioned(row.get("speaker_name"), "face-tagged speaker")
    except Exception as e:
        print(f"Could not check face-tagged speakers: {e}")

    # Also check for SPEAKER_XX labels in segments
    # This handles cases where segments use labels like "SPEAKER_19"
    try:
        transcription = get_transcription_from_any_source(video_hash, user_id)
        if transcription:
            segments = transcription.get('transcription', {}).get('segments', [])

            # Build a set of unique speaker labels
            speaker_labels = set()
            for segment in segments:
                speaker = segment.get('speaker')
                if speaker:
                    speaker_labels.add(speaker)

            # Check if any speaker label is mentioned in the query
            for speaker_label in speaker_labels:
                add_if_mentioned(speaker_label, "speaker label")
    except Exception as e:
        print(f"Could not check segment speakers: {e}")

    return found_speakers


def _load_face_tag_names(video_hash: str) -> list[str]:
    """Return unique manually tagged person names for a video."""
    if not _hash_resources_allowed.get():
        return []
    try:
        from services.supabase_service import supabase as get_supabase

        client = get_supabase()
        user_id = _chat_user_id.get()
        if not user_id:
            return []
        result = (
            client.table("face_tags")
            .select("speaker_name")
            .eq("user_id", user_id)
            .eq("video_hash", video_hash)
            .execute()
        )
        names = []
        for row in result.data or []:
            name = (row.get("speaker_name") or "").strip()
            if name and not any(existing.lower() == name.lower() for existing in names):
                names.append(name)
        return names
    except Exception as e:
        print(f"Could not load face-tag names: {e}")
        return []


def _clean_query_for_retrieval(query: str) -> str:
    """Normalize UI mention syntax before embedding/search providers see it."""
    return (query or "").replace("@", " ").strip()


def _split_user_visual_lines(value: Optional[str]) -> list[str]:
    """Parse user-owned visual search settings from comma/newline text."""
    import re

    if not value:
        return []
    items = []
    for item in re.split(r"[\n,]+", value):
        item = re.sub(r"\s+", " ", item).strip().lower()
        if item and item not in items:
            items.append(item)
    return items


def _user_visual_search_config(profile: Optional[dict]) -> tuple[set[str], list[str]]:
    """Return private per-user visual search trigger terms and CLIP phrases."""
    terms = set(_split_user_visual_lines((profile or {}).get("visual_search_terms")))
    phrases = _split_user_visual_lines((profile or {}).get("visual_search_phrases"))
    return terms, phrases


def _query_matches_user_visual_terms(query: str, user_terms: set[str]) -> bool:
    """Return True when the query contains a user-configured visual trigger."""
    import re

    if not user_terms:
        return False
    cleaned = _clean_query_for_retrieval(query).lower()
    cleaned = re.sub(r"[^\w\s-]+", " ", cleaned)
    words = set(cleaned.split())
    return any(term in cleaned or term in words for term in user_terms)


def _resolve_contextual_visual_question(
    question: str,
    conversation_history: Optional[list],
    user_visual_terms: Optional[set[str]] = None,
    user_visual_phrases: Optional[list[str]] = None,
    video_hash: Optional[str] = None,
) -> str:
    """
    Expand short follow-up questions for retrieval.

    Users often ask "while doing it" or "that scene" after a previous visual
    question. CLIP/text retrieval needs the implied action repeated explicitly.
    """
    import re

    if not conversation_history:
        return question

    q = question or ""
    q_lower = q.lower()
    has_followup_reference = bool(re.search(
        r"\b(doing it|that|this|there|those|them|same scene|while doing"
        r"|she|her|hers|herself|he|him|his|himself|they|their)\b",
        q_lower,
    ))
    if not has_followup_reference:
        return question

    recent_user_text = " ".join(
        str(msg.get("content", ""))
        for msg in conversation_history[-6:]
        if msg.get("role") == "user"
    ).lower()

    additions = []
    user_visual_terms = user_visual_terms or set()
    user_visual_phrases = user_visual_phrases or []
    if _query_matches_user_visual_terms(recent_user_text, user_visual_terms):
        additions.extend(user_visual_phrases[:3])
    # If a recent message named a person tagged in this video but the current
    # question doesn't, anchor retrieval to them so follow-ups keep the subject.
    if video_hash:
        # Most recently mentioned wins, so "her" follows the latest subject rather than tag-list order.
        latest_pos, latest_name = -1, None
        for name in _load_face_tag_names(video_hash):
            name_lower = name.lower()
            if name_lower in q_lower:
                continue
            matches = list(re.finditer(rf"\b{re.escape(name_lower)}\b", recent_user_text))
            if matches and matches[-1].start() > latest_pos:
                latest_pos, latest_name = matches[-1].start(), name_lower
        if latest_name:
            additions.append(f"involving {latest_name}")

    if not additions:
        return question

    resolved = f"{question} {' '.join(additions)}"
    print(f"Resolved contextual visual question: '{question}' -> '{resolved}'")
    return resolved


def _visual_query_variants(
    query: str,
    user_visual_terms: Optional[set[str]] = None,
    user_visual_phrases: Optional[list[str]] = None,
) -> list[str]:
    """
    Build CLIP-friendly visual queries from chatty natural-language questions.

    CLIP image search is sensitive to filler words. A question like
    "is person swimming in this film?" can return fewer results than the
    shorter scene phrase "person swimming". For common movie-scene intents,
    add concrete visual phrases because CLIP performs better on descriptions
    of what appears in a frame than on conversational questions.
    """
    import re

    cleaned = _clean_query_for_retrieval(query).lower()
    cleaned = re.sub(r"[^\w\s-]+", " ", cleaned)
    cleaned = re.sub(r"\b(in|from|during|inside|within)\s+(this|the|a|an)?\s*(film|movie|video|scene|clip)\b", " ", cleaned)
    cleaned = re.sub(r"\b(this|the|a|an)\s+(film|movie|video|scene|clip)\b", " ", cleaned)

    stop_words = {
        "is", "are", "was", "were", "does", "do", "did", "can", "could",
        "would", "should", "show", "find", "search", "look", "see", "tell",
        "me", "about", "whether", "if", "there", "any", "images", "image",
        "screenshots", "screenshot", "picture", "pictures", "of", "in",
        "looks", "looking", "amazing", "beautiful", "hot",
    }
    tokens = [tok for tok in cleaned.split() if tok and tok not in stop_words]
    compact = " ".join(tokens)

    intent_phrases: list[str] = []
    user_visual_terms = user_visual_terms or set()
    user_visual_phrases = user_visual_phrases or []
    if _query_matches_user_visual_terms(cleaned, user_visual_terms):
        intent_phrases.extend(user_visual_phrases)

    variants = []
    for candidate in (*intent_phrases, compact, _clean_query_for_retrieval(query)):
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate and candidate.lower() not in {v.lower() for v in variants}:
            variants.append(candidate)
    if len(variants) > 1:
        print(f"Visual query variants for '{query}': {variants[:6]}")
    return variants


_CAUSAL_MARKERS = {"why", "because", "reason", "reasons"}


def _is_causal_question(question: str) -> bool:
    """True if the question is asking for a cause/explanation ("why"/"because"
    /"reason"). Movie dialogue tends to state the reason for an event shortly
    *after* the event itself, so causal questions get a forward-biased
    context window in `_retrieve_text_context` -- see `_expand_text_hits_with_
    neighbors`'s `neighbor_chunks_after` and `_lexical_segment_matches`'s
    `after` param."""
    import re

    tokens = re.findall(r"[a-z']+", (question or "").lower())
    return any(token in _CAUSAL_MARKERS for token in tokens)


def _extract_keywords(text: str) -> set[str]:
    """Stop-word-filtered lowercase token set, shared by lexical matching
    and top-ranked-hit keyword annotation."""
    import re

    stop_words = {
        "a", "an", "and", "are", "about", "at", "can", "could", "did", "do",
        "does", "for", "from", "happen", "happened", "how", "i", "in", "is",
        "it", "me", "movie", "of", "on", "or", "scene", "show", "tell",
        "the", "this", "to", "video", "was", "what", "when", "where", "who",
        "why", "with", "would",
    }
    cleaned = _clean_query_for_retrieval(text).lower()
    return {
        token
        for token in re.findall(r"[a-z0-9_'-]+", cleaned)
        if len(token) > 2 and token not in stop_words
    }
