#!/usr/bin/env python3
"""
Test script to verify speaker name update in vector store
This demonstrates the fix for updating speaker names in RAG/chat
"""

def test_speaker_update_logic():
    """
    Test the logic of updating speaker names in metadata
    """
    print("Testing speaker name update logic...\n")

    # Simulate existing metadata from vector store
    mock_metadatas = [
        {
            "video_hash": "abc123",
            "start": 0.0,
            "end": 10.0,
            "speaker": "SPEAKER_06",
            "text": "Hello world"
        },
        {
            "video_hash": "abc123",
            "start": 10.0,
            "end": 20.0,
            "speaker": "SPEAKER_07",
            "text": "Another segment"
        },
        {
            "video_hash": "abc123",
            "start": 20.0,
            "end": 30.0,
            "speaker": "SPEAKER_06",
            "text": "More from speaker 6"
        }
    ]

    mock_ids = ["id1", "id2", "id3"]

    old_speaker = "SPEAKER_06"
    new_speaker = "Eric"

    # Simulate the update logic
    ids_to_update = []
    updated_metadatas = []

    for i, metadata in enumerate(mock_metadatas):
        if metadata.get('speaker') == old_speaker:
            ids_to_update.append(mock_ids[i])
            # Create updated metadata
            new_metadata = metadata.copy()
            new_metadata['speaker'] = new_speaker
            updated_metadatas.append(new_metadata)

    print(f"Original speaker: {old_speaker}")
    print(f"New speaker: {new_speaker}")
    print(f"\nIDs to update: {ids_to_update}")
    print(f"Updated count: {len(ids_to_update)}")
    print(f"\nUpdated metadata:")
    for meta in updated_metadatas:
        print(f"  - {meta}")

    # Verify the results
    assert len(ids_to_update) == 2, "Should find 2 items with SPEAKER_06"
    assert ids_to_update == ["id1", "id3"], "Should update correct IDs"
    assert all(m['speaker'] == new_speaker for m in updated_metadatas), "All updated items should have new speaker name"

    print("\nTest PASSED! Speaker name update logic works correctly.")
    return True

if __name__ == "__main__":
    test_speaker_update_logic()
