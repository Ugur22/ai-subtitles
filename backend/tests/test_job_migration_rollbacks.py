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
