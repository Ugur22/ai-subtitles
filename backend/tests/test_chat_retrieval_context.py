"""
Focused unit test for routers/chat.py's `_expand_text_hits_with_neighbors`.

Regression coverage for a context-assembly bug found via evals/evaluate_chat.py:
neighbor expansion used to walk a fixed number of raw ASR *segments* past a
hit's own overlapping span. Since the overlap check is boundary-inclusive
(`seg_start <= hit_end and seg_end >= hit_start`), a segment that merely
*touches* a hit's edge -- belonging to the next chunk over -- got swept into
the hit's own "semantic_hit" span. That silently ate into the raw-segment
neighbor budget, so how far the window actually reached depended on an
unrelated boundary quirk instead of being a stable "one chunk over".

The fix: expand in chunk-index space. Round the hit's own overlapping span
out to whole embedding-chunk boundaries first, then step `neighbor_chunks`
whole chunks further on each side -- so the window always reaches exactly
one full extra chunk regardless of how many raw segments the hit's own span
happened to claim. See routers/chat.py's `_retrieve_text_context` for the
call site.

Also covers a related bug found while investigating a movie-1 eval
regression: `_format_text_context` always includes every top-k hit's own
one-line text in an untruncated "TOP RANKED SEMANTIC MATCHES" header, so
the LLM can ground an answer in a low-ranked hit -- but under a single
shared truncation budget, a higher-ranked hit's "neighbor" filler could
crowd out a lower-ranked hit's own "semantic_hit" segment, leaving that
hit's citation entirely out of `sources` even though it grounded the
answer. First fixed by sorting hits ahead of filler under one shared
budget -- which then caused a *third* bug: guaranteeing every hit survives
ate into the same pool neighbor padding needed for "why" questions,
regressing the chunk-index fix above. Final fix: `hit_budget` and
`neighbor_budget` are separate pools, so neither can starve the other.

Run: python -m pytest tests/test_chat_retrieval_context.py -q  (from backend/)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LOCAL_MODE", "true")

from routers.chat import (  # noqa: E402
    _expand_text_hits_with_neighbors,
    _format_text_context,
    _is_causal_question,
    _lexical_segment_matches,
    _merge_text_results,
    _resolve_contextual_visual_question,
)

CHUNK_SIZE = 3


def _gapped_segments(count: int) -> list:
    # 1-unit gaps so adjacent segments never share a boundary point --
    # isolates exactly which raw segments a hit's own span overlaps.
    return [
        {"start": float(i * 10), "end": float(i * 10 + 9), "text": f"segment {i}", "speaker": "SPEAKER_00"}
        for i in range(count)
    ]


def _touching_segments(count: int) -> list:
    # No gaps: adjacent segments share a boundary point exactly, which is
    # what naturally triggers the boundary-inclusive overlap quirk this
    # test is modeling.
    return [
        {"start": float(i * 10), "end": float(i * 10 + 10), "text": f"segment {i}", "speaker": "SPEAKER_00"}
        for i in range(count)
    ]


def _hit(start: float, end: float) -> dict:
    return {
        "text": "hit",
        "metadata": {"video_hash": "h", "start": start, "end": end, "start_time": "", "end_time": "", "speaker": "SPEAKER_00"},
        "distance": None,
    }


def _included_segment_indices(expanded: list) -> set[int]:
    return {int(r["text"].split()[-1]) for r in expanded}


def test_hit_on_one_chunk_expands_to_exactly_one_neighbor_chunk_each_side():
    segments = _gapped_segments(15)  # 5 chunks of 3
    hit = _hit(30.0, 59.0)  # exactly chunk 1's raw segments (indices 3,4,5)
    expanded = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=1, chunk_size=CHUNK_SIZE, hit_budget=24, neighbor_budget=24
    )
    included = _included_segment_indices(expanded)
    assert included == {0, 1, 2, 3, 4, 5, 6, 7, 8}  # chunks 0, 1, 2
    assert 9 not in included  # chunk 3 not reached


def test_wide_hit_span_still_gets_a_full_neighbor_chunk_each_side():
    """
    Reproduces the real bug: touching segment boundaries let a hit whose
    true content is chunk 1 (indices 3,4,5) also "overlap" index 2 (last
    segment of chunk 0) and index 6 (first segment of chunk 2) -- widening
    the hit's own tagged span beyond its actual chunk. A raw-segment-count
    window would have its neighbor budget eaten by this widened span and
    stop partway into the next chunk. The chunk-index-based window must
    still reach a full extra chunk beyond wherever the (widened) span
    actually lands.
    """
    segments = _touching_segments(15)
    hit = _hit(30.0, 60.0)  # chunk 1's true range; touches idx2's end and idx6's start
    expanded = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=1, chunk_size=CHUNK_SIZE, hit_budget=24, neighbor_budget=24
    )
    included = _included_segment_indices(expanded)
    # Widened span (idx 2-6) spans chunks 0-2; one more neighbor chunk each
    # side reaches chunk 3 (indices 9,10,11) fully, not just its first segment.
    assert {9, 10, 11}.issubset(included)


def test_neighbor_chunks_zero_only_covers_the_hits_own_chunk():
    segments = _gapped_segments(9)
    hit = _hit(30.0, 59.0)  # chunk 1 (indices 3,4,5)
    expanded = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=0, chunk_size=CHUNK_SIZE, hit_budget=24, neighbor_budget=24
    )
    included = _included_segment_indices(expanded)
    assert included == {3, 4, 5}


def test_tight_neighbor_budget_never_drops_a_hits_own_segment():
    """
    5 ranked hits, spaced 4 chunks apart so their neighbor windows never
    overlap. neighbor_budget is 0 -- no filler allowed at all -- but
    hit_budget comfortably fits all 5 hits' own 15 segments. Every hit's
    own segment, including rank 5's (the lowest-priority hit), must still
    survive: the guarantee comes from a dedicated budget, not from winning
    a competition against filler.
    """
    segments = _gapped_segments(60)  # 20 chunks of 3
    hit_chunks = [0, 4, 8, 12, 16]
    hits = [_hit(float(c * CHUNK_SIZE * 10), float((c * CHUNK_SIZE + 2) * 10 + 9)) for c in hit_chunks]
    expanded = _expand_text_hits_with_neighbors(
        "h", hits, segments, neighbor_chunks=1, chunk_size=CHUNK_SIZE, hit_budget=15, neighbor_budget=0
    )
    included = _included_segment_indices(expanded)
    own_segments = {idx for c in hit_chunks for idx in (c * CHUNK_SIZE, c * CHUNK_SIZE + 1, c * CHUNK_SIZE + 2)}
    assert included == own_segments  # all 5 hits' own segments, zero filler
    assert len(expanded) == 15


def test_tight_hit_budget_does_not_shrink_neighbor_reach():
    """
    The other direction of independence: hit_budget=0 excludes the hit's
    own segment entirely, but neighbor_chunks/neighbor_budget still expand
    to the full intended window (one full chunk each side) -- proving
    neighbor reach is computed independently of hit_budget, not reduced by
    a starved hit_budget elsewhere.
    """
    segments = _gapped_segments(9)  # 3 chunks of 3
    hit = _hit(30.0, 59.0)  # chunk 1 (indices 3,4,5)
    expanded = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=1, chunk_size=CHUNK_SIZE, hit_budget=0, neighbor_budget=24
    )
    included = _included_segment_indices(expanded)
    assert included == {0, 1, 2, 6, 7, 8}  # full neighbor chunks 0 and 2
    assert not included & {3, 4, 5}  # hit's own segment excluded by hit_budget=0


# --- neighbor_chunks_after (causal-question forward-biased expansion) ------


def test_neighbor_chunks_after_none_matches_symmetric_default():
    """Omitting neighbor_chunks_after (all pre-existing call sites and every
    test above) must be byte-identical to today's symmetric behavior."""
    segments = _gapped_segments(15)
    hit = _hit(30.0, 59.0)  # chunk 1 (indices 3,4,5)
    default = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=1, chunk_size=CHUNK_SIZE, hit_budget=24, neighbor_budget=24
    )
    explicit_none = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=1, neighbor_chunks_after=None,
        chunk_size=CHUNK_SIZE, hit_budget=24, neighbor_budget=24,
    )
    assert _included_segment_indices(default) == _included_segment_indices(explicit_none)


