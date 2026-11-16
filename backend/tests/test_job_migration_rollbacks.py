import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "migrations"


def _read(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION {name}(")
    return sql[start:sql.index("$$;\n", start) + 4]


def _created_functions(sql: str) -> set:
    return set(re.findall(r"CREATE OR REPLACE FUNCTION (\w+)\(", sql))


def test_018_rollback_restores_the_replaced_functions_verbatim():
    rollback = _read("018_job_continuations_rollback.sql")

    assert _function(rollback, "claim_job") == _function(
        _read("005_job_upload_quota_security.sql"), "claim_job"
    )
    assert _function(rollback, "retry_job_secure") == _function(
        _read("008_atomic_finalization_recovery.sql"), "retry_job_secure"
    )
    assert "continuation_count" not in _function(rollback, "claim_job")
    assert "continuation_count" not in _function(rollback, "retry_job_secure")


def test_rollbacks_remove_everything_the_migrations_add():
    forward_018, rollback_018 = _read("018_job_continuations.sql"), _read("018_job_continuations_rollback.sql")
    forward_019, rollback_019 = _read("019_worker_timeout_retry.sql"), _read("019_worker_timeout_retry_rollback.sql")

    for forward, rollback in ((forward_018, rollback_018), (forward_019, rollback_019)):
        for column in re.findall(r"ADD COLUMN IF NOT EXISTS (\w+)", forward):
            assert f"DROP COLUMN IF EXISTS {column}" in rollback
        for index in re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", forward):
            assert f"DROP INDEX IF EXISTS {index}" in rollback
        # Every function is either restored to its earlier definition or dropped.
        for name in _created_functions(forward) - _created_functions(rollback):
            assert f"DROP FUNCTION IF EXISTS {name}(" in rollback
        assert rollback.count("BEGIN;") == 1 and rollback.rstrip().endswith("COMMIT;")

    assert _created_functions(rollback_018) == {"claim_job", "retry_job_secure"}
    assert _created_functions(rollback_019) == set()


DERIVED_TABLES = (
    "pipeline_cache", "transcript_embeddings", "transcript_embeddings_v2",
    "audio_event_embeddings", "audio_event_embeddings_v2", "image_embeddings", "face_tags",
)


def _delete_function(sql: str) -> str:
    start = sql.index("CREATE FUNCTION delete_job_permanent_secure(")
    return sql[start:sql.index("$$;\n", start) + 4]


def test_020_rollback_restores_the_live_delete_function():
    rollback = _delete_function(_read("020_delete_job_derived_data_rollback.sql"))
    # Live differs from 006 only in naming the unique constraint.
    live = _function(_read("006_media_deletion_outbox.sql"), "delete_job_permanent_secure").replace(
        "CREATE OR REPLACE FUNCTION", "CREATE FUNCTION"
    ).replace("ON CONFLICT (media_key)", "ON CONFLICT ON CONSTRAINT media_delete_outbox_media_key_key")

    assert rollback == live
    assert "screenshots_outbox_id" not in rollback


def test_020_deletes_derived_data_only_for_the_owner_and_only_for_the_last_job():
    sql = _read("020_delete_job_derived_data.sql")
    function = _delete_function(sql)

    for table in DERIVED_TABLES:
        assert (
            f"DELETE FROM {table}\n      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;"
            in function
        )
    guard = function.index("AND id <> p_job_id")
    assert all(function.index(f"DELETE FROM {table}\n") > guard for table in DERIVED_TABLES)
    assert "'screenshots/' || p_user_id::text || '/' || v_job.video_hash || '/'" in function
    assert "WHERE media_delete_outbox.status = 'completed'" in function
    assert "REVOKE ALL ON FUNCTION delete_job_permanent_secure(UUID, UUID) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION delete_job_permanent_secure(UUID, UUID) TO service_role;" in sql
    assert sql.count("BEGIN;") == 1 and sql.rstrip().endswith("COMMIT;")


def test_orphan_cleanup_covers_the_same_tables_as_020():
    cleanup = (MIGRATIONS.parent / "cleanup" / "2026-11_orphaned_derived_data.sql").read_text(encoding="utf-8")
    deleted = set(re.findall(r"DELETE FROM (\w+) d WHERE NOT EXISTS", cleanup))

    assert deleted == set(DERIVED_TABLES)


def test_021_rollback_restores_018_claim_and_drops_the_rest():
    forward, rollback = _read("021_gpu_slot_wait.sql"), _read("021_gpu_slot_wait_rollback.sql")

    assert _function(rollback, "claim_job") == _function(
        _read("018_job_continuations.sql"), "claim_job"
    )
    assert _created_functions(rollback) == {"claim_job"}
    for name in _created_functions(forward) - {"claim_job"}:
        assert f"DROP FUNCTION IF EXISTS {name}(" in rollback
    for index in re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", forward):
        assert f"DROP INDEX IF EXISTS {index}" in rollback
    assert "stage = 'waiting_for_gpu'" in rollback
    assert rollback.count("BEGIN;") == 1 and rollback.rstrip().endswith("COMMIT;")
    assert forward.count("BEGIN;") == 1 and forward.rstrip().endswith("COMMIT;")
