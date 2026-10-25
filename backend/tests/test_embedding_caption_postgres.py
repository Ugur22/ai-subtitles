import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND = Path(__file__).resolve().parents[1]
BGE = "BAAI/bge-small-en-v1.5"
MINILM = "all-MiniLM-L6-v2"


def _vector(size=384, axis=0):
    return [float(i == axis) for i in range(size)]


@pytest.fixture
def database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.types.json import Jsonb

    connection = psycopg.connect(url, autocommit=True)
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    connection.autocommit = False
    schema = f"embedding_caption_{uuid.uuid4().hex}"
    roles = {name: f"{name}_{uuid.uuid4().hex}" for name in ("anon", "authenticated", "service_role")}
    try:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET LOCAL search_path = {}, public").format(sql.Identifier(schema)))
        for role in roles.values():
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
        connection.execute("""
            CREATE FUNCTION current_uid() RETURNS uuid LANGUAGE sql AS $$
              SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
            $$;
            CREATE TABLE user_profiles (id uuid PRIMARY KEY);
            CREATE TABLE jobs (id uuid PRIMARY KEY, user_id uuid REFERENCES user_profiles(id), video_hash text);
        """)
        owners = (uuid.uuid4(), uuid.uuid4())
        for owner in owners:
            connection.execute("INSERT INTO user_profiles VALUES (%s)", (owner,))

        def migration(relative):
            source = (BACKEND / relative).read_text()
            source = source.replace("auth.uid()", f"{schema}.current_uid()")
            source = re.sub(r"\bpublic\b", schema, source)
            source = source.replace(f"SET search_path = {schema}", f"SET search_path = {schema}, public")
            source = re.sub(r"(?m)^BEGIN;\s*$|^COMMIT;\s*$", "", source)
            for original, role in roles.items():
                source = re.sub(rf"\b{original}\b", role, source)
            connection.execute(source)

        yield SimpleNamespace(connection=connection, migrate=migration, owners=owners,
                              schema=schema, roles=roles, json=Jsonb, sql=sql)
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def indexes(database):
    db = database
    db.migrate("sql/migrations/010_owner_scoped_transcript_audio_embeddings.sql")
    db.migrate("sql/migrations/013_transcript_embeddings_index_config.sql")
    db.migrate("sql/migrations/013_transcript_embeddings_index_config.sql")
    return db


def _transcript_rows(count, label="line"):
    return [dict(chunk_index=i, start_time=i, end_time=i + 1, start_timestamp="00:00:00",
                 end_timestamp="00:00:01", speaker="Person", segment_count=3,
                 chunk_text=f"{label}-{i}", embedding=_vector()) for i in range(count)]


def _replace(db, owner, count, model=BGE, config="chunk_size_3", label="line"):
    return db.connection.execute(
        "SELECT replace_transcript_embedding_index(%s, 'same-hash', %s, %s, %s)",
        (owner, model, db.json(_transcript_rows(count, label)), config),
    ).fetchone()[0]


def _search(db, owner, model=BGE, config="chunk_size_3"):
    return db.connection.execute(
        "SELECT chunk_text FROM search_transcript_chunks_by_embedding_v2(%s, %s::vector, %s, 'same-hash', 20, %s)",
        (owner, str(_vector()), model, config),
    ).fetchall()


def test_embedding_migration_preserves_legacy_upserts_and_search(indexes):
    db = indexes
    owner = db.owners[0]
    db.connection.execute("""
        INSERT INTO transcript_embeddings
          (user_id, video_hash, chunk_index, start_time, end_time, start_timestamp,
           end_timestamp, segment_count, chunk_text, embedding)
        VALUES (%s, 'same-hash', 0, 0, 1, '00:00:00', '00:00:01', 3, 'legacy', %s::vector)
        ON CONFLICT(user_id, video_hash, chunk_index) DO UPDATE SET chunk_text = EXCLUDED.chunk_text
    """, (owner, str(_vector())))
    assert db.connection.execute(
        "SELECT chunk_text FROM search_transcript_chunks_by_embedding(%s, %s::vector, 'same-hash', 5)",
        (owner, str(_vector())),
    ).fetchall() == [("legacy",)]


