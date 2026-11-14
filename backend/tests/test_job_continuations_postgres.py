"""PostgreSQL integration tests for the continuation and timeout RPCs.

Skipped unless TEST_DATABASE_URL points at a scratch database (and psycopg is
installed); `make check` always runs without it.
"""
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

BASE_TABLES = """
CREATE TABLE user_profiles (id UUID PRIMARY KEY);
CREATE TABLE jobs (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES user_profiles(id),
  status TEXT NOT NULL DEFAULT 'pending',
  progress INTEGER DEFAULT 0,
  stage TEXT,
  message TEXT,
  retry_count INTEGER DEFAULT 0,
  error_code TEXT,
  error_message TEXT,
  result_json JSONB,
  result_srt TEXT,
  result_vtt TEXT,
  final_media_key TEXT,
  finalization_started_at TIMESTAMPTZ,
  quota_reserved_seconds INTEGER NOT NULL DEFAULT 0,
  quota_reservation_period DATE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  failed_at TIMESTAMPTZ,
  last_seen TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE user_usage_monthly (
  user_id UUID NOT NULL REFERENCES user_profiles(id),
  period_start DATE NOT NULL,
  transcription_seconds INTEGER NOT NULL DEFAULT 0,
  reserved_transcription_seconds INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, period_start)
);
CREATE TABLE media_delete_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  media_key TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending'
);
"""


def _migration(name: str, schema: str) -> str:
    sql = (BACKEND / "sql/migrations" / name).read_text(encoding="utf-8")
    sql = sql.removeprefix("BEGIN;\n")
    if sql.rstrip().endswith("COMMIT;"):
        sql = sql.rstrip()[:-len("COMMIT;")]
    sql = re.sub(r"\bpublic\b", schema, sql)
    sql = sql.replace("FROM PUBLIC, anon, authenticated", "FROM PUBLIC")
    return sql.replace("TO service_role", "TO PUBLIC")


@contextmanager
def scratch_schema(*migrations: str):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    psycopg = pytest.importorskip(
        "psycopg", reason="psycopg is required for PostgreSQL integration tests"
    )
    schema = f"job_continuations_{uuid.uuid4().hex}"
    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
            cursor.execute(f'SET LOCAL search_path TO "{schema}"')
            cursor.execute(BASE_TABLES)
            for name in migrations:
                cursor.execute(_migration(name, schema))
            yield cursor
    finally:
        # Nothing is committed, so the schema disappears with the transaction.
        connection.rollback()
        connection.close()


def _processing_job(cursor, reserved=120):
    user_id, job_id = uuid.uuid4(), uuid.uuid4()
    cursor.execute("INSERT INTO user_profiles (id) VALUES (%s)", (user_id,))
    cursor.execute(
        """
        INSERT INTO user_usage_monthly (user_id, period_start, reserved_transcription_seconds)
        VALUES (%s, date_trunc('month', now())::date, %s)
        """,
        (user_id, reserved),
    )
    cursor.execute(
        """
        INSERT INTO jobs (
          id, user_id, status, progress, stage, started_at,
          quota_reserved_seconds, quota_reservation_period
        ) VALUES (
          %s, %s, 'processing', 42, 'transcribing', now() - interval '50 minutes',
          %s, date_trunc('month', now())::date
        )
        """,
        (job_id, user_id, reserved),
    )
    return user_id, job_id


def _job(cursor, job_id, columns):
    cursor.execute(f"SELECT {columns} FROM jobs WHERE id = %s", (job_id,))
    return cursor.fetchone()


def _reserved(cursor, user_id):
    cursor.execute(
        "SELECT reserved_transcription_seconds, transcription_seconds "
        "FROM user_usage_monthly WHERE user_id = %s",
        (user_id,),
    )
    return cursor.fetchone()


def test_continuation_keeps_the_reservation_and_stops_at_the_cap():
    with scratch_schema("018_job_continuations.sql") as cursor:
        user_id, job_id = _processing_job(cursor)
        started_at = _job(cursor, job_id, "started_at")[0]

        cursor.execute("SELECT requeue_job_for_continuation(%s, 2, 10.5)", (job_id,))
        assert cursor.fetchone()[0] == "continue"
        assert _job(
            cursor, job_id,
            "status, stage, continuation_count, retry_count, quota_reserved_seconds, "
            "gpu_seconds_accumulated, progress",
        ) == ("pending", "continuing", 1, 0, 120, pytest.approx(10.5), 42)
        # Same job: nothing reserved twice, nothing settled yet.
        assert _reserved(cursor, user_id) == (120, 0)

        cursor.execute("SELECT claim_job(%s, 3)", (job_id,))
        assert cursor.fetchone()[0] is True
        assert _job(cursor, job_id, "status, progress, started_at") == (
            "processing", 42, started_at,
        )

        cursor.execute("SELECT requeue_job_for_continuation(%s, 2, 1)", (job_id,))
        assert cursor.fetchone()[0] == "continue"
        cursor.execute("SELECT claim_job(%s, 3)", (job_id,))

        cursor.execute("SELECT requeue_job_for_continuation(%s, 2, 1)", (job_id,))
        assert cursor.fetchone()[0] == "exhausted"
        assert _job(cursor, job_id, "status, error_code, quota_reserved_seconds") == (
            "failed", "max_continuations_reached", 0,
        )
        assert _reserved(cursor, user_id) == (0, 0)

        cursor.execute("SELECT requeue_job_for_continuation(%s, 2, 1)", (job_id,))
        assert cursor.fetchone()[0] == "not_processing"


