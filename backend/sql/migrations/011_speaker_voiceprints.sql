BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- Greenfield table: replaces the local-disk speaker_database.json, which was
-- wiped every time the Cloud Run container scaled to zero (min-instances=0).
CREATE TABLE IF NOT EXISTS speaker_voiceprints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  speaker_name TEXT NOT NULL,
  embedding vector(512) NOT NULL,
  samples_count INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_speaker_voiceprints_owner_speaker
  ON speaker_voiceprints (user_id, speaker_name);
CREATE INDEX IF NOT EXISTS idx_speaker_voiceprints_hnsw
  ON speaker_voiceprints USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

DO $$
DECLARE
  v_table_name TEXT;
  v_policy RECORD;
BEGIN
  FOREACH v_table_name IN ARRAY ARRAY[
    'speaker_voiceprints'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', v_table_name);
    FOR v_policy IN
      SELECT policyname FROM pg_policies
      WHERE schemaname = 'public' AND tablename = v_table_name
    LOOP
      EXECUTE format('DROP POLICY %I ON %I', v_policy.policyname, v_table_name);
    END LOOP;
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR SELECT TO authenticated USING ((SELECT auth.uid()) = user_id)',
      v_table_name || '_select_own',
      v_table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)',
      v_table_name || '_service_role_all',
      v_table_name
    );
  END LOOP;
END;
$$;

-- Catalog-introspection-safe drop, same technique as 009/010: makes this
-- migration rerunnable regardless of how Postgres renders vector() typmods.
DO $$
DECLARE v_function RECORD;
BEGIN
  FOR v_function IN
    SELECT
      namespace.nspname AS schema_name,
      proc.proname AS function_name,
      pg_get_function_identity_arguments(proc.oid) AS identity_arguments
    FROM pg_proc AS proc
    JOIN pg_namespace AS namespace ON namespace.oid = proc.pronamespace
    WHERE namespace.nspname = 'public'
      AND proc.proname IN (
        'search_speaker_voiceprints_by_embedding'
      )
  LOOP
    EXECUTE format(
      'REVOKE ALL ON FUNCTION %I.%I(%s) FROM PUBLIC, authenticated',
      v_function.schema_name,
      v_function.function_name,
      v_function.identity_arguments
    );
    EXECUTE format(
      'DROP FUNCTION %I.%I(%s)',
      v_function.schema_name,
      v_function.function_name,
      v_function.identity_arguments
    );
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION search_speaker_voiceprints_by_embedding(
  p_user_id UUID,
  query_embedding vector(512),
  match_count INTEGER DEFAULT 1
)
RETURNS TABLE (
  speaker_name TEXT,
  samples_count INTEGER,
  similarity DOUBLE PRECISION
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  SET LOCAL hnsw.ef_search = 200;
  RETURN QUERY
  SELECT
    sv.speaker_name,
    sv.samples_count,
    1 - (sv.embedding <=> query_embedding) AS similarity
  FROM speaker_voiceprints AS sv
  WHERE sv.user_id = p_user_id
  ORDER BY sv.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION search_speaker_voiceprints_by_embedding(UUID, vector, INTEGER) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION search_speaker_voiceprints_by_embedding(UUID, vector, INTEGER) TO service_role;

COMMIT;
