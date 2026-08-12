import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8")


def _methods(relative: str, class_name: str) -> set[str]:
    tree = ast.parse(_read(relative))
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_visual_rows_are_safely_backfilled_and_owner_scoped():
    sql = _read("sql/migrations/009_owner_scoped_visual_embeddings.sql")

    assert "COUNT(DISTINCT user_id) = 1" in sql
    assert "COUNT(*) FILTER (WHERE user_id IS NULL) = 0" in sql
    for table in ("image_embeddings", "image_face_presence", "face_tags"):
        assert f"DELETE FROM {table} WHERE user_id IS NULL" in sql
        assert f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL" in sql
        assert f"'{table}'" in sql
    assert "v_table_name || '_select_own'" in sql
    assert "v_table_name || '_service_role_all'" in sql
    assert "idx_image_embeddings_owner_video_segment" in sql
    assert "ON image_embeddings (user_id, video_hash, segment_id)" in sql
    assert "idx_face_tags_owner_screenshot_bbox" in sql
    assert "FOREIGN KEY (user_id, image_embedding_id)" in sql


def test_same_hash_search_and_face_matching_require_the_owner():
    sql = _read("sql/migrations/009_owner_scoped_visual_embeddings.sql")

    image_search = sql[sql.index("CREATE OR REPLACE FUNCTION search_images_by_embedding"):]
    image_search = image_search[:image_search.index("CREATE OR REPLACE FUNCTION match_faces")]
    assert "p_user_id UUID" in image_search
    assert "ie.user_id = p_user_id" in image_search
    assert "ie.video_hash = target_video_hash" in image_search

    face_search = sql[sql.index("CREATE OR REPLACE FUNCTION match_faces_by_embedding"):]
    face_search = face_search[:face_search.index("CREATE OR REPLACE FUNCTION videos_missing")]
    assert "p_user_id UUID" in face_search
    assert "ifp.user_id = p_user_id" in face_search
    assert "ifp.video_hash = target_video_hash" in face_search

    service = _read("services/image_embedding_service.py")
    assert "on_conflict='user_id,video_hash,segment_id'" in service
    assert "'p_user_id': user_id" in service
    assert ".eq('user_id', user_id).eq('video_hash', video_hash)" in service


def test_visual_score_is_similarity_and_sorted_higher_first():
    sql = _read("sql/migrations/009_owner_scoped_visual_embeddings.sql")
    models = _read("models/chat.py")
    api = (BACKEND.parent / "frontend/src/services/api.ts").read_text(encoding="utf-8")

    assert "1 - (ie.embedding <=> query_embedding) AS similarity" in sql
    assert "ORDER BY ie.embedding <=> query_embedding" in sql
    image_model = models[models.index("class ImageSearchResult"):]
    image_model = image_model[:image_model.index("class SearchImagesResponse")]
    assert "similarity: float" in image_model
    assert "distance" not in image_model
    image_api = api[api.index("export interface ImageSearchResult"):]
    image_api = image_api[:image_api.index("export interface ImageSearchResponse")]
    assert "similarity: number" in image_api
    assert "distance" not in image_api


def test_chroma_has_no_visual_embedding_surface():
    methods = _methods("vector_store.py", "VectorStore")
    forbidden = {
        "get_or_create_image_collection",
        "embed_images",
        "index_video_images",
        "search_images",
        "delete_image_collection",
        "image_collection_exists",
        "clip_model",
    }
    assert methods.isdisjoint(forbidden)

    vector_source = _read("vector_store.py")
    chat_source = _read("routers/chat.py")
    assert "_images" not in vector_source
    assert "_use_supabase_for_images" not in chat_source
    assert "vector_store.search_images" not in chat_source
    assert "vector_store.index_video_images" not in chat_source


def test_clip_preloader_warms_the_shared_service_singleton():
    preloader = _read("model_preloader.py")
    assert "from services.image_embedding_service import image_embedding_service" in preloader
    assert "image_embedding_service.clip_model" in preloader
    assert "ImageEmbeddingService()" not in preloader


def test_legacy_visual_rpcs_are_dropped_and_replacements_are_service_only():
    sql = _read("sql/migrations/009_owner_scoped_visual_embeddings.sql")
    face_schema = _read("sql/face_tags_schema.sql")
    callers = "\n".join(
        _read(relative)
        for relative in (
            "routers/chat.py",
            "routers/jobs.py",
            "services/image_embedding_service.py",
        )
    )

    catalog_cleanup = sql[sql.index("Remove every historical visual-RPC overload"):]
    catalog_cleanup = catalog_cleanup[:catalog_cleanup.index("CREATE OR REPLACE FUNCTION search_images")]
    assert "pg_get_function_identity_arguments" in catalog_cleanup
    assert "'search_faces_by_embedding'" in catalog_cleanup
    assert "REVOKE ALL ON FUNCTION %I.%I(%s) FROM PUBLIC, authenticated" in catalog_cleanup
    assert "DROP FUNCTION %I.%I(%s)" in catalog_cleanup
    assert "search_faces_by_embedding" not in face_schema
    assert "search_faces_by_embedding" not in callers

    signatures = {
        "search_images_by_embedding": "UUID, vector, TEXT, INTEGER, TEXT",
        "match_faces_by_embedding": "UUID, TEXT, vector, DOUBLE PRECISION, INTEGER",
    }
    for function_name, signature in signatures.items():
        function = sql[sql.index(f"CREATE OR REPLACE FUNCTION {function_name}"):]
        function = function[:function.index("$$;", function.index("AS $$")) + 3]
        assert "p_user_id UUID" in function
        assert f"REVOKE ALL ON FUNCTION {function_name}({signature}) FROM PUBLIC, authenticated" in sql
        assert f"GRANT EXECUTE ON FUNCTION {function_name}({signature}) TO service_role" in sql
