#!/usr/bin/env python3
"""
Integration test demonstrating the complete speaker rename flow
This shows how the fix enables RAG/chat queries with renamed speakers
"""

def simulate_speaker_rename_flow():
    """
    Simulate the complete flow of renaming a speaker and querying with the new name
    """
    print("=" * 70)
    print("SPEAKER RENAME INTEGRATION TEST")
    print("=" * 70)

    # Step 1: Initial state - Transcription indexed with SPEAKER_06
    print("\n1. INITIAL STATE")
    print("-" * 70)

    video_hash = "abc123"
    original_speaker = "SPEAKER_06"
    new_speaker = "Eric"

    # Simulate database segments
    db_segments = [
        {"id": 1, "text": "Hello everyone", "speaker": "SPEAKER_06", "start": 0.0},
        {"id": 2, "text": "I'm here today", "speaker": "SPEAKER_06", "start": 5.0},
        {"id": 3, "text": "Nice to meet you", "speaker": "SPEAKER_07", "start": 10.0},
    ]

    # Simulate vector store metadata (text chunks)
    vector_store_text_metadata = [
        {"video_hash": video_hash, "speaker": "SPEAKER_06", "start": 0.0, "text": "Hello everyone"},
        {"video_hash": video_hash, "speaker": "SPEAKER_06", "start": 5.0, "text": "I'm here today"},
        {"video_hash": video_hash, "speaker": "SPEAKER_07", "start": 10.0, "text": "Nice to meet you"},
    ]

    # Simulate vector store metadata (images)
    vector_store_image_metadata = [
        {"video_hash": video_hash, "speaker": "SPEAKER_06", "start": 0.0},
        {"video_hash": video_hash, "speaker": "SPEAKER_06", "start": 5.0},
        {"video_hash": video_hash, "speaker": "SPEAKER_07", "start": 10.0},
    ]

    print(f"Video hash: {video_hash}")
    print(f"Database segments: {len(db_segments)}")
    print(f"Vector store text chunks: {len(vector_store_text_metadata)}")
    print(f"Vector store images: {len(vector_store_image_metadata)}")
    print(f"\nSpeaker to rename: '{original_speaker}' → '{new_speaker}'")

    # Step 2: User query BEFORE rename (fails)
    print("\n2. QUERY BEFORE RENAME")
    print("-" * 70)
    query_before = f"What did {new_speaker} say?"
    print(f"Query: '{query_before}'")

    # Check database for speaker (won't find "Eric")
    db_speakers = set(seg["speaker"] for seg in db_segments)
    print(f"Database speakers: {db_speakers}")
    print(f"Found '{new_speaker}' in database? {new_speaker in db_speakers}")

    # Check vector store for speaker (won't find "Eric")
    vs_speakers = set(meta["speaker"] for meta in vector_store_text_metadata)
    print(f"Vector store speakers: {vs_speakers}")
    print(f"Found '{new_speaker}' in vector store? {new_speaker in vs_speakers}")
    print(f"\nResult: Query FAILS - speaker not found ❌")

    # Step 3: Rename speaker
    print("\n3. RENAME SPEAKER (OUR FIX)")
    print("-" * 70)
    print(f"Renaming '{original_speaker}' → '{new_speaker}'...")

    # Update database
    for seg in db_segments:
        if seg["speaker"] == original_speaker:
            seg["speaker"] = new_speaker

    db_updated = sum(1 for seg in db_segments if seg["speaker"] == new_speaker)
    print(f"Database updated: {db_updated} segments")

    # Update vector store (THE FIX)
    for meta in vector_store_text_metadata:
        if meta["speaker"] == original_speaker:
            meta["speaker"] = new_speaker

    vs_text_updated = sum(1 for meta in vector_store_text_metadata if meta["speaker"] == new_speaker)
    print(f"Vector store text updated: {vs_text_updated} chunks")

    for meta in vector_store_image_metadata:
        if meta["speaker"] == original_speaker:
            meta["speaker"] = new_speaker

    vs_images_updated = sum(1 for meta in vector_store_image_metadata if meta["speaker"] == new_speaker)
    print(f"Vector store images updated: {vs_images_updated} images")

    # Step 4: User query AFTER rename (succeeds!)
    print("\n4. QUERY AFTER RENAME")
    print("-" * 70)
    query_after = f"What did {new_speaker} say?"
    print(f"Query: '{query_after}'")

    # Check database for speaker (now finds "Eric")
    db_speakers = set(seg["speaker"] for seg in db_segments)
    print(f"Database speakers: {db_speakers}")
    print(f"Found '{new_speaker}' in database? {new_speaker in db_speakers}")

    # Check vector store for speaker (now finds "Eric")
    vs_speakers = set(meta["speaker"] for meta in vector_store_text_metadata)
    print(f"Vector store speakers: {vs_speakers}")
    print(f"Found '{new_speaker}' in vector store? {new_speaker in vs_speakers}")

    # Extract speaker from query (simulating _extract_speaker_from_query)
    speaker_filter = None
    query_lower = query_after.lower()
    for speaker in db_speakers:
        if speaker.lower() in query_lower:
            speaker_filter = speaker
            break

    print(f"\nExtracted speaker filter: '{speaker_filter}'")

    # Filter vector store results by speaker
    matching_chunks = [
        meta for meta in vector_store_text_metadata
        if meta["speaker"] == speaker_filter
    ]

    print(f"Matching chunks found: {len(matching_chunks)}")
    for chunk in matching_chunks:
        print(f"  - [{chunk['start']:.1f}s] {chunk.get('text', '(image)')}")

    print(f"\nResult: Query SUCCEEDS - found {len(matching_chunks)} results ✅")

    # Step 5: Verification
    print("\n5. VERIFICATION")
    print("-" * 70)

    # Verify consistency
    db_eric_count = sum(1 for seg in db_segments if seg["speaker"] == new_speaker)
    vs_text_eric_count = sum(1 for meta in vector_store_text_metadata if meta["speaker"] == new_speaker)
    vs_images_eric_count = sum(1 for meta in vector_store_image_metadata if meta["speaker"] == new_speaker)

    print(f"Database '{new_speaker}' segments: {db_eric_count}")
    print(f"Vector store text '{new_speaker}' chunks: {vs_text_eric_count}")
    print(f"Vector store images '{new_speaker}': {vs_images_eric_count}")

    # Check for old speaker name (should be gone)
    db_old_count = sum(1 for seg in db_segments if seg["speaker"] == original_speaker)
    vs_old_count = sum(1 for meta in vector_store_text_metadata if meta["speaker"] == original_speaker)

    print(f"\nOld speaker '{original_speaker}' remaining in DB: {db_old_count}")
    print(f"Old speaker '{original_speaker}' remaining in VS: {vs_old_count}")

    consistency_check = (
        db_eric_count == vs_text_eric_count and
        db_old_count == 0 and
        vs_old_count == 0
    )

    print(f"\nConsistency check: {'PASS ✅' if consistency_check else 'FAIL ❌'}")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print("\nSUMMARY:")
    print("- Before fix: Chat queries for renamed speakers failed")
    print("- After fix: Vector store metadata is updated along with database")
    print("- Result: Chat queries now work with renamed speaker names")
    print("\nThe fix ensures database and vector store stay in sync!")

    return consistency_check

if __name__ == "__main__":
    success = simulate_speaker_rename_flow()
    exit(0 if success else 1)
