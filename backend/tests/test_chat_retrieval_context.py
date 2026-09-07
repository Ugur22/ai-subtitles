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

from routers.chat import _expand_text_hits_with_neighbors  # noqa: E402

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