def test_continuation_does_not_touch_a_cancelled_job():
    with scratch_schema("018_job_continuations.sql") as cursor:
        _user_id, job_id = _processing_job(cursor)
        cursor.execute("UPDATE jobs SET status = 'cancelled' WHERE id = %s", (job_id,))

        cursor.execute("SELECT requeue_job_for_continuation(%s, 12, 1)", (job_id,))

        assert cursor.fetchone()[0] == "not_processing"
        assert _job(cursor, job_id, "status, continuation_count") == ("cancelled", 0)


def test_manual_retry_starts_a_fresh_continuation_chain():
    with scratch_schema("018_job_continuations.sql") as cursor:
        user_id, job_id = _processing_job(cursor)
        cursor.execute("SELECT requeue_job_for_continuation(%s, 0, 1)", (job_id,))
        assert cursor.fetchone()[0] == "exhausted"
        cursor.execute("UPDATE jobs SET continuation_count = 12 WHERE id = %s", (job_id,))

        cursor.execute("SELECT id FROM retry_job_secure(%s, %s, 3, 1)", (job_id, user_id))

        assert cursor.fetchone()[0] == job_id
        assert _job(cursor, job_id, "status, continuation_count, retry_count") == (
            "pending", 0, 1,
        )


MIGRATIONS = ("018_job_continuations.sql", "019_worker_timeout_retry.sql")


def test_timeout_only_fails_a_processing_job_and_releases_its_reservation():
    with scratch_schema(*MIGRATIONS) as cursor:
        user_id, job_id = _processing_job(cursor)

        cursor.execute("SELECT timeout_job_secure(%s, 'out of time')", (job_id,))
        assert cursor.fetchone()[0] is True
        assert _job(cursor, job_id, "status, error_code, quota_reserved_seconds") == (
            "failed", "worker_timeout", 0,
        )
        assert _reserved(cursor, user_id) == (0, 0)

        for status in ("cancelled", "pending", "finalizing", "completed"):
            cursor.execute(
                "UPDATE jobs SET status = %s, error_code = NULL WHERE id = %s", (status, job_id)
            )
            cursor.execute("SELECT timeout_job_secure(%s, 'out of time')", (job_id,))
            assert cursor.fetchone()[0] is False
            assert _job(cursor, job_id, "status, error_code") == (status, None)


def test_timeout_auto_retry_is_granted_once_and_respects_limits():
    with scratch_schema(*MIGRATIONS) as cursor:
        user_id, job_id = _processing_job(cursor)
        cursor.execute("UPDATE jobs SET continuation_count = 3 WHERE id = %s", (job_id,))
        cursor.execute("SELECT timeout_job_secure(%s, 'out of time')", (job_id,))

        # Owner is at their concurrency limit: deferred, not consumed.
        other = uuid.uuid4()
        cursor.execute(
            "INSERT INTO jobs (id, user_id, status) VALUES (%s, %s, 'processing')",
            (other, user_id),
        )
        cursor.execute("SELECT auto_retry_timed_out_job(%s, %s, 3, 1)", (job_id, user_id))
        assert cursor.fetchone()[0] is False
        assert _job(cursor, job_id, "status, timeout_auto_retries") == ("failed", 0)
        cursor.execute("DELETE FROM jobs WHERE id = %s", (other,))

        cursor.execute("SELECT auto_retry_timed_out_job(%s, %s, 3, 1)", (job_id, user_id))
        assert cursor.fetchone()[0] is True
        assert _job(
            cursor, job_id,
            "status, error_code, retry_count, timeout_auto_retries, continuation_count",
        ) == ("pending", None, 1, 1, 3)

        # A second call (a concurrent check-stale run) gets nothing to dispatch.
        cursor.execute("SELECT auto_retry_timed_out_job(%s, %s, 3, 1)", (job_id, user_id))
        assert cursor.fetchone()[0] is False

        # Timing out again does not earn another automatic retry.
        cursor.execute("SELECT claim_job(%s, 3)", (job_id,))
        cursor.execute("SELECT timeout_job_secure(%s, 'out of time')", (job_id,))
        cursor.execute("SELECT auto_retry_timed_out_job(%s, %s, 3, 1)", (job_id, user_id))
        assert cursor.fetchone()[0] is False
        assert _job(cursor, job_id, "status, error_code") == ("failed", "worker_timeout")
