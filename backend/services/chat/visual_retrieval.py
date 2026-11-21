"""Screenshot retrieval: CLIP search, face-tag frames and scene scoring."""
from typing import Awaitable, Callable, Optional
from services.image_embedding_service import image_embedding_service
from services.chat.context import _chat_user_id, _hash_resources_allowed, _run_in_executor, get_transcription_from_any_source
from services.chat.query import _clean_query_for_retrieval, _extract_all_speakers_from_query, _query_matches_user_visual_terms, _visual_query_variants
from services.chat.visual_refs import _cosine_similarity, _load_speaker_face_embeddings, _load_speaker_reference_embedding, _owner_scoped_screenshot_url, _parse_vector, _timestamp_from_screenshot_url


def _image_result_key(result: dict) -> str:
    url = result.get('screenshot_url') or result.get('screenshot_path', '')
    try:
        from services.gcs_service import gcs_service
        return gcs_service.extract_gcs_path_from_signed_url(url) or url.split("?", 1)[0]
    except Exception:
        return url.split("?", 1)[0]


async def _face_tag_image_results(
    video_hash: str,
    speaker_names: list[str],
    limit: int,
) -> list[dict]:
    """Use manually tagged faces as visual candidates for named-person queries."""
    if not speaker_names:
        return []

    try:
        from services.supabase_service import supabase as get_supabase
        user_id = _chat_user_id.get()
        if not user_id:
            return []
        face_client = get_supabase()
        rows = []
        for speaker_name in speaker_names:
            response = (
                face_client.table("face_tags")
                .select("speaker_name, screenshot_url, embedding")
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .eq("speaker_name", speaker_name)
                .limit(max(limit * 2, limit))
                .execute()
            )
            for row in response.data or []:
                rows.append(row)

        from config import settings
        references = {
            name: _load_speaker_reference_embedding(video_hash, name)
            for name in speaker_names
        }
        results = []
        seen_paths = set()
        for row in rows:
            screenshot_url = row.get("screenshot_url")
            if not screenshot_url:
                continue
            # A tag far from the person's reference is a mis-tag; don't let it
            # surface as identity evidence.
            reference = references.get(row.get("speaker_name"))
            tag_embedding = _parse_vector(row.get("embedding"))
            face_score = 1.0
            if reference and tag_embedding:
                face_score = max(0.0, _cosine_similarity(reference, tag_embedding))
                if face_score < settings.FACE_PRESENCE_SIMILARITY_THRESHOLD:
                    continue
            try:
                from services.gcs_service import gcs_service
                dedupe_key = gcs_service.extract_gcs_path_from_signed_url(screenshot_url) or screenshot_url.split("?", 1)[0]
            except Exception:
                dedupe_key = screenshot_url.split("?", 1)[0]
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)

            start = _timestamp_from_screenshot_url(screenshot_url)
            owned_url = _owner_scoped_screenshot_url(screenshot_url, video_hash)
            if not owned_url:
                continue
            results.append({
                "screenshot_url": owned_url,
                "metadata": {
                    "video_hash": video_hash,
                    "segment_id": f"face_tag_{len(results)}",
                    "start": start,
                    "end": start + 1.0,
                    "speaker": row.get("speaker_name") or speaker_names[0],
                },
                # A manual face tag is strong identity evidence, but it is
                # not evidence that the frame matches the requested action or
                # object. Keep it below CLIP scene matches so named-person
                # action queries do not get flooded by face-only examples.
                "similarity": 0.25,
                "face_score": face_score,
                "overlap_score": 0,
                "likely_speakers": [row.get("speaker_name") or speaker_names[0]],
                "source": "face_tag",
            })
            if len(results) >= limit:
                break

        if results:
            print(
                f"Face-tag visual candidates: {len(results)} screenshots for "
                f"{', '.join(speaker_names)}"
            )
        return results
    except Exception as e:
        print(f"Face-tag visual candidate lookup failed (non-critical): {e}")
        return []


