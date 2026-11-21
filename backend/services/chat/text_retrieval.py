"""Transcript retrieval: semantic hits, lexical fallback, neighbour expansion."""
from typing import Optional
from services.transcript_embedding_service import transcript_embedding_service
from services.chat.context import _chat_user_id, _run_in_executor, get_transcription_from_any_source
from services.chat.query import _clean_query_for_retrieval, _extract_all_speakers_from_query, _extract_keywords, _is_causal_question
from services.chat.segments import _segment_as_search_result, _segment_bounds, _segment_key, _segment_text


_TIER_LABELS = {
    "semantic_hit": "Semantic Match",
    "neighbor": "Surrounding Context",
    "lexical": "Keyword Match",
    "speaker_match": "Speaker Match",
}


def _format_text_context(
    video_hash: str,
    search_results: list,
    top_ranked_hits: Optional[list] = None,
    question: Optional[str] = None,
) -> tuple[str, list]:
    context_parts = []
    sources = []
    question_keywords = _extract_keywords(question) if question else set()

    if top_ranked_hits:
        top_lines = [
            "TOP RANKED SEMANTIC MATCHES (check every one of these before "
            "concluding the transcript doesn't address the question):"
        ]
        for rank, hit in enumerate(top_ranked_hits, start=1):
            metadata = hit["metadata"]
            similarity = hit.get("similarity")
            sim_part = f"similarity {similarity:.2f}" if similarity is not None else "similarity n/a"
            keyword_part = ""
            if question_keywords:
                overlap = question_keywords & _extract_keywords(hit["text"])
                if overlap:
                    keyword_part = (
                        f", {len(overlap)}/{len(question_keywords)} question "
                        f"keywords: {', '.join(sorted(overlap))}"
                    )
            top_lines.append(
                f"Rank {rank} ({sim_part}{keyword_part}) "
                f"[{metadata['start_time']} - {metadata['end_time']}] "
                f"{metadata['speaker']}: {hit['text']}"
            )
        context_parts.append("\n".join(top_lines))

    for result in search_results:
        metadata = result["metadata"]
        text = result["text"]
        tier = result.get("tier", "semantic_hit")
        rank = result.get("rank")
        similarity = result.get("similarity")
        label = _TIER_LABELS.get(tier, "Semantic Match")

        if tier == "semantic_hit":
            evidence = f"{label}, Rank {rank}" if rank else label
            if similarity is not None:
                evidence += f", similarity {similarity:.2f}"
        elif tier == "neighbor":
            evidence = f"{label} (near Rank {rank} Semantic Match)" if rank else label
        elif tier == "speaker_match":
            evidence = f"{label} (named-speaker lookup, not semantic ranking)"
        else:
            anchor_keywords = result.get("lexical_anchor_keywords")
            if anchor_keywords and question_keywords:
                evidence = (
                    f"{label}, its match cluster overlaps {len(anchor_keywords)}/"
                    f"{len(question_keywords)} question keywords: {', '.join(anchor_keywords)} "
                    f"(literal word overlap only, not semantic ranking)"
                )
            else:
                evidence = f"{label} (literal word overlap only, not semantic ranking)"

        context_parts.append(
            f"[Evidence: {evidence}] "
            f"[Timestamp: {metadata['start_time']} - {metadata['end_time']}] "
            f"[Speaker: {metadata['speaker']}]\n{text}"
        )
        sources.append({
            "start_time": metadata["start_time"],
            "end_time": metadata["end_time"],
            "start": metadata["start"],
            "end": metadata["end"],
            "speaker": metadata["speaker"],
            "text": text[:200] + "..." if len(text) > 200 else text,
            "tier": tier,
            "rank": rank,
            "similarity": similarity,
        })

    return "\n\n".join(context_parts), sources


