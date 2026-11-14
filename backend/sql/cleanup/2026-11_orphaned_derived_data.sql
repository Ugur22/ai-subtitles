-- One-off: remove derived data whose (user_id, video_hash) no longer has a job.
-- Left behind by job deletes before migration 020. Run manually, section by
-- section: preview first, then the delete.
--
-- Expected on 2026-11-15: 31,758 image_embeddings rows for 39 legacy 32-char
-- hashes (2026-03-05..06-14), cascading to image_face_presence and
-- image_caption_sentences; every other table 0. Their legacy
-- screenshots/{hash}/ folders are past the bucket's 30-day lifecycle already.

-- 1. Preview
WITH live AS (
  SELECT DISTINCT user_id, video_hash FROM jobs WHERE video_hash IS NOT NULL
), derived AS (
  SELECT 'pipeline_cache' AS t, user_id, video_hash FROM pipeline_cache
  UNION ALL SELECT 'transcript_embeddings', user_id, video_hash FROM transcript_embeddings
  UNION ALL SELECT 'transcript_embeddings_v2', user_id, video_hash FROM transcript_embeddings_v2
  UNION ALL SELECT 'audio_event_embeddings', user_id, video_hash FROM audio_event_embeddings
  UNION ALL SELECT 'audio_event_embeddings_v2', user_id, video_hash FROM audio_event_embeddings_v2
  UNION ALL SELECT 'image_embeddings', user_id, video_hash FROM image_embeddings
  UNION ALL SELECT 'face_tags', user_id, video_hash FROM face_tags
)
SELECT t, count(*) AS orphan_rows, count(DISTINCT video_hash) AS videos
FROM derived d
WHERE NOT EXISTS (
  SELECT 1 FROM live l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash
)
GROUP BY t ORDER BY t;

-- 2. Delete
BEGIN;

CREATE TEMP TABLE live_videos ON COMMIT DROP AS
  SELECT DISTINCT user_id, video_hash FROM jobs WHERE video_hash IS NOT NULL;

DELETE FROM pipeline_cache d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);
DELETE FROM transcript_embeddings d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);
DELETE FROM transcript_embeddings_v2 d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);
DELETE FROM audio_event_embeddings d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);
DELETE FROM audio_event_embeddings_v2 d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);
-- Cascades to image_caption_sentences and image_face_presence.
DELETE FROM image_embeddings d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);
DELETE FROM face_tags d WHERE NOT EXISTS (
  SELECT 1 FROM live_videos l WHERE l.user_id = d.user_id AND l.video_hash = d.video_hash);

COMMIT;