async def _load_face_presence(
    video_hash: str,
    speaker_face_embeddings: dict[str, list[float]],
) -> tuple[dict[str, dict[str, float]], dict[str, list[tuple[float, float]]]]:
    """
    Load pre-indexed face-presence matches for named speakers.

    Returns:
      - face_presence_by_image: image_embedding_id -> speaker_name -> similarity
      - presence_timelines: speaker_name -> [(start, end), ...]
    """
    face_presence_by_image: dict[str, dict[str, float]] = {}
    presence_timelines: dict[str, list[tuple[float, float]]] = {
        speaker: [] for speaker in speaker_face_embeddings
    }
    if not speaker_face_embeddings:
        return face_presence_by_image, presence_timelines

    try:
        from config import settings
        from services.supabase_service import supabase as get_supabase

        face_client = get_supabase()
        user_id = _chat_user_id.get()
        if not user_id:
            return face_presence_by_image, presence_timelines
        for speaker, embedding in speaker_face_embeddings.items():
            response = await _run_in_executor(
                lambda emb=embedding: face_client.rpc(
                    "match_faces_by_embedding",
                    {
                        "p_user_id": user_id,
                        "target_video_hash": video_hash,
                        "query_embedding": emb,
                        "similarity_threshold": settings.FACE_PRESENCE_SIMILARITY_THRESHOLD,
                    },
                ).execute()
            )
            for row in response.data or []:
                image_id = str(row.get("image_embedding_id") or "")
                if not image_id:
                    continue
                similarity = float(row.get("similarity") or 0.0)
                face_presence_by_image.setdefault(image_id, {})[speaker] = max(
                    similarity,
                    face_presence_by_image.get(image_id, {}).get(speaker, 0.0),
                )
                presence_timelines.setdefault(speaker, []).append((
                    float(row.get("start_time") or 0.0),
                    float(row.get("end_time") or 0.0),
                ))
    except Exception as e:
        print(f"  Face presence lookup failed (non-critical): {e}")
        return {}, {speaker: [] for speaker in speaker_face_embeddings}

    for speaker, timeline in presence_timelines.items():
        if timeline:
            print(f"  Face presence for '{speaker}': {len(timeline)} matched screenshots")

    return face_presence_by_image, presence_timelines


def _scene_score(result: dict) -> float:
    """Best available scene-match signal for a visual candidate. MiniLM caption
    cosines for real matches run ~0.45-0.8 vs CLIP's flat ~0.2-0.3 band, so
    max() lets confident caption hits outrank weak CLIP hits without any scale
    calibration."""
    sim = result.get('similarity', 0) or 0
    if sim == 0 and 'distance' in result:
        sim = max(0, 1 - result['distance'])
    return max(sim, result.get('caption_similarity') or 0.0)


