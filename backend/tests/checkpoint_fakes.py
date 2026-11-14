"""Shared in-memory fakes for checkpoint tests."""


class FakeCache:
    """In-memory stand-in for PipelineCacheService, keyed like the real table."""

    def __init__(self):
        self.rows = {}
        self.fail_saves = False

    def get_cached_prefix(self, user_id, video_hash, prefix):
        return {
            stage: data for (owner, media, stage), data in self.rows.items()
            if owner == user_id and media == video_hash and stage.startswith(prefix)
        }

    def save_cache(self, user_id, video_hash, stage, data):
        if self.fail_saves:
            return False
        self.rows[(user_id, video_hash, stage)] = data
        return True

    def clear_prefix(self, user_id, video_hash, prefix):
        doomed = [
            key for key in self.rows
            if key[0] == user_id and key[1] == video_hash and key[2].startswith(prefix)
        ]
        for key in doomed:
            del self.rows[key]
        return len(doomed)
