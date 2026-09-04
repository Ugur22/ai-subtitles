from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8")


def test_transcript_and_audio_tables_are_owner_scoped_from_creation():
    sql = _read("sql/migrations/010_owner_scoped_transcript_audio_embeddings.sql")

    for table in ("transcript_embeddings", "audio_event_embeddings"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert "user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE" in sql
        assert f"'{table}'" in sql

    assert "v_table_name || '_select_own'" in sql
    assert "v_table_name || '_service_role_all'" in sql
    assert "idx_transcript_embeddings_owner_video_chunk" in sql
    assert "ON transcript_embeddings (user_id, video_hash, chunk_index)" in sql
    assert "idx_audio_event_embeddings_owner_video_segment" in sql
    assert "ON audio_event_embeddings (user_id, video_hash, segment_id)" in sql


def test_transcript_and_audio_search_require_the_owner():
    sql = _read("sql/migrations/010_owner_scoped_transcript_audio_embeddings.sql")

    transcript_search = sql[sql.index("CREATE OR REPLACE FUNCTION search_transcript_chunks_by_embedding"):]
    transcript_search = transcript_search[:transcript_search.index("CREATE OR REPLACE FUNCTION search_audio_events")]
    assert "p_user_id UUID" in transcript_search
    assert "te.user_id = p_user_id" in transcript_search
    assert "te.video_hash = target_video_hash" in transcript_search

    audio_search = sql[sql.index("CREATE OR REPLACE FUNCTION search_audio_events_by_embedding"):]
    assert "p_user_id UUID" in audio_search
    assert "ae.user_id = p_user_id" in audio_search
    assert "ae.video_hash = target_video_hash" in audio_search

    service = _read("services/transcript_embedding_service.py")
    assert "on_conflict='user_id,video_hash,chunk_index'" in service or "'user_id,video_hash,chunk_index'" in service
    assert "on_conflict='user_id,video_hash,segment_id'" in service or "'user_id,video_hash,segment_id'" in service
    assert "'p_user_id': user_id" in service
    assert ".eq('user_id', user_id).eq('video_hash', video_hash)" in service


def test_transcript_and_audio_score_is_similarity_and_sorted_higher_first():
    sql = _read("sql/migrations/010_owner_scoped_transcript_audio_embeddings.sql")
    service = _read("services/transcript_embedding_service.py")

    assert "1 - (te.embedding <=> query_embedding) AS similarity" in sql
    assert "ORDER BY te.embedding <=> query_embedding" in sql
    assert "1 - (ae.embedding <=> query_embedding) AS similarity" in sql
    assert "ORDER BY ae.embedding <=> query_embedding" in sql

    # The service renames the RPC's similarity to the return dict's key of
    # the same name (not the old Chroma "distance" key).
    assert "'similarity': item['similarity']" in service
    assert "'distance':" not in service


def test_transcript_and_audio_search_use_the_bge_query_prefix_not_indexing():
    service = _read("services/transcript_embedding_service.py")

    index_transcript = service[service.index("def index_transcript_chunks("):service.index("def search_transcript_chunks(")]
    search_transcript = service[service.index("def search_transcript_chunks("):service.index("def audio_events_exist(")]
    index_audio = service[service.index("def index_audio_events("):service.index("def search_audio_events(")]
    search_audio = service[service.index("def search_audio_events("):service.index("def update_speaker_name(")]

    assert "_BGE_QUERY_PREFIX" not in index_transcript
    assert "_BGE_QUERY_PREFIX" in search_transcript
    assert "_BGE_QUERY_PREFIX" not in index_audio
    assert "_BGE_QUERY_PREFIX" in search_audio


def test_transcript_audio_migration_drops_old_overloads_and_locks_grants():
    sql = _read("sql/migrations/010_owner_scoped_transcript_audio_embeddings.sql")

    catalog_cleanup = sql[sql.index("Catalog-introspection-safe drop"):]
    catalog_cleanup = catalog_cleanup[:catalog_cleanup.index("CREATE OR REPLACE FUNCTION search_transcript_chunks")]
    assert "pg_get_function_identity_arguments" in catalog_cleanup
    assert "'search_transcript_chunks_by_embedding'" in catalog_cleanup
    assert "'search_audio_events_by_embedding'" in catalog_cleanup
    assert "REVOKE ALL ON FUNCTION %I.%I(%s) FROM PUBLIC, authenticated" in catalog_cleanup
    assert "DROP FUNCTION %I.%I(%s)" in catalog_cleanup

    signatures = {
        "search_transcript_chunks_by_embedding": "UUID, vector, TEXT, INTEGER",
        "search_audio_events_by_embedding": "UUID, vector, TEXT, INTEGER",
    }
    for function_name, signature in signatures.items():
        function = sql[sql.index(f"CREATE OR REPLACE FUNCTION {function_name}"):]
        function = function[:function.index("$$;", function.index("AS $$")) + 3]
        assert "p_user_id UUID" in function
        assert f"REVOKE ALL ON FUNCTION {function_name}({signature}) FROM PUBLIC, authenticated" in sql
        assert f"GRANT EXECUTE ON FUNCTION {function_name}({signature}) TO service_role" in sql
