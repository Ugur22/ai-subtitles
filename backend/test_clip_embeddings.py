"""
Test script for CLIP image embeddings in VectorStore

This demonstrates how to use the new image embedding features:
1. Index video images using CLIP embeddings
2. Search images using text queries
"""

from vector_store import VectorStore
import os


def test_image_embeddings():
    """Test the CLIP image embedding functionality"""

    # Initialize vector store
    print("=" * 60)
    print("Initializing Vector Store")
    print("=" * 60)
    vs = VectorStore()

    # Example video hash
    video_hash = "test_video_123"

    # Example segments with screenshot paths
    # In production, these would come from actual video processing
    segments = [
        {
            "id": "seg_001",
            "start": 0.0,
            "end": 5.0,
            "speaker": "SPEAKER_00",
            "text": "Hello world",
            "screenshot_url": "/path/to/screenshot_001.jpg"
        },
        {
            "id": "seg_002",
            "start": 5.0,
            "end": 10.0,
            "speaker": "SPEAKER_01",
            "text": "This is a test",
            "screenshot_url": "/path/to/screenshot_002.jpg"
        }
    ]

    # Test 1: Index video images
    print("\n" + "=" * 60)
    print("Test 1: Indexing Video Images")
    print("=" * 60)
    print(f"Segments to index: {len(segments)}")

    try:
        count = vs.index_video_images(video_hash, segments)
        print(f"Result: Successfully indexed {count} images")
    except Exception as e:
        print(f"Note: Indexing skipped (screenshots don't exist): {str(e)}")

    # Test 2: Check if image collection exists
    print("\n" + "=" * 60)
    print("Test 2: Check Image Collection")
    print("=" * 60)
    exists = vs.image_collection_exists(video_hash)
    print(f"Image collection exists: {exists}")

    # Test 3: Search images with text query
    print("\n" + "=" * 60)
    print("Test 3: Search Images with Text Query")
    print("=" * 60)
    query = "person speaking"
    print(f"Query: '{query}'")

    try:
        results = vs.search_images(video_hash, query, n_results=3)
        print(f"Found {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"\n  Result {i}:")
            print(f"    Screenshot: {result['screenshot_path']}")
            print(f"    Metadata: {result['metadata']}")
            print(f"    Distance: {result.get('distance', 'N/A')}")
    except Exception as e:
        print(f"Search completed (no images indexed): {str(e)}")

    # Test 4: Embed specific images
    print("\n" + "=" * 60)
    print("Test 4: Direct Image Embedding")
    print("=" * 60)
    test_images = [
        "/path/to/test1.jpg",
        "/path/to/test2.jpg"
    ]
    print(f"Test image paths: {test_images}")

    try:
        embeddings = vs.embed_images(test_images)
        if embeddings:
            print(f"Generated {len(embeddings)} embeddings")
            print(f"Embedding dimension: {len(embeddings[0])}")
        else:
            print("No embeddings generated (images don't exist)")
    except Exception as e:
        print(f"Note: {str(e)}")

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)


def example_usage_with_real_data():
    """
    Example showing how to use this in production with real video data
    """
    print("\n\n" + "=" * 60)
    print("PRODUCTION USAGE EXAMPLE")
    print("=" * 60)

    code_example = '''
# After video processing and screenshot generation:

from vector_store import vector_store  # Global instance

# 1. Index the transcription (text embeddings)
vector_store.index_transcription(
    video_hash="abc123",
    segments=processed_segments
)

# 2. Index the screenshots (image embeddings)
images_indexed = vector_store.index_video_images(
    video_hash="abc123",
    segments=processed_segments  # Same segments with screenshot_url fields
)

# 3. Search transcriptions with text
text_results = vector_store.search(
    video_hash="abc123",
    query="What did they say about AI?",
    n_results=5
)

# 4. Search images with text (find visual moments)
image_results = vector_store.search_images(
    video_hash="abc123",
    query="person pointing at screen",
    n_results=5
)

# 5. Use results
for result in image_results:
    screenshot_path = result["screenshot_path"]
    timestamp = result["metadata"]["start"]
    speaker = result["metadata"]["speaker"]

    print(f"Found at {timestamp}s by {speaker}")
    print(f"Screenshot: {screenshot_path}")
'''

    print(code_example)


if __name__ == "__main__":
    test_image_embeddings()
    example_usage_with_real_data()
