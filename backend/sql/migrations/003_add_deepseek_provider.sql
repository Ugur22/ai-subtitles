-- Add DeepSeek as a supported LLM provider for saved settings and API keys.

DO $$
DECLARE
  constraint_name text;
BEGIN
  SELECT conname INTO constraint_name
  FROM pg_constraint
  WHERE conrelid = 'user_profiles'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%default_llm_provider%'
  LIMIT 1;

  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE user_profiles DROP CONSTRAINT %I', constraint_name);
  END IF;
END $$;

ALTER TABLE user_profiles
  ADD CONSTRAINT user_profiles_default_llm_provider_check
  CHECK (default_llm_provider IN ('groq', 'xai', 'openai', 'anthropic', 'deepseek'));

COMMENT ON COLUMN user_profiles.default_llm_provider IS
  'Default LLM provider for chat (groq, xai, openai, anthropic, deepseek)';

DO $$
DECLARE
  constraint_name text;
BEGIN
  SELECT conname INTO constraint_name
  FROM pg_constraint
  WHERE conrelid = 'user_api_keys'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%provider%'
  LIMIT 1;

  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE user_api_keys DROP CONSTRAINT %I', constraint_name);
  END IF;
END $$;

ALTER TABLE user_api_keys
  ADD CONSTRAINT user_api_keys_provider_check
  CHECK (provider IN ('groq', 'xai', 'openai', 'anthropic', 'deepseek'));

COMMENT ON TABLE user_api_keys IS
  'Encrypted user API keys for LLM providers (Groq, xAI, OpenAI, Anthropic, DeepSeek)';
