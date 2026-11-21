"""Runs a person-comparison answer end to end."""
import json
from typing import Dict, Optional
from fastapi import Request
from models import ChatRequest
from services.model_catalog import ReasoningEffort
from services.chat.comparison.appearances import _comparison_appearance_key, _load_face_tag_appearances, _load_person_appearances_with_fallback, _merge_comparison_appearances, _video_duration_seconds
from services.chat.comparison.intent import ComparisonIntent
from services.chat.comparison.state_pairs import _select_multi_person_state_pair, _select_state_pair
from services.chat.context import get_transcription_from_any_source
from services.chat.providers import _get_chat_provider, llm_manager
from services.chat.segments import _format_segment_time, _segment_bounds, _segment_text
from services.chat.visual_refs import _load_speaker_reference_embedding


def _transcript_window_context(video_hash: str, timestamps: list[float], window_seconds: float = 15.0) -> str:
    transcription = get_transcription_from_any_source(video_hash)
    segments = (transcription or {}).get("transcription", {}).get("segments", [])
    if not segments:
        return "No transcript context is available for these moments."

    blocks = []
    for timestamp in timestamps:
        nearby = []
        for segment in segments:
            text = _segment_text(segment)
            if not text:
                continue
            start, end, start_time, end_time = _segment_bounds(segment)
            if start <= timestamp + window_seconds and end >= timestamp - window_seconds:
                nearby.append(f"[{start_time} - {end_time}] {segment.get('speaker') or 'Unknown'}: {text}")
        label = _format_segment_time(timestamp)
        blocks.append(f"Moment around [{label}]:\n" + ("\n".join(nearby) if nearby else "No nearby transcript lines."))
    return "\n\n".join(blocks)


def _comparison_frame_metadata(appearance: dict) -> dict:
    start = float(appearance.get("start_time") or 0.0)
    metadata = {
        "url": appearance.get("screenshot_url"),
        "timestamp_seconds": start,
        "timestamp": _format_segment_time(start),
        "bbox": appearance.get("bbox"),
    }
    if appearance.get("label"):
        metadata["label"] = appearance.get("label")
    if appearance.get("people"):
        metadata["people"] = appearance.get("people")
    if appearance.get("bboxes"):
        metadata["bboxes"] = appearance.get("bboxes")
    return metadata


def _timeline_frame_metadata(appearance: dict) -> dict:
    start = float(appearance.get("start_time") or 0.0)
    metadata = {
        "url": appearance.get("screenshot_url"),
        "timestamp_seconds": start,
        "timestamp": _format_segment_time(start),
        "bbox": appearance.get("bbox"),
    }
    similarity = appearance.get("similarity")
    if similarity is not None:
        try:
            metadata["similarity"] = float(similarity)
        except (TypeError, ValueError):
            pass
    if appearance.get("low_confidence"):
        metadata["low_confidence"] = True
    return metadata