async def _retrieve_visual_context(
    video_hash: str,
    question: str,
    n_images: int,
    user_visual_terms: Optional[set[str]] = None,
    user_visual_phrases: Optional[list[str]] = None,
    phase_cb: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> dict:
    """
    Search image embeddings, apply temporal + face re-ranking, and return visual context.

    phase_cb: optional async callback(phase_name, label) called before each sub-stage.
              The streaming endpoint passes a coroutine that emits SSE phase events;
              the sync endpoint passes None.

    Returns a dict with keys:
        images_indexed (bool) - False means images are not indexed; all other keys absent
        image_paths, visual_context, visual_sources, visual_query_used,
        image_results, face_tags_available, speaker_names
    """
    if not _hash_resources_allowed.get():
        return {"images_indexed": False}
    user_id = _chat_user_id.get()
    if not user_id:
        return {"images_indexed": False}
    images_indexed = image_embedding_service.image_collection_exists(video_hash, user_id)

    try:
        # Extract ALL speaker names from the query
        speaker_names = _extract_all_speakers_from_query(question, video_hash)
        transcription = None
        segments = []
        total_segments = 0
        transcription = get_transcription_from_any_source(video_hash)
        if transcription:
            segments = transcription.get('transcription', {}).get('segments', [])
            total_segments = len(segments)

        # CLIP doesn't know specific people by name; replace names with generic "person"/"people"
        visual_query = _clean_query_for_retrieval(question)
        if speaker_names:
            import re
            replacement = "person" if len(speaker_names) == 1 else "people"
            for speaker_name in speaker_names:
                visual_query = re.sub(
                    rf'\b{re.escape(speaker_name)}\b',
                    replacement,
                    visual_query,
                    flags=re.IGNORECASE
                )
            print(f"Visual search: transformed '{question}' -> '{visual_query}'")
            visual_query_used = visual_query
        else:
            visual_query_used = question

        image_results = []
        query_variants = []
        user_visual_terms = user_visual_terms or set()
        user_visual_phrases = user_visual_phrases or []
        configured_visual_query = _query_matches_user_visual_terms(visual_query, user_visual_terms)
        if images_indexed:
            print(f"Visual analysis requested, searching for {n_images} relevant images...")

            # Sub-stage: CLIP scene search
            if phase_cb is not None:
                await phase_cb("analyzing_scenes", "Analyzing scenes")

            seen_image_paths = set()
            query_variants = _visual_query_variants(
                visual_query,
                user_visual_terms=user_visual_terms,
                user_visual_phrases=user_visual_phrases,
            )[:6]
            per_variant_results = max(n_images, 4)
            for query_variant in query_variants:
                variant_results = await _run_in_executor(
                    image_embedding_service.search_images,
                    video_hash,
                    query_variant,
                    user_id,
                    n_results=per_variant_results,
                    speaker_filter=None,
                )

                for result in variant_results:
                    key = _image_result_key(result)
                    if key in seen_image_paths:
                        continue
                    seen_image_paths.add(key)
                    result["visual_query_variant"] = query_variant
                    image_results.append(result)

            if len(query_variants) > 1:
                print(
                    f"Visual multi-query search: {len(query_variants)} variants, "
                    f"{len(image_results)} unique CLIP candidates"
                )

            clip_candidate_limit = max(n_images * 4, min(32, n_images * (1 + total_segments // 100)))
            if len(image_results) > clip_candidate_limit:
                image_results.sort(key=_scene_score, reverse=True)
                image_results = image_results[:clip_candidate_limit]

            # Third candidate source: vision-caption semantic search. Captions
            # capture actions CLIP can't encode.
            from config import settings
            caption_results = await _run_in_executor(
                image_embedding_service.search_images_by_caption,
                video_hash,
                visual_query,
                user_id,
                max(n_images, 6),
            )
            caption_added = 0
            for result in caption_results:
                if (result.get('similarity') or 0) < settings.CAPTION_MIN_SIMILARITY:
                    continue
                key = _image_result_key(result)
                if key in seen_image_paths:
                    # Frame already found by CLIP: annotate it so the
                    # caption signal still boosts its score.
                    for existing in image_results:
                        if _image_result_key(existing) == key:
                            existing['caption'] = result.get('caption')
                            existing['caption_similarity'] = result['similarity']
                            break
                    continue
                seen_image_paths.add(key)
                result['caption_similarity'] = result['similarity']
                image_results.append(result)
                caption_added += 1
            if caption_results:
                print(
                    f"Caption search: {len(caption_results)} matches, "
                    f"{caption_added} new candidates added"
                )
        else:
            print(
                f"Images not indexed for video {video_hash}. "
                "Checking face tags before falling back to text-only analysis."
            )

        # Scene candidates restricted to frames where the named person actually
        # appears. A global CLIP top-K is dominated by other people's frames, so
        # "person + action" queries would otherwise never reach her real scenes.
        preloaded_presence = None
        if speaker_names and images_indexed:
            presence_face_embeddings = _load_speaker_face_embeddings(video_hash, speaker_names)
            if presence_face_embeddings:
                preloaded_presence = (
                    presence_face_embeddings,
                    await _load_face_presence(video_hash, presence_face_embeddings),
                )
                present_ids = sorted(preloaded_presence[1][0])
                restricted_added = 0
                for query_variant in query_variants:
                    for result in await _run_in_executor(
                        image_embedding_service.search_images_within,
                        video_hash,
                        query_variant,
                        user_id,
                        present_ids,
                        n_results=max(n_images, 4),
                    ):
                        key = _image_result_key(result)
                        if key in seen_image_paths:
                            continue
                        seen_image_paths.add(key)
                        result["visual_query_variant"] = query_variant
                        image_results.append(result)
                        restricted_added += 1
                print(
                    f"Person-restricted scene search: {len(present_ids)} frames with "
                    f"{', '.join(speaker_names)}, {restricted_added} new candidates added"
                )
        person_frames_found = bool(preloaded_presence and preloaded_presence[1][0])

        face_tag_results = []
        # Tagged frames are only a fallback when the face-presence index has no
        # frames for this person; otherwise they crowd out scene-relevant ones.
        if speaker_names and not person_frames_found:
            face_tag_results = await _face_tag_image_results(
                video_hash,
                speaker_names,
                n_images,
            )
            if face_tag_results:
                if configured_visual_query and image_results:
                    print(
                        "Face-tag candidates available, but using them for identity "
                        "scoring only because the query matches configured visual search terms."
                    )
                else:
                    deduped = []
                    seen_paths = set()
                    # For identity-only questions, include manually tagged
                    # face screenshots as candidates. For action questions,
                    # keep CLIP scene matches as the candidate pool and use
                    # face tags only to score whether those scenes include the
                    # named person.
                    for source_results in (image_results, face_tag_results):
                        for result in source_results:
                            key = _image_result_key(result)
                            if key in seen_paths:
                                continue
                            seen_paths.add(key)
                            deduped.append(result)
                    image_results = deduped

        face_tags_available = False

        if configured_visual_query and image_results:
            before_trim = len(image_results)
            image_results.sort(key=_scene_score, reverse=True)
            image_results = image_results[:n_images]
            if before_trim != len(image_results):
                print(
                    "Configured visual query: trimmed scene candidates before "
                    f"face scoring ({before_trim} -> {len(image_results)})"
                )

        # Phase 1: Temporal Correlation Scoring
        if speaker_names and image_results:
            print(f"Applying presence correlation scoring for speakers: {speaker_names}")

            if preloaded_presence:
                speaker_face_embeddings = preloaded_presence[0]
                face_presence_by_image, presence_timelines = preloaded_presence[1]
            else:
                speaker_face_embeddings = _load_speaker_face_embeddings(video_hash, speaker_names)
                face_presence_by_image, presence_timelines = await _load_face_presence(
                    video_hash,
                    speaker_face_embeddings,
                )
            face_tags_available = bool(speaker_face_embeddings)
            has_face_presence = any(presence_timelines.values())

            if transcription:
                if has_face_presence:
                    speaker_timelines = presence_timelines
                    for name in speaker_names:
                        print(f"  Speaker '{name}': {len(speaker_timelines.get(name, []))} face-presence spans")
                else:
                    speaker_timelines = {}
                    for name in speaker_names:
                        speaker_timelines[name] = [
                            (seg['start'], seg['end'])
                            for seg in segments
                            if seg.get('speaker', '').lower() == name.lower()
                        ]
                        print(f"  Speaker '{name}': {len(speaker_timelines[name])} voice segments")

                for result in image_results:
                    img_start = float(result['metadata'].get('start', 0) or 0)
                    img_end = float(result['metadata'].get('end', 0) or 0)

                    overlap_score = 0
                    overlapping_speakers = []

                    for speaker, timeline in speaker_timelines.items():
                        for seg_start, seg_end in timeline:
                            if img_start <= seg_end and img_end >= seg_start:
                                overlap_score += 1
                                if speaker not in overlapping_speakers:
                                    overlapping_speakers.append(speaker)

                    from config import settings
                    if settings.CHAT_DEBUG_LOGS and overlap_score == 0 and speaker_timelines:
                        first_speaker = list(speaker_timelines.keys())[0]
                        tl = speaker_timelines[first_speaker]
                        if tl:
                            print(f"  DEBUG overlap=0: img=[{img_start:.1f}-{img_end:.1f}], "
                                  f"first segment=[{tl[0][0]:.1f}-{tl[0][1]:.1f}], "
                                  f"last segment=[{tl[-1][0]:.1f}-{tl[-1][1]:.1f}], "
                                  f"total={len(tl)} segments")

                    result['overlap_score'] = overlap_score
                    result['likely_speakers'] = overlapping_speakers

                # Sub-stage: face re-ranking (only if face tags exist)
                if face_tags_available:
                    if phase_cb is not None:
                        await phase_cb("matching_faces", "Matching faces")

                    print("Computing face scores for visual results...")
                    try:
                        for result in image_results:
                            # Manually tagged face rows are already positive
                            # identity evidence; re-running face detection on
                            # them is slow and can fail on marginal frames.
                            if result.get("source") == "face_tag":
                                result.setdefault('face_score', 1.0)
                                if not result.get('likely_speakers'):
                                    result['likely_speakers'] = speaker_names
                                continue

                            image_id = str(result.get('metadata', {}).get('image_embedding_id') or "")
                            speaker_scores = face_presence_by_image.get(image_id, {})
                            if speaker_scores:
                                result['face_score'] = max(speaker_scores.values())
                                likely = [
                                    speaker for speaker, score in speaker_scores.items()
                                    if score >= 0.5
                                ]
                                if likely:
                                    result['likely_speakers'] = sorted(set(result.get('likely_speakers', []) + likely))
                                continue

                            result['face_score'] = 0.0

                        if not has_face_presence:
                            from services.face_service import face_service
                            print("No face-presence rows found; falling back to query-time face detection")
                            for result in image_results:
                                if result.get("source") == "face_tag":
                                    continue
                                screenshot_reference = result.get('screenshot_url') or result.get('screenshot_path', '')
                                screenshot_url = _owner_scoped_screenshot_url(
                                    screenshot_reference, video_hash
                                )
                                if not screenshot_url:
                                    continue

                                detected = await _run_in_executor(face_service.detect_faces, screenshot_url)
                                if not detected:
                                    continue

                                max_sim = 0.0
                                matched_speakers = []
                                for det_face in detected:
                                    for speaker, ref_emb in speaker_face_embeddings.items():
                                        sim = face_service.compute_face_similarity(
                                            det_face['embedding'], ref_emb
                                        )
                                        if sim >= 0.5:
                                            matched_speakers.append(speaker)
                                        max_sim = max(max_sim, sim)
                                result['face_score'] = max(0.0, max_sim)
                                if matched_speakers:
                                    result['likely_speakers'] = sorted(
                                        set(result.get('likely_speakers', []) + matched_speakers)
                                    )
                    except Exception as e:
                        print(f"  Face scoring failed (falling back to no face): {e}")
                        face_tags_available = False

                # Hybrid ranking: temporal is on-screen face presence when the
                # face-presence index exists, otherwise speaker voice overlap.
                for result in image_results:
                    clip_score = _scene_score(result)

                    max_overlap = 3
                    normalized_overlap = min(result.get('overlap_score', 0), max_overlap) / max_overlap

                    if face_tags_available:
                        face_score = result.get('face_score', 0.0)
                        if configured_visual_query:
                            result['hybrid_score'] = 0.95 * clip_score + 0.05 * face_score
                        else:
                            result['hybrid_score'] = 0.6 * clip_score + 0.15 * normalized_overlap + 0.25 * face_score
                    else:
                        result['hybrid_score'] = 0.8 * clip_score + 0.2 * normalized_overlap

                image_results.sort(key=lambda x: x.get('hybrid_score', 0), reverse=True)

                if face_tags_available and configured_visual_query:
                    ranking_mode = "95% CLIP + 5% face"
                elif face_tags_available:
                    ranking_mode = "60% CLIP + 15% temporal + 25% face"
                else:
                    ranking_mode = "80% CLIP + 20% temporal"
                print(f"Scored {len(image_results)} visual results with hybrid ranking ({ranking_mode})")
                from config import settings
                if settings.CHAT_DEBUG_LOGS:
                    for i, result in enumerate(image_results[:3]):
                        face_info = f", face={result.get('face_score', 0):.3f}" if face_tags_available else ""
                        print(f"  Result {i+1}: hybrid={result.get('hybrid_score', 0):.3f}, "
                              f"clip={result.get('similarity', 0):.3f}, "
                              f"overlap={result.get('overlap_score', 0)}{face_info}, "
                              f"variant={result.get('visual_query_variant', result.get('source', 'unknown'))}, "
                              f"speakers={result.get('likely_speakers', [])}")

        image_paths = []
        visual_context = ""
        visual_sources = []

        if image_results:
            if not any("hybrid_score" in result for result in image_results):
                image_results.sort(key=_scene_score, reverse=True)
            image_results = image_results[:n_images]
            owned_image_results = []
            for result in image_results:
                screenshot_reference = (
                    result.get('screenshot_url') or result.get('screenshot_path', '')
                )
                screenshot_url = _owner_scoped_screenshot_url(
                    screenshot_reference, video_hash
                )
                if not screenshot_url:
                    continue
                result = dict(result)
                result['screenshot_url'] = screenshot_url
                result.pop('screenshot_path', None)
                owned_image_results.append(result)
            image_results = owned_image_results
            print(f"Found {len(image_results)} relevant images")
            image_paths = [result['screenshot_url'] for result in image_results]

            visual_parts = []
            for i, img_result in enumerate(image_results):
                metadata = img_result['metadata']
                screenshot_url = img_result['screenshot_url']

                speaker_display = ', '.join(img_result.get('likely_speakers', [])) or metadata.get('speaker') or 'unknown'
                caption_note = f", Caption: {img_result['caption']}" if img_result.get('caption') else ''
                visual_parts.append(
                    f"Screenshot {i+1} - Timestamp: {metadata['start']:.2f}s - {metadata['end']:.2f}s, "
                    f"Speaker: {speaker_display}{caption_note}"
                )

                visual_sources.append({
                    "start_time": f"{int(metadata['start'] // 3600):02d}:{int((metadata['start'] % 3600) // 60):02d}:{int(metadata['start'] % 60):02d}",
                    "end_time": f"{int(metadata['end'] // 3600):02d}:{int((metadata['end'] % 3600) // 60):02d}:{int(metadata['end'] % 60):02d}",
                    "start": metadata['start'],
                    "end": metadata['end'],
                    "speaker": speaker_display,
                    "screenshot_url": screenshot_url,
                    "type": "visual",
                    "likely_speakers": img_result.get('likely_speakers', []),
                    "overlap_score": img_result.get('overlap_score', 0),
                    "visual_query_variant": img_result.get('visual_query_variant'),
                    "visual_similarity": img_result.get('similarity'),
                    "hybrid_score": img_result.get('hybrid_score'),
                    "face_score": img_result.get('face_score'),
                    "caption": img_result.get("caption"),
                    "caption_similarity": img_result.get("caption_similarity"),
                    "source_kind": img_result.get('source') or "clip",
                    "evidence_label": (
                        "Identity match"
                        if img_result.get('source') == "face_tag"
                        else "Caption match"
                        if img_result.get("source") == "caption"
                        else "Scene + identity"
                        if img_result.get('likely_speakers')
                        else "Scene match"
                    )
                })

            visual_context = "\n".join(visual_parts)
            print(f"Visual context: {visual_context}")
        else:
            print("No relevant images found for the query")
            if not images_indexed:
                return {"images_indexed": False}

        return {
            "images_indexed": images_indexed or bool(image_results),
            "image_paths": image_paths,
            "visual_context": visual_context,
            "visual_sources": visual_sources,
            "visual_query_used": visual_query_used,
            "visual_query_variants": query_variants,
            "image_results": image_results,
            "face_tags_available": face_tags_available,
            "speaker_names": speaker_names,
        }

    except Exception as e:
        print(f"Warning: Failed to search images: {str(e)}")
        return {
            "images_indexed": True,
            "image_paths": [],
            "visual_context": "",
            "visual_sources": [],
            "visual_query_used": question,
            "visual_query_variants": [],
            "image_results": [],
            "face_tags_available": False,
            "speaker_names": [],
        }