def test_neighbor_chunks_after_widens_forward_reach_only():
    """A wider neighbor_chunks_after reaches further chunks forward while
    backward reach stays governed by neighbor_chunks -- the asymmetric
    window causal questions use (see _retrieve_text_context)."""
    segments = _gapped_segments(21)  # 7 chunks of 3
    hit = _hit(30.0, 59.0)  # chunk 1 (indices 3,4,5)
    expanded = _expand_text_hits_with_neighbors(
        "h", [hit], segments, neighbor_chunks=1, neighbor_chunks_after=3,
        chunk_size=CHUNK_SIZE, hit_budget=24, neighbor_budget=48,
    )
    included = _included_segment_indices(expanded)
    assert {0, 1, 2}.issubset(included)  # backward: still just 1 chunk (chunk 0)
    assert {6, 7, 8, 9, 10, 11, 12, 13, 14}.issubset(included)  # forward: chunks 2,3,4
    assert not included & {15, 16, 17}  # chunk 5 not reached


# --- _lexical_segment_matches before/after window ---------------------------


def _text_segments(pairs):
    return [
        {"start": start, "end": start + 4.0, "text": text, "speaker": "SPEAKER_00"}
        for start, text in pairs
    ]


_LEXICAL_FIXTURE = _text_segments([
    (0.0, "unrelated filler one"),
    (10.0, "unrelated filler two"),
    (20.0, "the disasters caused by matteo wind were terrible"),
    (30.0, "unrelated filler three"),
    (40.0, "unrelated filler four"),
    (50.0, "unrelated filler five"),
    (60.0, "this is the only weapon to deal with the colonel"),
])