def _select_timeline_candidates(
    appearances: list[dict],
    pair: Optional[tuple[dict, dict]],
    video_duration: float,
    target_count: int = 8,
) -> list[dict]:
    """
    Pick a small set of evenly-spread, high-quality appearances for the timeline strip.

    Returns appearance dicts (NOT yet projected to metadata), sorted by start_time.
    Force-includes both Frame A and Frame B from `pair` so the strip always shows the
    active pair in context. Enrichment fields (people/bboxes/label) on the pair are
    preserved.
    """
    with_url = [
        appearance for appearance in (appearances or [])
        if appearance.get("screenshot_url")
    ]
    if not with_url:
        if pair:
            return list(pair)
        return []

    times = [float(row.get("start_time") or 0.0) for row in with_url]
    t_min = min(times)
    t_max = max(times)
    distinct_timestamps = {round(t, 2) for t in times}

    bucket_count = min(target_count, len(distinct_timestamps))
    if bucket_count <= 0:
        bucket_count = 1

    picks_by_bucket: dict[int, dict] = {}
    span = max(t_max - t_min, 1e-6)
    for row in with_url:
        t = float(row.get("start_time") or 0.0)
        # Map t into [0, bucket_count); clamp the upper bound exactly into the last bucket.
        idx = int(((t - t_min) / span) * bucket_count)
        if idx >= bucket_count:
            idx = bucket_count - 1
        elif idx < 0:
            idx = 0
        existing = picks_by_bucket.get(idx)
        if (
            existing is None
            or float(row.get("similarity") or 0.0) > float(existing.get("similarity") or 0.0)
        ):
            picks_by_bucket[idx] = row

    picks = list(picks_by_bucket.values())

    # Enforce minimum spacing between picks.
    min_gap = max(2.0, video_duration * 0.01) if video_duration else 2.0
    picks.sort(key=lambda row: float(row.get("start_time") or 0.0))
    filtered: list[dict] = []
    for row in picks:
        if not filtered:
            filtered.append(row)
            continue
        prev = filtered[-1]
        gap = abs(float(row.get("start_time") or 0.0) - float(prev.get("start_time") or 0.0))
        if gap < min_gap:
            # Keep the higher-similarity of the two.
            if float(row.get("similarity") or 0.0) > float(prev.get("similarity") or 0.0):
                filtered[-1] = row
            continue
        filtered.append(row)

    # Force-include Frame A and Frame B. Replace the nearest pick by timestamp so we
    # preserve the enriched pair (joint bboxes / labels) and don't grow past the target.
    def _force_include(target: dict) -> None:
        target_t = float(target.get("start_time") or 0.0)
        target_key = _comparison_appearance_key(target)
        for i, row in enumerate(filtered):
            if _comparison_appearance_key(row) == target_key:
                filtered[i] = target  # replace with enriched copy
                return
        if not filtered:
            filtered.append(target)
            return
        nearest_idx = min(
            range(len(filtered)),
            key=lambda i: abs(float(filtered[i].get("start_time") or 0.0) - target_t),
        )
        nearest = filtered[nearest_idx]
        nearest_gap = abs(float(nearest.get("start_time") or 0.0) - target_t)
        if nearest_gap < min_gap:
            filtered[nearest_idx] = target
        else:
            filtered.append(target)

    if pair:
        _force_include(pair[0])
        _force_include(pair[1])

    filtered.sort(key=lambda row: float(row.get("start_time") or 0.0))
    return filtered


def _format_person_comparison_answer(
    person_name: str,
    frame_a: dict,
    frame_b: dict,
    prose: str,
    secondary_person_name: Optional[str] = None,
    timeline_appearances: Optional[list[dict]] = None,
) -> str:
    metadata = {
        "person": person_name,
        "frame_a": frame_a,
        "frame_b": frame_b,
    }
    if secondary_person_name:
        metadata["secondary_person"] = secondary_person_name
    if timeline_appearances:
        metadata["timeline"] = [
            _timeline_frame_metadata(appearance)
            for appearance in timeline_appearances
            if appearance.get("screenshot_url")
        ]
    return (
        "## Person Comparison\n\n"
        "```json\n"
        f"{json.dumps(metadata, ensure_ascii=False)}\n"
        "```\n\n"
        f"{(prose or '').strip()}"
    )