def test_atomic_replacement_is_owner_model_config_scoped_and_rolls_back(indexes):
    db = indexes
    alice, bob = db.owners
    assert _replace(db, alice, 3) == 3
    _replace(db, alice, 2, model=MINILM, label="minilm")
    _replace(db, alice, 1, config="chunk_size_5", label="config5")
    _replace(db, bob, 2, label="bob")
    assert set(_search(db, alice)) == {("line-0",), ("line-1",), ("line-2",)}
    assert _search(db, alice, config="chunk_size_5") == [("config5-0",)]
    assert len(_search(db, alice, model=MINILM)) == 2
    invalid = _transcript_rows(1)
    invalid[0]["embedding"] = [1.0, 0.0]
    with pytest.raises(Exception, match="dimensions"):
        with db.connection.transaction():
            db.connection.execute(
                "SELECT replace_transcript_embedding_index(%s, 'same-hash', %s, %s, 'chunk_size_3')",
                (alice, BGE, db.json(invalid)),
            )
    assert len(_search(db, alice)) == 3
    _replace(db, alice, 1)
    assert _search(db, alice) == [("line-0",)]
    assert len(_search(db, bob)) == 2
    assert len(_search(db, alice, model=MINILM)) == 2


def test_audio_replacement_and_last_job_cleanup_preserve_other_owners(indexes):
    db = indexes
    alice, bob = db.owners
    job_ids = [uuid.uuid4() for _ in range(3)]
    for job_id, owner in zip(job_ids, (alice, alice, bob)):
        db.connection.execute("INSERT INTO jobs VALUES (%s, %s, 'same-hash')", (job_id, owner))
    rows = [dict(segment_id=str(i), start_time=i, end_time=i + 1, speaker="Person",
                 description=f"laughter-{i}", embedding=_vector()) for i in range(3)]
    for owner in (alice, bob):
        _replace(db, owner, 2)
        db.connection.execute("SELECT replace_audio_embedding_index(%s, 'same-hash', %s, %s)",
                              (owner, BGE, db.json(rows)))
    db.connection.execute("SELECT replace_audio_embedding_index(%s, 'same-hash', %s, %s)",
                          (alice, BGE, db.json(rows[:1])))
    assert db.connection.execute("SELECT count(*) FROM audio_event_embeddings_v2 WHERE user_id=%s", (alice,)).fetchone()[0] == 1
    db.connection.execute("DELETE FROM jobs WHERE id=%s", (job_ids[0],))
    assert len(_search(db, alice)) == 2
    db.connection.execute("DELETE FROM jobs WHERE id=%s", (job_ids[1],))
    assert _search(db, alice) == []
    assert db.connection.execute("SELECT count(*) FROM audio_event_embeddings_v2 WHERE user_id=%s", (alice,)).fetchone()[0] == 0
    assert len(_search(db, bob)) == 2
    assert db.connection.execute("SELECT count(*) FROM audio_event_embeddings_v2 WHERE user_id=%s", (bob,)).fetchone()[0] == 3


@pytest.fixture
def captions(database):
    db = database
    db.connection.execute("""
        CREATE TABLE image_embeddings (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid REFERENCES user_profiles(id),
          video_hash text NOT NULL, segment_id text NOT NULL, start_time double precision NOT NULL,
          end_time double precision NOT NULL, speaker text, screenshot_url text NOT NULL,
          embedding vector(512) NOT NULL
        )
    """)
    db.migrate("sql/migrations/017_owner_scoped_vision_captions.sql")
    db.migrate("sql/migrations/017_owner_scoped_vision_captions.sql")
    return db


def _image(db, owner, name):
    return db.connection.execute("""
        INSERT INTO image_embeddings(user_id, video_hash, segment_id, start_time, end_time,
                                     screenshot_url, embedding)
        VALUES (%s, 'same-hash', %s, 1, 2, %s, %s::vector) RETURNING id
    """, (owner, name, f"{owner}/{name}.jpg", str(_vector(512)))).fetchone()[0]