def test_lexical_segment_matches_default_window_does_not_reach_distant_line():
    """Default before=1/after=1 reproduces the original hardcoded ±1 window --
    too narrow to reach a follow-up line 4 segments past the matched anchor."""
    results = _lexical_segment_matches("h", "why free matteo wind disasters", _LEXICAL_FIXTURE, limit=1)
    texts = {r["text"] for r in results}
    assert "the disasters caused by matteo wind were terrible" in texts
    assert "this is the only weapon to deal with the colonel" not in texts


def test_lexical_segment_matches_wider_after_reaches_follow_up_line():
    """Widening `after` (as _retrieve_text_context does for causal questions)
    reaches the follow-up line, and the internal result cap scales with the
    window so it isn't silently truncated back down."""
    results = _lexical_segment_matches(
        "h", "why free matteo wind disasters", _LEXICAL_FIXTURE, limit=1, after=4
    )
    texts = {r["text"] for r in results}
    assert "the disasters caused by matteo wind were terrible" in texts
    assert "this is the only weapon to deal with the colonel" in texts


# --- _merge_text_results lexical-budget reservation (regression) ------------


def test_merge_text_results_drops_lexical_when_primary_saturates_shared_budget():
    """Reproduces the real bug: when primary (semantic hit + neighbor tiers)
    alone fills max_results, lexical results are silently dropped entirely --
    this is the OLD behavior (max_results = hit_budget + neighbor_budget,
    with no separate lexical allowance)."""
    primary = [
        {"metadata": {"start": float(i), "end": float(i) + 1.0}, "text": f"primary {i}"}
        for i in range(10)
    ]
    lexical = [
        {"metadata": {"start": float(100 + i), "end": float(100 + i) + 1.0}, "text": f"lexical {i}"}
        for i in range(4)
    ]
    merged = _merge_text_results(primary, lexical, max_results=10)
    assert not any(r["text"].startswith("lexical") for r in merged)


def test_merge_text_results_reserves_room_for_lexical_with_extra_budget():
    """Fix: reserving a dedicated lexical_budget on top of hit_budget +
    neighbor_budget (see _retrieve_text_context) guarantees lexical results
    survive even when primary is fully saturated."""
    primary = [
        {"metadata": {"start": float(i), "end": float(i) + 1.0}, "text": f"primary {i}"}
        for i in range(10)
    ]
    lexical = [
        {"metadata": {"start": float(100 + i), "end": float(100 + i) + 1.0}, "text": f"lexical {i}"}
        for i in range(4)
    ]
    merged = _merge_text_results(primary, lexical, max_results=10 + 4)
    lexical_survivors = [r for r in merged if r["text"].startswith("lexical")]
    assert len(lexical_survivors) == 4


