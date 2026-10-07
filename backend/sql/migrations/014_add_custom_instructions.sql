-- Persist the chat "Custom Instructions" box per user so a new chat starts with them filled in.

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS custom_instructions TEXT DEFAULT '';

COMMENT ON COLUMN user_profiles.custom_instructions IS
  'Private chat style/format instructions applied to every chat question (max 4000 chars, enforced by the API).';