def _tag_semantic_rank(search_results: list) -> list:
    """Tag raw search_transcript_chunks results with tier/rank so downstream
    formatting can distinguish real semantic hits from neighbor/lexical
    evidence. Shallow-copies each dict so the caller's original list (which
    may be cached/reused elsewhere) is never mutated."""
    tagged = []
    for rank, result in enumerate(search_results, start=1):
        item = dict(result)
        item["tier"] = "semantic_hit"
        item["rank"] = rank
        tagged.append(item)
    return tagged


def _expand_text_hits_with_neighbors(
    video_hash: str,
    search_results: list,
    segments: list,
    neighbor_chunks: int = 1,
    chunk_size: int = 1,
    hit_budget: int = 24,
    neighbor_budget: int = 24,
    neighbor_chunks_after: Optional[int] = None,
) -> list:
    """
    Add nearby transcript segments around vector hits, tagging every segment
    with the tier/rank/similarity of the semantic hit that produced it.

    Vector hits are indexed as small chunks. For movie/chat questions the
    surrounding line or two often carries the setup, referent, or resolution,
    so we include adjacent transcript segments before prompting the LLM --
    but grouped by originating rank (best first) rather than chronological
    position, so the LLM (and any max_results truncation) can tell a real
    semantic hit apart from filler pulled in only for continuity.

    neighbor_chunks_after: forward-only override for how many chunks past a
    hit's own span to include, independent of the backward `neighbor_chunks`
    reach. Defaults to None, which keeps expansion symmetric (uses
    `neighbor_chunks` on both sides, byte-identical to passing no override) --
    for causal ("why"/"because"/"reason") questions, the explanation more
    often follows the retrieved event than precedes it, so callers can widen
    only the forward reach without also pulling in more backward filler.

    Expansion is done in chunk-index space, not raw-segment count: a hit's
    own overlapping raw-segment span is rounded out to whole embedding-chunk
    boundaries (`chunk_size` raw segments per chunk) before stepping
    `neighbor_chunks` whole chunks further on each side. This keeps "one
    chunk of new context on each side" true regardless of how many raw
    segments the hit's own span happens to claim -- a raw-segment-count
    window would silently shrink whenever the overlap check (which is
    boundary-inclusive) swept extra segments into the hit's own span.

    Two rank-ascending passes over search_results: pass 1 claims each hit's
    own overlapping segment(s) as tier="semantic_hit"; pass 2 claims the
    chunk-expanded window as tier="neighbor", never overwriting an index
    pass 1 already claimed. This makes precedence deterministic -- a segment
    that is simultaneously rank 1's exact hit and rank 3's neighbor always
    keeps "semantic_hit", and ties within a tier keep the better (lower) rank.

    "semantic_hit" and "neighbor" tiers are truncated against **separate**
    budgets (`hit_budget`, `neighbor_budget`), not one shared pool. They
    used to share a single cap, which meant guaranteeing every hit's own
    segment survives truncation (so `sources` never omits a hit that
    actually grounded the answer -- see `_format_text_context`'s untruncated
    "TOP RANKED SEMANTIC MATCHES" header, which always includes it) came at
    the direct expense of neighbor padding for "why"/causal questions,
    whichever ate the shared budget first. Separate budgets mean growing
    one can never starve the other.
    """
    tagged_results = _tag_semantic_rank(search_results)
    if not tagged_results or not segments:
        return tagged_results

    index_info: dict[int, dict] = {}
    per_hit_overlap: list[list[int]] = []

    for result in tagged_results:
        metadata = result.get("metadata") or {}
        hit_start = float(metadata.get("start", 0) or 0)
        hit_end = float(metadata.get("end", hit_start) or hit_start)

        overlapping = []
        for idx, segment in enumerate(segments):
            text = _segment_text(segment)
            if not text:
                continue
            seg_start, seg_end, _, _ = _segment_bounds(segment)
            if seg_start <= hit_end and seg_end >= hit_start:
                overlapping.append(idx)
        per_hit_overlap.append(overlapping)

        for idx in overlapping:
            if idx not in index_info:
                index_info[idx] = {
                    "tier": "semantic_hit",
                    "rank": result["rank"],
                    "similarity": result.get("similarity"),
                }

    chunks_after = neighbor_chunks if neighbor_chunks_after is None else neighbor_chunks_after
    for result, overlapping in zip(tagged_results, per_hit_overlap):
        if not overlapping:
            continue
        chunk_start = min(overlapping) // chunk_size
        chunk_end = max(overlapping) // chunk_size
        start_idx = max(0, (chunk_start - neighbor_chunks) * chunk_size)
        end_idx = min(len(segments) - 1, (chunk_end + chunks_after + 1) * chunk_size - 1)
        for idx in range(start_idx, end_idx + 1):
            if idx in index_info:
                continue
            index_info[idx] = {
                "tier": "neighbor",
                "rank": result["rank"],
                "similarity": result.get("similarity"),
            }

    if not index_info:
        return tagged_results

    hit_items = sorted(
        ((idx, info) for idx, info in index_info.items() if info["tier"] == "semantic_hit"),
        key=lambda kv: (kv[1]["rank"], kv[0]),
    )
    neighbor_items = sorted(
        ((idx, info) for idx, info in index_info.items() if info["tier"] != "semantic_hit"),
        key=lambda kv: (kv[1]["rank"], kv[0]),
    )

    expanded = []
    seen = set()

    def _add_up_to_budget(items: list, budget: int) -> None:
        added = 0
        for idx, info in items:
            if added >= budget:
                break
            segment = segments[idx]
            text = _segment_text(segment)
            if not text:
                continue
            key = _segment_key(segment)
            if key in seen:
                continue
            seen.add(key)
            result = _segment_as_search_result(video_hash, segment)
            result["tier"] = info["tier"]
            result["rank"] = info["rank"]
            result["similarity"] = info["similarity"]
            expanded.append(result)
            added += 1

    _add_up_to_budget(hit_items, hit_budget)
    _add_up_to_budget(neighbor_items, neighbor_budget)

    return expanded or tagged_results