# --- _is_causal_question ------------------------------------------------------


# --- anchor-score propagation (Keyword Match relevance labeling) -----------


def test_lexical_segment_matches_propagates_anchor_keywords_to_zero_overlap_followup():
    """A real causal answer often shares zero words with the question (a
    'why free X' question answered by a line using "weapon" shares nothing).
    The follow-up must inherit its *anchor's* overlap count, not show 0 --
    otherwise the model has no signal this segment belongs to a relevant
    cluster at all."""
    results = _lexical_segment_matches(
        "h", "why free matteo wind disasters", _LEXICAL_FIXTURE, limit=1, after=4
    )
    by_text = {r["text"]: r for r in results}
    weapon = by_text["this is the only weapon to deal with the colonel"]
    anchor = by_text["the disasters caused by matteo wind were terrible"]
    assert weapon["lexical_anchor_keyword_count"] == anchor["lexical_anchor_keyword_count"]
    assert weapon["lexical_anchor_keyword_count"] > 0
    assert set(weapon["lexical_anchor_keywords"]) == set(anchor["lexical_anchor_keywords"])


def test_lexical_segment_matches_window_collision_keeps_higher_scoring_anchor():
    """When two anchors' windows overlap on the same index, the higher-scoring
    anchor's keywords win -- same 'better source wins on tie' precedence as
    _expand_text_hits_with_neighbors."""
    segments = _text_segments([
        (0.0, "alpha strong overlap keyword value"),
        (10.0, "middle shared segment text"),
        (20.0, "beta weak keyword"),
    ])
    question = "alpha strong overlap value keyword"
    results = _lexical_segment_matches("h", question, segments, limit=2, before=1, after=1)
    by_text = {r["text"]: r for r in results}
    middle = by_text["middle shared segment text"]
    assert middle["lexical_anchor_keyword_count"] == 5
    assert set(middle["lexical_anchor_keywords"]) == {"alpha", "strong", "overlap", "keyword", "value"}


def test_format_text_context_renders_lexical_anchor_annotation():
    results = _lexical_segment_matches(
        "h", "why free matteo wind disasters", _LEXICAL_FIXTURE, limit=1, after=4
    )
    context, _ = _format_text_context("h", results, question="why free matteo wind disasters")
    assert "its match cluster overlaps" in context
    assert "this is the only weapon to deal with the colonel" in context


def test_format_text_context_falls_back_to_plain_label_without_question():
    """The one existing no-question call site (empty-search-results fallback
    in _retrieve_text_context) must keep working unchanged."""
    results = _lexical_segment_matches(
        "h", "why free matteo wind disasters", _LEXICAL_FIXTURE, limit=1, after=4
    )
    context, _ = _format_text_context("h", results)
    assert "its match cluster overlaps" not in context
    assert "(literal word overlap only, not semantic ranking)" in context


def test_is_causal_question_detects_why_because_reason():
    assert _is_causal_question("Why do they free him?") is True
    assert _is_causal_question("What is the reason they free him?") is True
    assert _is_causal_question("Because of what happened, what changed?") is True


def test_is_causal_question_false_for_non_causal_wording():
    assert _is_causal_question("What do they do to free him?") is False
    assert _is_causal_question("Who frees him?") is False
    assert _is_causal_question("") is False


def _resolve(question, history, tags=("vila", "anna")):
    import routers.chat as chat
    orig = chat._load_face_tag_names
    chat._load_face_tag_names = lambda _h: list(tags)
    try:
        return _resolve_contextual_visual_question(question, history, set(), [], "vh")
    finally:
        chat._load_face_tag_names = orig


def test_pronoun_followup_anchors_to_previously_named_person():
    history = [{"role": "user", "content": "any scene where vila is swimming?"}]
    assert "involving vila" in _resolve("her boobs look amazing", history)


def test_pronoun_followup_prefers_most_recent_person():
    history = [
        {"role": "user", "content": "show vila"},
        {"role": "user", "content": "now anna"},
    ]
    assert "involving anna" in _resolve("what is she wearing", history)


def test_followup_unchanged_when_name_given_or_no_history():
    history = [{"role": "user", "content": "vila swimming"}]
    assert _resolve("her friend vila", history) == "her friend vila"
    assert _resolve("her boobs", None) == "her boobs"