async def _run_person_comparison_llm(
    request: Request,
    *,
    person_name: str,
    secondary_person_name: Optional[str],
    frame_a_appearance: dict,
    frame_b_appearance: dict,
    question: str,
    custom_instructions: Optional[str],
    provider_name: Optional[str],
    video_hash: str,
    timeline_appearances: Optional[list[dict]] = None,
    model: Optional[str] = None,
    reasoning_effort: Optional[ReasoningEffort] = None,
) -> Dict:
    """
    Build the comparison prompt for the resolved pair, run the vision LLM, and return
    the standard chat response shape. Shared by the auto-detect path and the swap endpoint.
    """
    frame_a = _comparison_frame_metadata(frame_a_appearance)
    frame_b = _comparison_frame_metadata(frame_b_appearance)
    transcript_context = _transcript_window_context(
        video_hash,
        [frame_a["timestamp_seconds"], frame_b["timestamp_seconds"]],
        window_seconds=15.0,
    )

    # Resolve timeline intermediates (frames that are neither A nor B).
    intermediates: list[dict] = []
    if timeline_appearances:
        a_key = _comparison_appearance_key(frame_a_appearance)
        b_key = _comparison_appearance_key(frame_b_appearance)
        intermediates = [
            appearance for appearance in timeline_appearances
            if appearance.get("screenshot_url")
            and _comparison_appearance_key(appearance) not in {a_key, b_key}
        ]
        intermediates.sort(key=lambda row: float(row.get("start_time") or 0.0))

    provider = await _get_chat_provider(request, provider_name, model, reasoning_effort)
    if not provider.supports_vision():
        provider = await _get_chat_provider(request, "grok")
        provider_name = "grok"

    system_message = (
        "You compare two video frames involving a tagged person. "
        "Focus on visible evidence only and be explicit about uncertainty. "
        "Compare exactly these axes: emotion/facial expression, physical appearance "
        "(clothing, hair, injuries, dirt, age cues), and surroundings/context "
        "(location, lighting, nearby people or objects). Cite timestamps in [HH:MM:SS] format."
    )
    if secondary_person_name:
        system_message += (
            f" Frame A may be selected because it contains both {person_name} "
            f"and {secondary_person_name}; do not claim the second person is present "
            "in Frame B unless visibly shown or supported by the metadata."
        )
    if intermediates:
        system_message += (
            "\n\nAdditional intermediate frames are provided (image positions 3 onward) at "
            "timestamps spread across the video. After the three-axis comparison and the "
            "closing change sentence, add ONE FINAL paragraph that begins with "
            "\"**Timeline arc:**\" (bold lead-in, same line as content, no heading). In that "
            "paragraph, walk through ALL frames in chronological order — including Frame A and "
            "Frame B — briefly noting visible change at each timestamp in [HH:MM:SS] format. "
            "Aim for ~12 words per timestamp. Keep it grounded in what you actually see; do "
            "not invent. The whole paragraph should read as a short narrative."
        )
    if custom_instructions:
        system_message += (
            "\n\nUser's custom instructions (follow these preferences):\n"
            f"{custom_instructions}"
        )

    user_message_parts = [
        f"Question: {question}",
        "",
        f"Tagged person: {person_name}",
    ]
    if secondary_person_name:
        user_message_parts.append(f"Additional tagged person requested: {secondary_person_name}")
    if frame_a.get("label"):
        user_message_parts.append(f"Frame A label: {frame_a.get('label')}")
    if frame_b.get("label"):
        user_message_parts.append(f"Frame B label: {frame_b.get('label')}")
    if frame_a.get("people"):
        user_message_parts.append(f"Frame A people: {', '.join(frame_a.get('people') or [])}")
    if frame_b.get("people"):
        user_message_parts.append(f"Frame B people: {', '.join(frame_b.get('people') or [])}")
    user_message_parts.extend([
        f"Frame A timestamp: [{frame_a['timestamp']}]",
        f"Frame B timestamp: [{frame_b['timestamp']}]",
    ])
    if intermediates:
        intermediate_lines = []
        for offset, appearance in enumerate(intermediates, start=3):
            ts = _format_segment_time(float(appearance.get("start_time") or 0.0))
            intermediate_lines.append(f"  - Image {offset} → [{ts}]")
        user_message_parts.extend([
            "",
            "Intermediate timeline frames (in chronological order, for the Timeline arc):",
            *intermediate_lines,
        ])
    user_message_parts.extend([
        "",
        f"Nearby transcript context:\n{transcript_context}",
        "",
        "Write a concise comparison. Use bullets grouped by the three requested axes, "
        "then end with one sentence summarizing the biggest visible change.",
    ])
    if intermediates:
        user_message_parts[-1] += (
            " Then add the **Timeline arc:** paragraph as described in the system message."
        )

    messages = [
        {
            "role": "system",
            "content": system_message,
        },
        {
            "role": "user",
            "content": "\n".join(user_message_parts),
        },
    ]
    image_paths = [frame_a["url"], frame_b["url"]]
    image_paths.extend(
        appearance["screenshot_url"] for appearance in intermediates
    )
    prose = await provider.generate_with_images(
        messages,
        image_paths=image_paths,
        temperature=0.3,
        max_tokens=1800,
    )

    return {
        "answer": _format_person_comparison_answer(
            person_name,
            frame_a,
            frame_b,
            prose,
            secondary_person_name=secondary_person_name,
            timeline_appearances=timeline_appearances,
        ),
        "sources": [],
        "provider_used": provider_name or llm_manager.default_provider,
        "video_hash": video_hash,
    }