def _store_caption(db, owner, image_id, text="swimming", model=BGE, sentences=None):
    if sentences is None:
        sentences = [dict(sentence=text, embedding=_vector())]
    return db.connection.execute(
        "SELECT store_image_caption(%s, 'same-hash', %s, %s, %s::vector, %s, %s)",
        (owner, image_id, text, str(_vector()), model, db.json(sentences)),
    ).fetchone()[0]


def test_caption_store_search_and_resume_are_owner_model_scoped(captions):
    db = captions
    alice, bob = db.owners
    alice_id, bob_id, old_id = _image(db, alice, "alice"), _image(db, bob, "bob"), _image(db, alice, "old")
    assert _store_caption(db, alice, alice_id)
    assert _store_caption(db, bob, bob_id)
    assert _store_caption(db, alice, old_id, model=MINILM)
    assert not _store_caption(db, alice, bob_id, text="stolen")
    assert db.connection.execute(
        "SELECT id FROM search_images_by_caption_sentences(%s, %s::vector, 'same-hash', %s, 6)",
        (alice, str(_vector()), BGE),
    ).fetchall() == [(alice_id,)]
    assert db.connection.execute(
        "SELECT id FROM caption_frames_to_process(%s, 'same-hash', %s, 1, false)", (alice, BGE),
    ).fetchall() == [(old_id,)]
    assert db.connection.execute(
        "SELECT count(*) FROM caption_frames_to_process(%s, 'same-hash', %s, 1, true)", (alice, BGE),
    ).fetchone()[0] == 1
    with pytest.raises(Exception, match="dimensions"):
        with db.connection.transaction():
            _store_caption(db, alice, alice_id, text="invalid", sentences=[dict(sentence="bad", embedding=[1.0])])
    assert db.connection.execute("SELECT caption FROM image_embeddings WHERE id=%s", (alice_id,)).fetchone()[0] == "swimming"
    assert db.connection.execute("SELECT sentence FROM image_caption_sentences WHERE image_embedding_id=%s", (alice_id,)).fetchall() == [("swimming",)]


def test_caption_rls_and_rpc_permissions_block_client_roles(captions):
    db = captions
    alice, bob = db.owners
    for owner, name in ((alice, "alice"), (bob, "bob")):
        _store_caption(db, owner, _image(db, owner, name))
    for name in ("caption_frames_to_process", "search_images_by_caption_sentences", "store_image_caption", "videos_missing_captions"):
        rows = db.connection.execute("""
            SELECT has_function_privilege(%s, p.oid, 'EXECUTE'), has_function_privilege(%s, p.oid, 'EXECUTE'),
                   has_function_privilege(%s, p.oid, 'EXECUTE')
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=%s AND p.proname=%s
        """, (db.roles["anon"], db.roles["authenticated"], db.roles["service_role"], db.schema, name)).fetchall()
        assert rows == [(False, False, True)]
    db.connection.execute(db.sql.SQL("SET LOCAL ROLE {}").format(db.sql.Identifier(db.roles["authenticated"])))
    db.connection.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (str(alice),))
    assert db.connection.execute("SELECT DISTINCT user_id FROM image_caption_sentences").fetchall() == [(alice,)]
    with pytest.raises(Exception, match="permission denied"):
        with db.connection.transaction():
            db.connection.execute("DELETE FROM image_caption_sentences")


def test_clean_image_schema_bootstrap_supports_caption_and_clip_search(database):
    db = database
    db.migrate("sql/image_embeddings_schema.sql")
    alice = db.owners[0]
    image_id = _image(db, alice, "fresh")
    assert _store_caption(db, alice, image_id)
    assert db.connection.execute(
        "SELECT id FROM search_images_by_embedding(%s, %s::vector, 'same-hash', 5, NULL)",
        (alice, str(_vector(512))),
    ).fetchall() == [(image_id,)]
    assert db.connection.execute(
        "SELECT id FROM search_images_by_caption_sentences(%s, %s::vector, 'same-hash', %s, 6)",
        (alice, str(_vector()), BGE),
    ).fetchall() == [(image_id,)]
