from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8")


def test_mutating_job_routes_require_owner_not_share_token():
    source = _read("routers/jobs.py")
    for route in (
        '@router.delete("/{job_id}"',
        '@router.post("/{job_id}/retry"',
        '@router.delete("/{job_id}/permanent"',
        '@router.get("/{job_id}/share"',
    ):
        section = source[source.index(route):]
        section = section[: section.index("\n@router.", 1) if "\n@router." in section[1:] else len(section)]
        assert "require_job_owner(job_id, user_id)" in section
        assert "require_job_access(job_id, token, user_id)" not in section


def test_worker_preserves_content_hash_and_tenant_scopes_pipeline_cache():
    source = _read("services/background_worker.py")
    assert 'video_hash = job["video_hash"]' in source
    assert "hashlib.md5(gcs_path.encode())" not in source
    assert "PipelineCacheService.get_cached(user_id, video_hash" in source
    assert "actual_hash != video_hash" in source


def test_upload_paths_and_submission_are_owner_bound():
    gcs_source = _read("services/gcs_service.py")
    upload_source = _read("routers/upload.py")
    jobs_source = _read("routers/jobs.py")
    assert 'f"{settings.GCS_UPLOAD_PREFIX}{user_id}/{upload_intent_id}/{safe_filename}"' in gcs_source
    assert 'table("upload_intents").insert' in upload_source
    assert '"user_id", user_id' in upload_source
    assert "is_user_upload_path(job_request.gcs_path, user_id)" in jobs_source
    assert "actual_size != job_request.file_size_bytes" in jobs_source


def test_permanent_deletion_checks_exact_key_ownership_before_media_delete():
    jobs_source = _read("routers/jobs.py")
    migration = _read("sql/migrations/006_media_deletion_outbox.sql")
    section = jobs_source[jobs_source.index('async def delete_job_permanent'):]
    section = section[:section.index("\n@router.", 1)]

    assert section.index("claim_permanent_deletion") < section.index(
        "drain_media_deletions_best_effort"
    )
    assert "get_media_storage" not in section
    assert "delete_job_permanent_secure" in migration
    assert "WHERE gcs_path = v_job.gcs_path" in migration
    assert "v_reference_count = 1" in migration
    assert "uploads/" in migration and "processed/" in migration
    assert "jobs_guard_claimed_media_key" in migration


def test_media_outbox_is_service_only_rerunnable_and_maintained():
    migration = _read("sql/migrations/006_media_deletion_outbox.sql")
    jobs_source = _read("routers/jobs.py")

    assert "CREATE TABLE IF NOT EXISTS media_delete_outbox" in migration
    assert "DROP POLICY IF EXISTS media_delete_outbox_service_role_all" in migration
    assert "TO service_role" in migration
    assert "TO authenticated" not in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "status = 'processing' AND claimed_at <" in migration
    assert "JobQueueService.process_media_delete_outbox" in jobs_source
    assert "limit=10" in jobs_source


def test_permanent_delete_is_terminal_only_and_worker_uses_durable_finalization():
    migration = _read("sql/migrations/006_media_deletion_outbox.sql")
    jobs_source = _read("routers/jobs.py")
    worker_source = _read("services/background_worker.py")

    assert "v_job.status NOT IN ('completed', 'failed', 'cancelled')" in migration
    assert "'job_not_terminal'::TEXT" in migration
    assert "Only completed, failed, or cancelled jobs can be permanently deleted" in jobs_source
    cancelled_helper = worker_source[
        worker_source.index("def _check_cancelled"):worker_source.index("class HeartbeatThread")
    ]
    assert "if not job:" in cancelled_helper
    assert 'job.get("status") != "processing"' in cancelled_helper
    begin_index = worker_source.index("JobQueueService.begin_finalization(")
    copy_index = worker_source.index("media_storage.copy_to_processed, gcs_path")
    settle_index = worker_source.index("JobQueueService.settle_finalization(")
    assert worker_source.rfind("_check_cancelled(job_id)", 0, begin_index) > 0
    assert begin_index < copy_index < settle_index


