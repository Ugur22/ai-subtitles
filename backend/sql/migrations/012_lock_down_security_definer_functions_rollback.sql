-- ========================================
-- Rollback: Lock Down SECURITY DEFINER Functions & face_tags RLS
-- ========================================
-- Reverts 012_lock_down_security_definer_functions.sql
-- ========================================

-- Restore default PUBLIC EXECUTE grants
GRANT EXECUTE ON FUNCTION get_vault_secret(TEXT) TO PUBLIC;
GRANT EXECUTE ON FUNCTION cleanup_expired_codes() TO PUBLIC;
GRANT EXECUTE ON FUNCTION is_invite_code_valid(UUID) TO PUBLIC;
GRANT EXECUTE ON FUNCTION use_invite_code(UUID, UUID) TO PUBLIC;

-- Restore permissive face_tags policies
CREATE POLICY "Allow insert face tags" ON face_tags
  FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow update face tags" ON face_tags
  FOR UPDATE USING (true);

CREATE POLICY "Allow delete face tags" ON face_tags
  FOR DELETE USING (true);