def _lexical_segment_matches(
    video_hash: str,
    question: str,
    segments: list,
    limit: int,
    before: int = 1,
    after: int = 1,
) -> list:
    """Find transcript segments with exact query term/phrase overlap.

    before/after: raw-segment window expanded around each of the top `limit`
    scored anchors (default ±1, matching prior hardcoded behavior). Callers
    widen `after` for causal questions, where the explanation tends to follow
    shortly after a lexically-matched setup line rather than surround it
    symmetrically -- the internal result cap below scales with the window so
    a wider `after` isn't silently truncated back down to the old size.

    Every returned segment also carries `lexical_anchor_keywords`/
    `lexical_anchor_keyword_count`, propagated from the *anchor* segment that
    earned it a window (not the segment's own text). This matters because a
    real causal explanation often shares zero words with the question -- e.g.
    "this is the only weapon to deal with that colonel" doesn't repeat any
    word from a "why do they free him" question -- so scoring/annotating a
    segment on its own overlap would rank the actual explanation *below* a
    same-topic but off-target segment that happens to repeat the subject's
    name. The anchor's overlap (computed from the setup line that pulled the
    explanation into range, e.g. "...the disasters that the Matteo wind has
    caused") is a much better relevance proxy for the whole matched cluster.
    On a window collision between two anchors, the higher-scoring anchor's
    keywords win -- same "better source wins on tie" precedence already used
    in `_expand_text_hits_with_neighbors`."""
    import re

    query = _clean_query_for_retrieval(question).lower()
    if not query or not segments:
        return []

    quoted_phrases = []
    for double_quoted, single_quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'', query):
        phrase = (double_quoted or single_quoted).strip().lower()
        if phrase:
            quoted_phrases.append(phrase)
    tokens = _extract_keywords(question)
    if not tokens and not quoted_phrases:
        return []

    scored: list[tuple[int, int, dict, set]] = []
    for idx, segment in enumerate(segments):
        text = _segment_text(segment)
        if not text:
            continue
        haystack = f"{segment.get('speaker', '')} {text}".lower()
        haystack_tokens = set(re.findall(r"[a-z0-9_'-]+", haystack))
        overlap = tokens & haystack_tokens
        score = len(overlap)

        for phrase in quoted_phrases:
            if phrase in haystack:
                score += 8 + len(phrase.split())

        if score > 0:
            scored.append((score, idx, segment, overlap))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    anchors = scored[:limit]

    index_info: dict[int, tuple[int, set]] = {}
    for score, anchor_idx, _, overlap in anchors:
        window = range(max(0, anchor_idx - before), min(len(segments), anchor_idx + after + 1))
        for idx in window:
            existing = index_info.get(idx)
            if existing is None or score > existing[0]:
                index_info[idx] = (score, overlap)

    results = []
    seen = set()
    max_results = max(limit * (before + after + 1), limit)
    for idx in sorted(index_info):
        segment = segments[idx]
        text = _segment_text(segment)
        if not text:
            continue
        key = _segment_key(segment)
        if key in seen:
            continue
        seen.add(key)
        _, anchor_overlap = index_info[idx]
        tagged = _segment_as_search_result(video_hash, segment)
        tagged["tier"] = "lexical"
        tagged["rank"] = None
        tagged["similarity"] = None
        tagged["lexical_anchor_keywords"] = sorted(anchor_overlap)
        tagged["lexical_anchor_keyword_count"] = len(anchor_overlap)
        results.append(tagged)
        if len(results) >= max_results:
            break

    print(f"Lexical transcript matches: {len(results)} context segments")
    return results