def test_recoverable_finalization_migration_contract():
    migration = _read("sql/migrations/007_recoverable_job_finalization.sql")
    queue_source = _read("services/job_queue_service.py")
    worker_source = _read("services/background_worker.py")

    assert "ADD COLUMN IF NOT EXISTS final_media_key" in migration
    assert "status = 'finalizing'" in migration
    assert "WHERE id = p_job_id AND user_id = p_user_id AND status = 'processing'" in migration
    settlement = migration[migration.index("settle_finalizing_job"):]
    assert settlement.index("status = 'completed'") < settlement.index(
        "INSERT INTO media_delete_outbox"
    )
    assert "ON CONFLICT (media_key) DO NOTHING" in migration
    assert "FROM PUBLIC, anon, authenticated" in migration
    assert "TO service_role" in migration
    assert 'rpc("claim_stale_finalizing_job"' in queue_source
    assert "return await self._resume_finalization(job, media_storage)" in worker_source


def test_atomic_stale_finalization_recovery_contract():
    migration = _read("sql/migrations/008_atomic_finalization_recovery.sql")

    assert "claim_stale_finalizing_job" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "FOR UPDATE" in migration
    assert "status = 'finalizing' AND last_seen < p_cutoff" in migration
    assert "retry_count = COALESCE(jobs.retry_count, 0) + 1" in migration
    assert "error_code = 'finalization_retries_exhausted'" in migration
    assert "status = 'failed'" in migration
    assert "quota_reserved_seconds = 0" in migration
    assert "final_media_key = NULL" in migration
    assert "finalization_cleanup_pending" in migration
    assert "available_at <= now()" in migration
    assert "now() + interval '10 minutes'" in migration
    assert "TO service_role" in migration
    assert "TO authenticated" not in migration


def test_security_migration_contains_atomic_service_role_only_contracts():
    sql = _read("sql/migrations/005_job_upload_quota_security.sql")
    required_functions = (
        "create_job_secure",
        "claim_job",
        "adjust_job_quota_reservation",
        "settle_completed_job",
        "release_job_quota_reservation",
        "fail_job_secure",
        "cancel_job_secure",
        "retry_job_secure",
        "increment_monthly_usage",
        "consume_rate_limit",
    )
    for function in required_functions:
        assert f"FUNCTION {function}" in sql
        assert f"FUNCTION {function}" in sql[sql.index("REVOKE ALL ON FUNCTION"):]
    assert "FOR UPDATE" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "TO service_role" in sql
    assert "TO authenticated" not in sql[sql.index("REVOKE ALL ON FUNCTION"):]


def test_migration_bootstraps_pipeline_cache_and_is_rerunnable():
    sql = _read("sql/migrations/005_job_upload_quota_security.sql")
    assert "CREATE TABLE IF NOT EXISTS pipeline_cache" in sql
    assert "ADD COLUMN IF NOT EXISTS user_id" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_cache_owner_video_stage" in sql
    assert "SELECT 1 FROM pg_constraint" in sql
    assert "pg_get_constraintdef(oid) NOT LIKE '%user_id%'" in sql
    assert "DROP POLICY IF EXISTS pipeline_cache_select_own" in sql
    assert "SELECT policyname FROM pg_policies" in sql
    assert "DROP POLICY IF EXISTS jobs_own ON jobs" in sql
    assert "DROP POLICY IF EXISTS jobs_legacy ON jobs" in sql
    assert 'DROP POLICY IF EXISTS "Users manage own jobs" ON jobs' in sql
    assert 'DROP POLICY IF EXISTS "Legacy jobs read-only" ON jobs' in sql
    assert "tablename = 'jobs'" in sql
    assert "CREATE POLICY jobs_select_own ON jobs" in sql
    assert "FOR SELECT TO authenticated" in sql
    assert "CREATE POLICY jobs_service_role_all ON jobs" in sql
    assert "'image_embeddings', 'face_tags', 'image_face_presence'" in sql
    assert "'video_face_tags', 'video_face_presence'" in sql
    assert "CREATE POLICY visual_service_role_only" in sql
    assert "FOR ALL TO service_role" in sql
    assert "Users search own video embeddings" not in sql
    assert "Users read own video face tags" not in sql
    assert "Users read own video face presence" not in sql


def test_terminal_transitions_are_atomic_compare_and_set_rpcs():
    sql = _read("sql/migrations/005_job_upload_quota_security.sql")
    service = _read("services/job_queue_service.py")
    for function in ("fail_job_secure", "cancel_job_secure"):
        section = sql[sql.index(f"FUNCTION {function}"):]
        section = section[:section.index("CREATE OR REPLACE FUNCTION", 20)]
        assert "FOR UPDATE" in section
        assert "status IN ('pending', 'processing')" in section
        assert "reserved_transcription_seconds" in section
        assert "quota_reserved_seconds = 0" in section
        assert "pg_advisory_xact_lock" in section
    assert 'rpc("fail_job_secure"' in service
    assert 'rpc("cancel_job_secure"' in service
    assert 'rpc("release_job_quota_reservation"' not in service


