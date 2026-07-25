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
    gpu_seconds REAL
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
    user_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(video_hash, segment_id)
);
CREATE INDEX IF NOT EXISTS idx_image_embeddings_video_hash ON image_embeddings(video_hash);

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