def _merge_text_results(primary: list, supplemental: list, max_results: int) -> list:
    """Concat + dedupe by (start, end, text prefix). `primary` must be the
    higher-tier list (semantic hits/neighbors) and `supplemental` the
    lower-tier one (lexical) -- dedup keeps the first occurrence, so this
    order is what makes an overlapping segment keep its higher-tier tag."""
    merged = []
    seen = set()

    for result in primary + supplemental:
        metadata = result.get("metadata") or {}
        key = (
            round(float(metadata.get("start", 0) or 0), 3),
            round(float(metadata.get("end", 0) or 0), 3),
            (result.get("text") or "")[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
        if len(merged) >= max_results:
            break

    return merged


def _speaker_segment_context(video_hash: str, question: str, limit: int) -> tuple[list, str, list]:
    """
    Build deterministic transcript context for speaker/person mention queries.

    Semantic search can miss short mention-only prompts like "tell me about
    @alex". When the query names a known transcript speaker, use that
    speaker's segments directly instead of returning no context.
    """
    speaker_names = _extract_all_speakers_from_query(question, video_hash)
    if not speaker_names:
        return [], "", []

    transcription = get_transcription_from_any_source(video_hash)
    if not transcription:
        return [], "", []

    segments = transcription.get("transcription", {}).get("segments", [])
    speaker_lowers = {name.lower() for name in speaker_names}
    matching_segments = [
        seg for seg in segments
        if (seg.get("speaker") or "").lower() in speaker_lowers
    ]
    if not matching_segments:
        return [], "", []

    selected = matching_segments[:max(1, limit)]
    search_results = []

    for seg in selected:
        text = (seg.get("translation") or seg.get("text") or "").strip()
        if not text:
            continue
        result = _segment_as_search_result(video_hash, seg)
        result["tier"] = "speaker_match"
        result["rank"] = None
        result["similarity"] = None
        search_results.append(result)

    if not search_results:
        return [], "", []

    context, sources = _format_text_context(video_hash, search_results)
    print(
        f"Speaker fallback context: {len(search_results)} segments for "
        f"{', '.join(speaker_names)}"
    )
    return search_results, context, sources


async def _retrieve_text_context(
    video_hash: str,
    question: str,
    n_results: int,
) -> tuple[list, str, list]:
    """
    Search transcript vector store and build context text + sources list.

    Returns:
        (search_results, context_text, sources)
        search_results is the raw list from transcript_embedding_service.search_transcript_chunks;
        empty list if none found.
    """
    query = _clean_query_for_retrieval(question)
    print(f"Searching for relevant context for question: {query}")
    user_id = _chat_user_id.get()
    if not user_id:
        return [], "", []
    search_results = await _run_in_executor(
        transcript_embedding_service.search_transcript_chunks, video_hash, query, user_id, n_results=n_results
    )

    transcription = get_transcription_from_any_source(video_hash)
    segments = (transcription or {}).get("transcription", {}).get("segments", [])

    if not search_results:
        # Rows can be missing on first access; index once from the persisted
        # transcript, then retry.
        if segments:
            try:
                await _run_in_executor(
                    transcript_embedding_service.index_transcript_chunks, video_hash, segments, user_id
                )
                search_results = await _run_in_executor(
                    transcript_embedding_service.search_transcript_chunks,
                    video_hash,
                    query,
                    user_id,
                    n_results=n_results,
                )
            except Exception as e:
                print(f"Transcript reindex/search retry failed: {e}")

    if not search_results:
        fallback = _speaker_segment_context(video_hash, query, limit=max(n_results * 3, 12))
        if fallback[0]:
            return fallback
        lexical_results = _lexical_segment_matches(
            video_hash,
            question,
            segments,
            limit=max(n_results, 6),
        )
        if lexical_results:
            context, sources = _format_text_context(video_hash, lexical_results)
            return lexical_results, context, sources
        return [], "", []

    raw_semantic_hits = search_results
    chunk_size_val = 3
    # Separate, non-competing budgets: hit_budget guarantees every top-k
    # hit's own segment survives (so `sources` never omits a hit that
    # actually grounded the answer -- see _expand_text_hits_with_neighbors'
    # docstring), sized tightly around what top-k hits actually claim
    # (chunk_size each, +2 slack for the boundary-touch overlap quirk).
    # neighbor_budget is the "read a bit more around it" allowance for
    # causal/"why" questions, independent of how much of hit_budget got used.
    # lexical_budget is a third, equally independent pool: without it,
    # expanded_results alone can saturate hit_budget+neighbor_budget (both
    # tiers full, zero dedup collisions), and _merge_text_results' shared
    # max_results cap then drops lexical_results entirely before the merge
    # loop ever reaches it -- silently defeating the lexical fallback exactly
    # when semantic search alone missed the answer, which is the one case it
    # exists to catch.
    causal = _is_causal_question(question)
    hit_budget = n_results * (chunk_size_val + 2)
    neighbor_budget = max(n_results * 6, 24) if causal else max(n_results * 4, 16)
    lexical_budget = 24 if causal else max(n_results * 2, 10)
    expanded_results = _expand_text_hits_with_neighbors(
        video_hash,
        search_results,
        segments,
        neighbor_chunks=1,
        neighbor_chunks_after=3 if causal else None,
        chunk_size=chunk_size_val,
        hit_budget=hit_budget,
        neighbor_budget=neighbor_budget,
    )
    lexical_results = _lexical_segment_matches(
        video_hash,
        question,
        segments,
        limit=max(3, n_results // 2),
        after=8 if causal else 1,
    )
    combined_results = _merge_text_results(
        expanded_results,
        lexical_results,
        max_results=hit_budget + neighbor_budget + lexical_budget,
    )

    if len(combined_results) != len(search_results):
        tier_counts: dict[str, int] = {}
        for r in combined_results:
            t = r.get("tier", "semantic_hit")
            tier_counts[t] = tier_counts.get(t, 0) + 1
        print(
            f"Text retrieval context expanded: semantic={len(search_results)}, "
            f"context_segments={len(combined_results)} ({tier_counts})"
        )

    context, sources = _format_text_context(
        video_hash, combined_results, top_ranked_hits=raw_semantic_hits, question=question
    )
    search_results = combined_results
    return search_results, context, sources