def test_quota_lock_order_and_duration_probe_fail_closed():
    sql = _read("sql/migrations/005_job_upload_quota_security.sql")
    for function in (
        "adjust_job_quota_reservation",
        "settle_completed_job",
        "release_job_quota_reservation",
    ):
        section = sql[sql.index(f"FUNCTION {function}"):]
        section = section[:section.index("CREATE OR REPLACE FUNCTION", 20)]
        assert section.index("pg_advisory_xact_lock") < section.index("FOR UPDATE")
    worker = _read("services/background_worker.py")
    assert "Could not determine media duration for quota enforcement" in worker
    assert "probed_duration_seconds is None or probed_duration_seconds <= 0" in worker
    assert "Job has no owner; refusing unscoped processing" in worker


def test_retry_is_atomic_owner_scoped_and_concurrency_checked():
    sql = _read("sql/migrations/005_job_upload_quota_security.sql")
    service = _read("services/job_queue_service.py")
    section = sql[sql.index("FUNCTION retry_job_secure"):]
    section = section[:section.index("CREATE OR REPLACE FUNCTION", 20)]
    assert section.index("pg_advisory_xact_lock") < section.index("FOR UPDATE")
    assert "id = p_job_id AND user_id = p_user_id FOR UPDATE" in section
    assert "status IN ('pending', 'processing')" in section
    assert "v_active >= p_user_concurrent_limit" in section
    assert "status = 'failed'" in section
    assert "COALESCE(retry_count, 0) < p_max_retries" in section
    assert 'rpc("retry_job_secure"' in service
    assert '"p_user_concurrent_limit": limits["max_concurrent_jobs"]' in service
    retry_method = service[service.index("def retry_job("):]
    retry_method = retry_method[:retry_method.index("\n    @staticmethod", 1)]
    assert 'table("jobs").update' not in retry_method


def test_quota_reservations_keep_their_original_monthly_ledger_period():
    sql = _read("sql/migrations/005_job_upload_quota_security.sql")
    assert "ADD COLUMN IF NOT EXISTS quota_reservation_period DATE" in sql
    assert "jobs_quota_reservation_period_required" in sql
    assert "quota_reserved_seconds > 0 AND quota_reservation_period IS NULL" in sql

    create = sql[sql.index("FUNCTION create_job_secure"):]
    create = create[:create.index("CREATE OR REPLACE FUNCTION", 20)]
    assert "quota_reserved_seconds, quota_reservation_period" in create
    assert "p_duration_seconds, v_reservation, v_period" in create

    adjust = sql[sql.index("FUNCTION adjust_job_quota_reservation"):]
    adjust = adjust[:adjust.index("CREATE OR REPLACE FUNCTION", 20)]
    assert "v_job.quota_reservation_period" in adjust
    assert "COALESCE(" in adjust
    assert "quota_reservation_period = v_period" in adjust

    settle = sql[sql.index("FUNCTION settle_completed_job"):]
    settle = settle[:settle.index("CREATE OR REPLACE FUNCTION", 20)]
    assert "v_period := v_job.quota_reservation_period" in settle
    assert "period_start = v_period" in settle
    assert "quota_reservation_period = NULL" in settle
    assert "date_trunc('month', now()" not in settle

    for function in (
        "release_job_quota_reservation",
        "fail_job_secure",
        "cancel_job_secure",
    ):
        section = sql[sql.index(f"FUNCTION {function}"):]
        section = section[:section.index("CREATE OR REPLACE FUNCTION", 20)]
        assert "v_job.quota_reservation_period" in section
        assert "period_start = v_period" in section
        assert "quota_reservation_period = NULL" in section
        assert "date_trunc('month', now()" not in section

    retry = sql[sql.index("FUNCTION retry_job_secure"):]
    retry = retry[:retry.index("CREATE OR REPLACE FUNCTION", 20)]
    assert "quota_reserved_seconds = 0, quota_reservation_period = NULL" in retry


def test_usage_and_rate_limit_updates_use_atomic_rpcs():
    usage = _read("services/usage_meter.py")
    rate_limit = _read("middleware/rate_limit.py")
    assert 'rpc("increment_monthly_usage"' in usage
    assert "Read-modify-write" not in usage
    assert 'rpc("consume_rate_limit"' in rate_limit
    assert "Fail open" not in rate_limit