async def _handle_person_comparison(
    request: Request,
    chat_request: ChatRequest,
    intent: ComparisonIntent,
) -> Dict:
    if not intent.person_name:
        name_text = f" {intent.unmatched_name}" if intent.unmatched_name else " that person"
        return {
            "answer": f"I don't recognise{name_text} yet. Tag a face in any screenshot first.",
            "sources": [],
            "provider_used": chat_request.provider or "none",
            "video_hash": chat_request.video_hash,
        }

    video_hash = chat_request.video_hash
    appearances = await _load_person_appearances_with_fallback(video_hash, intent.person_name)
    video_duration = _video_duration_seconds(video_hash, appearances)
    pair = None
    if intent.secondary_person_name:
        secondary_appearances = await _load_person_appearances_with_fallback(
            video_hash,
            intent.secondary_person_name,
        )
        video_duration = _video_duration_seconds(
            video_hash,
            [*appearances, *secondary_appearances],
        )
        pair = _select_multi_person_state_pair(
            primary_appearances=appearances,
            secondary_appearances=secondary_appearances,
            video_duration=video_duration,
            query=chat_request.question,
            primary_person=intent.person_name,
            secondary_person=intent.secondary_person_name,
        )

    person_names = [n for n in (intent.person_name, intent.secondary_person_name) if n]
    if not pair:
        pair = _select_state_pair(appearances, video_duration, chat_request.question, person_names)
    if not pair:
        print(
            f"[Chat] Face comparison could not select a distinct pair from "
            f"{len(appearances)} presence appearances for '{intent.person_name}'; "
            "retrying with manual face tags"
        )
        reference_embedding = _load_speaker_reference_embedding(video_hash, intent.person_name)
        tagged_appearances = (
            _load_face_tag_appearances(video_hash, intent.person_name, reference_embedding)
            if reference_embedding
            else []
        )
        appearances = _merge_comparison_appearances(appearances, tagged_appearances)
        video_duration = _video_duration_seconds(video_hash, appearances)
        pair = _select_state_pair(appearances, video_duration, chat_request.question, person_names)

    if not pair:
        return {
            "answer": (
                f"I found {intent.person_name}, but not enough separate face appearances "
                "to compare yet. Ask a normal chat question, or index more screenshots first."
            ),
            "sources": [],
            "provider_used": chat_request.provider or "none",
            "video_hash": video_hash,
        }

    timeline_appearances = _select_timeline_candidates(appearances, pair, video_duration)

    return await _run_person_comparison_llm(
        request,
        person_name=intent.person_name,
        secondary_person_name=intent.secondary_person_name,
        frame_a_appearance=pair[0],
        frame_b_appearance=pair[1],
        question=chat_request.question,
        custom_instructions=chat_request.custom_instructions,
        provider_name=chat_request.provider,
        video_hash=video_hash,
        timeline_appearances=timeline_appearances,
        model=chat_request.model,
        reasoning_effort=chat_request.reasoning_effort,
    )
