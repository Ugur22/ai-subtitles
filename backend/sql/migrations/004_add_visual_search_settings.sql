-- Per-user visual search rewrite settings.
-- These let users keep domain-specific trigger terms and CLIP phrases in their
-- private profile instead of hardcoding them in the public application code.

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS visual_search_terms TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS visual_search_phrases TEXT DEFAULT '';

COMMENT ON COLUMN user_profiles.visual_search_terms IS
  'Private comma/newline-separated trigger terms for visual query rewriting.';

COMMENT ON COLUMN user_profiles.visual_search_phrases IS
  'Private newline-separated CLIP-friendly visual search phrases used when trigger terms match.';
