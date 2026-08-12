import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]


def test_cross_month_reservation_settles_in_original_period():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    psycopg = pytest.importorskip("psycopg", reason="psycopg is required for PostgreSQL integration tests")

    schema = f"job_security_{uuid.uuid4().hex}"
    user_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    job_id = uuid.uuid4()
    access_token = uuid.uuid4()
    video_hash = "a" * 64
    gcs_path = f"uploads/{user_id}/{intent_id}/video.mp4"

    migration = (BACKEND / "sql/migrations/005_job_upload_quota_security.sql").read_text(
        encoding="utf-8"
    )
    migration = migration.removeprefix("BEGIN;\n")
    if migration.rstrip().endswith("COMMIT;"):
        migration = migration.rstrip()[:-len("COMMIT;")]
    migration = re.sub(r"\bpublic\b", schema, migration)
    migration = migration.replace("auth.uid()", "NULL::uuid")
    migration = migration.replace("FROM PUBLIC, anon, authenticated", "FROM PUBLIC")
    migration = migration.replace("TO authenticated", "TO PUBLIC")
    migration = migration.replace("TO service_role", "TO PUBLIC")

    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
            cursor.execute(f'SET LOCAL search_path TO "{schema}"')
            cursor.execute(
                """
                CREATE TABLE user_profiles (
                  id UUID PRIMARY KEY,
                  is_admin BOOLEAN NOT NULL DEFAULT false,
                  subscription_plan TEXT NOT NULL DEFAULT 'free'
                );
                CREATE TABLE jobs (
                  id UUID PRIMARY KEY,
                  access_token UUID NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',
                  filename TEXT NOT NULL,
                  gcs_path TEXT,
                  file_size_bytes BIGINT,
                  video_hash TEXT,
                  progress INTEGER DEFAULT 0,
                  stage TEXT,
                  message TEXT,
                  estimated_duration_seconds INTEGER,
                  retry_count INTEGER DEFAULT 0,
                  params JSONB,
                  error_code TEXT,
                  error_message TEXT,
                  result_json JSONB,
                  result_srt TEXT,
                  result_vtt TEXT,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now(),
                  started_at TIMESTAMPTZ,
                  completed_at TIMESTAMPTZ,
                  failed_at TIMESTAMPTZ,
                  cancelled_at TIMESTAMPTZ,
                  last_seen TIMESTAMPTZ DEFAULT now(),
                  user_id UUID REFERENCES user_profiles(id)
                );
                CREATE TABLE user_usage_monthly (
                  user_id UUID NOT NULL REFERENCES user_profiles(id),
                  period_start DATE NOT NULL,
                  transcription_seconds INTEGER NOT NULL DEFAULT 0,
                  llm_tokens INTEGER NOT NULL DEFAULT 0,
                  chat_messages INTEGER NOT NULL DEFAULT 0,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (user_id, period_start)
                );
                CREATE TABLE rate_limits (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id UUID NOT NULL REFERENCES user_profiles(id),
                  limit_type TEXT NOT NULL,
                  count INTEGER NOT NULL DEFAULT 0,
                  window_start TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (user_id, limit_type)
                );
                """
            )
            cursor.execute(migration)
            cursor.execute(
                "INSERT INTO user_profiles (id) VALUES (%s)",
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO upload_intents (
                  id, user_id, gcs_path, original_filename, content_type,
                  expected_size_bytes, expires_at
                ) VALUES (%s, %s, %s, 'video.mp4', 'video/mp4', 100, now() + interval '1 hour')
                """,
                (intent_id, user_id, gcs_path),
            )
            cursor.execute(
                """
                SELECT id FROM create_job_secure(
                  %s, %s, %s, 'video.mp4', %s, 100, %s, 120, '{}'::jsonb,
                  60, 3600, 1, 3
                )
                """,
                (job_id, access_token, user_id, gcs_path, video_hash),
            )
            assert cursor.fetchone()[0] == job_id
            cursor.execute("SELECT claim_job(%s, 3)", (job_id,))
            assert cursor.fetchone()[0] is True

            cursor.execute(
                """
                WITH original AS (
                  SELECT quota_reservation_period AS current_period
                  FROM jobs WHERE id = %s
                ), moved AS (
                  UPDATE user_usage_monthly u
                  SET period_start = (original.current_period - interval '1 month')::date
                  FROM original
                  WHERE u.user_id = %s AND u.period_start = original.current_period
                  RETURNING u.period_start
                )
                UPDATE jobs SET quota_reservation_period = (SELECT period_start FROM moved)
                WHERE id = %s
                """,
                (job_id, user_id, job_id),
            )
            cursor.execute(
                """
                SELECT settle_completed_job(
                  %s, %s, %s, '{}'::jsonb, '', '', 120, 1, %s
                )
                """,
                (job_id, user_id, video_hash, gcs_path),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                """
                SELECT transcription_seconds, reserved_transcription_seconds,
                       period_start < date_trunc('month', now() AT TIME ZONE 'UTC')::date
                FROM user_usage_monthly WHERE user_id = %s
                """,
                (user_id,),
            )
            assert cursor.fetchone() == (120, 0, True)
            cursor.execute(
                "SELECT quota_reserved_seconds, quota_reservation_period FROM jobs WHERE id = %s",
                (job_id,),
            )
            assert cursor.fetchone() == (0, None)
    finally:
        connection.rollback()
        connection.close()


def test_atomic_media_deletion_outbox_reference_semantics():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    psycopg = pytest.importorskip(
        "psycopg", reason="psycopg is required for PostgreSQL integration tests"
    )

    schema = f"media_deletion_{uuid.uuid4().hex}"
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    shared_job_a = uuid.uuid4()
    shared_job_b = uuid.uuid4()
    exclusive_job = uuid.uuid4()
    blocked_job = uuid.uuid4()
    processing_job = uuid.uuid4()
    finalizing_job = uuid.uuid4()
    stale_finalizing_job = uuid.uuid4()
    shared_key = f"processed/{user_a}/shared/video.mp4"
    exclusive_key = f"processed/{user_a}/{uuid.uuid4()}/video.mp4"
    migration = (BACKEND / "sql/migrations/006_media_deletion_outbox.sql").read_text(
        encoding="utf-8"
    )
    migration = migration.removeprefix("BEGIN;\n")
    if migration.rstrip().endswith("COMMIT;"):
        migration = migration.rstrip()[:-len("COMMIT;")]
    migration = re.sub(r"\bpublic\b", schema, migration)
    migration = migration.replace("FROM PUBLIC, anon, authenticated", "FROM PUBLIC")
    migration = migration.replace("TO authenticated", "TO PUBLIC")
    migration = migration.replace("TO service_role", "TO PUBLIC")
    finalization_migration = (
        BACKEND / "sql/migrations/007_recoverable_job_finalization.sql"
    ).read_text(encoding="utf-8")
    finalization_migration = finalization_migration.removeprefix("BEGIN;\n")
    if finalization_migration.rstrip().endswith("COMMIT;"):
        finalization_migration = finalization_migration.rstrip()[:-len("COMMIT;")]
    finalization_migration = re.sub(r"\bpublic\b", schema, finalization_migration)
    finalization_migration = finalization_migration.replace(
        "FROM PUBLIC, anon, authenticated", "FROM PUBLIC"
    ).replace("TO service_role", "TO PUBLIC")
    recovery_migration = (
        BACKEND / "sql/migrations/008_atomic_finalization_recovery.sql"
    ).read_text(encoding="utf-8")
    recovery_migration = recovery_migration.removeprefix("BEGIN;\n")
    if recovery_migration.rstrip().endswith("COMMIT;"):
        recovery_migration = recovery_migration.rstrip()[:-len("COMMIT;")]
    recovery_migration = re.sub(r"\bpublic\b", schema, recovery_migration)
    recovery_migration = recovery_migration.replace(
        "FROM PUBLIC, anon, authenticated", "FROM PUBLIC"
    ).replace("TO service_role", "TO PUBLIC")

    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
            cursor.execute(f'SET LOCAL search_path TO "{schema}"')
            cursor.execute(
                """
                CREATE TABLE jobs (
                  id UUID PRIMARY KEY,
                  user_id UUID NOT NULL,
                  gcs_path TEXT,
                  status TEXT NOT NULL DEFAULT 'completed',
                  video_hash TEXT,
                  result_json JSONB,
                  result_srt TEXT,
                  result_vtt TEXT,
                  video_duration_seconds INTEGER,
                  gpu_seconds NUMERIC,
                  retry_count INTEGER NOT NULL DEFAULT 0,
                  error_code TEXT,
                  error_message TEXT,
                  progress INTEGER NOT NULL DEFAULT 0,
                  stage TEXT,
                  message TEXT,
                  quota_reserved_seconds INTEGER NOT NULL DEFAULT 0,
                  quota_reservation_period DATE,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
                  completed_at TIMESTAMPTZ,
                  failed_at TIMESTAMPTZ
                );
                CREATE TABLE user_usage_monthly (
                  user_id UUID NOT NULL,
                  period_start DATE NOT NULL,
                  transcription_seconds INTEGER NOT NULL DEFAULT 0,
                  reserved_transcription_seconds INTEGER NOT NULL DEFAULT 0,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (user_id, period_start)
                );
                """
            )
            cursor.execute(migration)
            cursor.execute(finalization_migration)
            cursor.execute(recovery_migration)
            cursor.execute(
                "INSERT INTO jobs (id, user_id, gcs_path, status) VALUES (%s, %s, %s, 'processing')",
                (processing_job, user_a, f"processed/{user_a}/processing/video.mp4"),
            )
            cursor.execute(
                "SELECT deleted, error_code FROM delete_job_permanent_secure(%s, %s)",
                (processing_job, user_a),
            )
            assert cursor.fetchone() == (False, "job_not_terminal")
            cursor.execute("SELECT status FROM jobs WHERE id = %s", (processing_job,))
            assert cursor.fetchone() == ("processing",)
            cursor.execute("SELECT count(*) FROM media_delete_outbox")
            assert cursor.fetchone()[0] == 0

            cursor.execute(
                "INSERT INTO jobs (id, user_id, gcs_path) VALUES (%s, %s, %s), (%s, %s, %s)",
                (shared_job_a, user_a, shared_key, shared_job_b, user_b, shared_key),
            )
            cursor.execute(
                "SELECT deleted, outbox_id FROM delete_job_permanent_secure(%s, %s)",
                (shared_job_a, user_a),
            )
            assert cursor.fetchone() == (True, None)
            cursor.execute("SELECT id FROM jobs WHERE gcs_path = %s", (shared_key,))
            assert cursor.fetchall() == [(shared_job_b,)]
            cursor.execute("SELECT count(*) FROM media_delete_outbox")
            assert cursor.fetchone()[0] == 0

            cursor.execute(
                "INSERT INTO jobs (id, user_id, gcs_path) VALUES (%s, %s, %s)",
                (exclusive_job, user_a, exclusive_key),
            )
            cursor.execute(
                "SELECT deleted, outbox_id IS NOT NULL FROM delete_job_permanent_secure(%s, %s)",
                (exclusive_job, user_a),
            )
            assert cursor.fetchone() == (True, True)
            cursor.execute("SAVEPOINT claimed_key")
            with pytest.raises(psycopg.errors.UniqueViolation):
                cursor.execute(
                    "INSERT INTO jobs (id, user_id, gcs_path) VALUES (%s, %s, %s)",
                    (blocked_job, user_a, exclusive_key),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT claimed_key")
            cursor.execute("SELECT count(*) FROM jobs WHERE id = %s", (blocked_job,))
            assert cursor.fetchone()[0] == 0

            source_key = f"uploads/{user_a}/{uuid.uuid4()}/final.mp4"
            final_key = source_key.replace("uploads/", "processed/", 1)
            cursor.execute(
                """
                INSERT INTO user_usage_monthly (
                  user_id, period_start, reserved_transcription_seconds
                ) VALUES (%s, date_trunc('month', now())::date, 12)
                """,
                (user_a,),
            )
            cursor.execute(
                """
                INSERT INTO jobs (
                  id, user_id, gcs_path, status, video_hash,
                  quota_reserved_seconds, quota_reservation_period
                ) VALUES (
                  %s, %s, %s, 'processing', %s, 12,
                  date_trunc('month', now())::date
                )
                """,
                (finalizing_job, user_a, source_key, "f" * 64),
            )
            cursor.execute(
                """
                SELECT begin_job_finalization(
                  %s, %s, %s, '{}'::jsonb, 'srt', 'vtt', 12, 1.5, %s
                )
                """,
                (finalizing_job, user_a, "f" * 64, final_key),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "UPDATE jobs SET status = 'cancelled' WHERE id = %s AND status IN ('pending', 'processing')",
                (finalizing_job,),
            )
            assert cursor.rowcount == 0
            cursor.execute(
                """
                SELECT begin_job_finalization(
                  %s, %s, %s, '{}'::jsonb, 'srt', 'vtt', 12, 1.5, %s
                )
                """,
                (finalizing_job, user_a, "f" * 64, final_key),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT settle_finalizing_job(%s, %s)",
                (finalizing_job, user_a),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT status, gcs_path, final_media_key FROM jobs WHERE id = %s",
                (finalizing_job,),
            )
            assert cursor.fetchone() == ("completed", final_key, None)
            cursor.execute(
                "SELECT media_key, status FROM media_delete_outbox WHERE source_job_id = %s",
                (finalizing_job,),
            )
            assert cursor.fetchone() == (source_key, "pending")

            stale_source_key = f"uploads/{user_a}/{uuid.uuid4()}/stale.mp4"
            stale_final_key = stale_source_key.replace("uploads/", "processed/", 1)
            cursor.execute(
                """
                INSERT INTO jobs (
                  id, user_id, gcs_path, status, video_hash, result_json,
                  result_srt, result_vtt, retry_count, final_media_key,
                  finalization_started_at, last_seen
                ) VALUES (
                  %s, %s, %s, 'finalizing', %s, '{"segments": []}'::jsonb,
                  'stale-srt', 'stale-vtt', 0, %s, now() - interval '1 hour',
                  now() - interval '1 hour'
                )
                """,
                (
                    stale_finalizing_job,
                    user_a,
                    stale_source_key,
                    "e" * 64,
                    stale_final_key,
                ),
            )
            cursor.execute(
                """
                SELECT id FROM jobs WHERE id = %s
                """,
                (stale_finalizing_job,),
            )
            assert cursor.fetchone()[0] == stale_finalizing_job
            connection.commit()

            barrier = threading.Barrier(2, timeout=10)

            def claim_stale_job():
                concurrent_connection = psycopg.connect(database_url)
                try:
                    with concurrent_connection.cursor() as concurrent_cursor:
                        concurrent_cursor.execute(f'SET search_path TO "{schema}"')
                        barrier.wait()
                        concurrent_cursor.execute(
                            """
                            SELECT job_id, action, retry_count
                            FROM claim_stale_finalizing_job(
                              now() - interval '5 minutes', 1
                            )
                            """
                        )
                        row = concurrent_cursor.fetchone()
                    concurrent_connection.commit()
                    return row
                finally:
                    concurrent_connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                claims = list(executor.map(lambda _index: claim_stale_job(), range(2)))
            assert [claim for claim in claims if claim is not None] == [
                (stale_finalizing_job, "redispatch", 1)
            ]

            cursor.execute(f'SET LOCAL search_path TO "{schema}"')
            cursor.execute(
                "UPDATE jobs SET last_seen = now() - interval '1 hour' WHERE id = %s",
                (stale_finalizing_job,),
            )
            cursor.execute(
                """
                SELECT job_id, action, retry_count
                FROM claim_stale_finalizing_job(now() - interval '5 minutes', 1)
                """
            )
            assert cursor.fetchone() == (stale_finalizing_job, "failed", 1)
            cursor.execute(
                """
                SELECT status, error_code, gcs_path, final_media_key,
                       result_srt, result_vtt
                FROM jobs WHERE id = %s
                """,
                (stale_finalizing_job,),
            )
            assert cursor.fetchone() == (
                "failed",
                "finalization_retries_exhausted",
                stale_source_key,
                stale_final_key,
                "stale-srt",
                "stale-vtt",
            )
            cursor.execute(
                """
                SELECT status, available_at > now()
                FROM media_delete_outbox WHERE media_key = %s
                """,
                (stale_final_key,),
            )
            assert cursor.fetchone() == ("pending", True)
            cursor.execute(
                """
                SELECT count(*)
                FROM claim_stale_finalizing_job(now() - interval '5 minutes', 1)
                """
            )
            assert cursor.fetchone()[0] == 0

            cursor.execute("SAVEPOINT cleanup_pending")
            with pytest.raises(psycopg.errors.RaiseException, match="finalization_cleanup_pending"):
                cursor.execute(
                    "SELECT id FROM retry_job_secure(%s, %s, 1, NULL)",
                    (stale_finalizing_job, user_a),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT cleanup_pending")
            cursor.execute(
                """
                UPDATE media_delete_outbox
                SET status = 'completed', completed_at = now()
                WHERE media_key = %s
                """,
                (stale_final_key,),
            )
            cursor.execute(
                "SELECT id FROM retry_job_secure(%s, %s, 1, NULL)",
                (stale_finalizing_job, user_a),
            )
            assert cursor.fetchone()[0] == stale_finalizing_job
            cursor.execute(
                """
                SELECT status, retry_count, final_media_key,
                       finalization_started_at, result_json, result_srt, result_vtt
                FROM jobs WHERE id = %s
                """,
                (stale_finalizing_job,),
            )
            assert cursor.fetchone() == ("pending", 0, None, None, None, None, None)
    finally:
        connection.rollback()
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        connection.close()
