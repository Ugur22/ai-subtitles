"""Audio-event retrieval for chat context."""
from services.transcript_embedding_service import transcript_embedding_service
from services.chat.context import _chat_user_id, _run_in_executor



def _without_legacy_emotion(results):
    cleaned = []
    for result in results:
        events = [e for e in result['description'].split(", ") if not e.startswith("emotion:")]
        if events:
            cleaned.append({**result, 'description': ", ".join(events)})
    return cleaned

async def _retrieve_audio_context(
    video_hash: str,
    question: str,
    search_results: list,
    image_results: list,
) -> tuple[str, list, bool]:
    """
    Search audio event vector store, apply temporal re-ranking, and return audio context.

    Returns:
        (audio_context, audio_sources, audio_indexed)
    """
    user_id = _chat_user_id.get()
    if not user_id or not transcript_embedding_service.audio_events_exist(video_hash, user_id):
        return "", [], False

    audio_context = ""
    audio_sources = []

    try:
        audio_results = await _run_in_executor(
            transcript_embedding_service.search_audio_events,
            video_hash,
            question,
            user_id,
            n_results=20
        )
        audio_results = _without_legacy_emotion(audio_results or [])

        if audio_results:
            temporal_anchors = []

            if search_results:
                for sr in search_results:
                    s = sr.get('metadata', {}).get('start')
                    e = sr.get('metadata', {}).get('end')
                    if s is not None and e is not None:
                        temporal_anchors.append((float(s), float(e)))

            if image_results:
                for ir in image_results:
                    s = ir.get('metadata', {}).get('start')
                    e = ir.get('metadata', {}).get('end')
                    if s is not None and e is not None:
                        temporal_anchors.append((float(s), float(e)))

            if temporal_anchors:
                for audio_result in audio_results:
                    a_start = float(audio_result['metadata'].get('start', 0) or 0)
                    a_end = float(audio_result['metadata'].get('end', 0) or 0)
                    a_mid = (a_start + a_end) / 2

                    min_dist = float('inf')
                    for anchor_start, anchor_end in temporal_anchors:
                        anchor_mid = (anchor_start + anchor_end) / 2
                        dist = abs(a_mid - anchor_mid)
                        min_dist = min(min_dist, dist)

                    audio_result['temporal_distance'] = min_dist

                audio_results.sort(key=lambda x: x.get('temporal_distance', float('inf')))

                n_text = sum(1 for sr in (search_results or []) if sr.get('metadata', {}).get('start') is not None)
                n_img = len(temporal_anchors) - n_text
                print(f"Audio re-ranking: {n_text} text + {n_img} image = {len(temporal_anchors)} anchors, "
                      f"closest={audio_results[0]['temporal_distance']:.1f}s, "
                      f"furthest={audio_results[-1]['temporal_distance']:.1f}s")

            audio_results = audio_results[:5]
            print(f"Found {len(audio_results)} relevant audio events")
            audio_parts = []

            for i, audio_result in enumerate(audio_results):
                metadata = audio_result['metadata']
                description = audio_result['description']

                audio_parts.append(
                    f"Audio Event {i+1} - Timestamp: {metadata['start']:.2f}s - {metadata['end']:.2f}s, "
                    f"Events: {description}"
                )

                events_list = description.split(", ")

                for event_str in events_list[:3]:
                    if "(" in event_str and ")" in event_str:
                        event_type = event_str.split("(")[0].strip()
                        confidence_str = event_str.split("(")[1].split("%")[0].strip()

                        try:
                            confidence = float(confidence_str) / 100.0
                        except ValueError:
                            confidence = 0.5

                        if confidence < 0.3:
                            continue

                        audio_sources.append({
                            "start_time": f"{int(float(metadata['start']) // 3600):02d}:{int((float(metadata['start']) % 3600) // 60):02d}:{int(float(metadata['start']) % 60):02d}",
                            "end_time": f"{int(float(metadata['end']) // 3600):02d}:{int((float(metadata['end']) % 3600) // 60):02d}:{int(float(metadata['end']) % 60):02d}",
                            "start": float(metadata['start']),
                            "end": float(metadata['end']),
                            "speaker": metadata.get('speaker', 'Unknown'),
                            "event_type": event_type,
                            "confidence": confidence,
                            "type": "audio"
                        })

            audio_context = "\n".join(audio_parts)

    except Exception as e:
        print(f"Warning: Failed to search audio events: {str(e)}")
        import traceback
        traceback.print_exc()

    return audio_context, audio_sources, True
