-- LOCAL_MODE SQLite schema. Mirrors the Supabase tables actually queried by
-- the backend (columns derived from code call sites + migrations 002/004 —
-- supabase_schema.sql alone is stale). Vector columns are stored as JSON text;
-- similarity RPCs are computed in Python (services/local_db.py).

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    filename TEXT NOT NULL,
    gcs_path TEXT,
    file_size_bytes INTEGER,
    video_hash TEXT,
    progress INTEGER DEFAULT 0,
    stage TEXT,
    message TEXT,
    estimated_duration_seconds INTEGER,
    retry_count INTEGER DEFAULT 0,
    params TEXT,
    error_code TEXT,
    error_message TEXT,
    result_json TEXT,
    result_srt TEXT,
    result_vtt TEXT,
    created_at TEXT,
    updated_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    failed_at TEXT,
    cancelled_at TEXT,
    last_seen TEXT,
    user_id TEXT,
    video_duration_seconds INTEGER,
    gpu_seconds REAL,
    quota_reserved_seconds INTEGER NOT NULL DEFAULT 0,
    quota_reservation_period TEXT,
    upload_intent_id TEXT,
    final_media_key TEXT,
    finalization_started_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_video_hash ON jobs(video_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);

CREATE TABLE IF NOT EXISTS user_profiles (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    -- no 'groq' default here (unlike prod): NULL lets settings.DEFAULT_LLM_PROVIDER win
    default_llm_provider TEXT,
    visual_search_terms TEXT DEFAULT '',
    visual_search_phrases TEXT DEFAULT '',
    email_verified INTEGER DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    subscription_plan TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    subscription_status TEXT,
    current_period_end TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    encrypted_key TEXT NOT NULL,
    key_suffix TEXT NOT NULL,
    is_valid INTEGER,
    validation_error TEXT,
    validated_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, provider)
);

CREATE TABLE IF NOT EXISTS invite_codes (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    created_by TEXT,
    used_by TEXT,
    used_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_action ON usage_logs(user_id, action);

CREATE TABLE IF NOT EXISTS rate_limits (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    limit_type TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    window_start TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, limit_type)
);

CREATE TABLE IF NOT EXISTS email_verifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS password_resets (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS user_usage_monthly (
    user_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    transcription_seconds INTEGER NOT NULL DEFAULT 0,
    llm_tokens INTEGER NOT NULL DEFAULT 0,
    chat_messages INTEGER NOT NULL DEFAULT 0,
    reserved_transcription_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (user_id, period_start)
);

CREATE TABLE IF NOT EXISTS image_embeddings (
    id TEXT PRIMARY KEY,
    video_hash TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    speaker TEXT,
    screenshot_url TEXT NOT NULL,
    embedding TEXT NOT NULL,
    caption TEXT,
    caption_embedding TEXT,
    user_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, video_hash, segment_id)
);
CREATE INDEX IF NOT EXISTS idx_image_embeddings_video_hash ON image_embeddings(video_hash);

CREATE TABLE IF NOT EXISTS image_caption_sentences (
    id TEXT PRIMARY KEY,
    image_embedding_id TEXT NOT NULL,
    video_hash TEXT NOT NULL,
    sentence TEXT NOT NULL,
    embedding TEXT NOT NULL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ics_video_hash ON image_caption_sentences(video_hash);

CREATE TABLE IF NOT EXISTS image_face_presence (
    id TEXT PRIMARY KEY,
    image_embedding_id TEXT NOT NULL,
    video_hash TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    face_embedding TEXT NOT NULL,
    bbox TEXT,
    det_score REAL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ifp_video_hash ON image_face_presence(video_hash);

CREATE TABLE IF NOT EXISTS face_tags (
    id TEXT PRIMARY KEY,
    video_hash TEXT NOT NULL,
    speaker_name TEXT NOT NULL,
    screenshot_url TEXT NOT NULL,
    bbox_x REAL NOT NULL,
    bbox_y REAL NOT NULL,
    bbox_w REAL NOT NULL,
    bbox_h REAL NOT NULL,
    embedding TEXT NOT NULL,
    created_at TEXT,
    UNIQUE(video_hash, screenshot_url, bbox_x, bbox_y)
);
CREATE INDEX IF NOT EXISTS idx_face_tags_video_hash ON face_tags(video_hash);

CREATE TABLE IF NOT EXISTS pipeline_cache (
    id TEXT PRIMARY KEY,
    video_hash TEXT NOT NULL,
    stage TEXT NOT NULL,
    data TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(video_hash, stage)
);

-- Column names must match backend/sql/migrations/011_speaker_voiceprints.sql
-- exactly: speaker_recognition.py issues the same .table() calls regardless
-- of whether it's talking to Supabase or this local fake.
CREATE TABLE IF NOT EXISTS speaker_voiceprints (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    speaker_name TEXT NOT NULL,
    embedding TEXT NOT NULL,
    samples_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, speaker_name)
);
CREATE INDEX IF NOT EXISTS idx_speaker_voiceprints_user ON speaker_voiceprints(user_id);

-- Mirrors backend/sql/migrations/005_job_upload_quota_security.sql's upload_intents.
CREATE TABLE IF NOT EXISTS upload_intents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    gcs_path TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    expected_size_bytes INTEGER NOT NULL,
    content_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    job_id TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_upload_intents_owner_status ON upload_intents(user_id, status, expires_at);

-- Mirrors backend/sql/migrations/006_media_deletion_outbox.sql + 008's available_at addition.
CREATE TABLE IF NOT EXISTS media_delete_outbox (
    id TEXT PRIMARY KEY,
    source_job_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    media_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    available_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_delete_outbox_status ON media_delete_outbox(status, created_at);

-- Mirrors backend/sql/migrations/010_owner_scoped_transcript_audio_embeddings.sql.
CREATE TABLE IF NOT EXISTS transcript_embeddings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    video_hash TEXT NOT NULL,
    index_config TEXT NOT NULL DEFAULT 'chunk_size_3',
    chunk_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    start_timestamp TEXT NOT NULL,
    end_timestamp TEXT NOT NULL,
    speaker TEXT,
    segment_count INTEGER NOT NULL DEFAULT 1,
    chunk_text TEXT NOT NULL,
    embedding TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, video_hash, index_config, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_owner_video ON transcript_embeddings(user_id, video_hash);

CREATE TABLE IF NOT EXISTS audio_event_embeddings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    video_hash TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    speaker TEXT,
    has_speech INTEGER NOT NULL DEFAULT 0,
    primary_event TEXT,
    speech_emotion TEXT,
    description TEXT NOT NULL,
    embedding TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, video_hash, segment_id)
);
CREATE INDEX IF NOT EXISTS idx_audio_event_embeddings_owner_video ON audio_event_embeddings(user_id, video_hash);
