from pathlib import Path
from types import SimpleNamespace

from services.transcription_repository import TranscriptionRepository


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}
        self.operation = "select"
        self.payload = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _value):
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        matches = [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.operation == "update":
            for row in matches:
                row.update(self.payload)
        elif self.operation == "delete":
            for row in matches:
                self.rows.remove(row)
        return SimpleNamespace(data=matches)


class Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "jobs"
        return Query(self.rows)


def rows():
    return [
        {
            "id": "job-a",
            "user_id": "user-a",
            "video_hash": "shared-hash",
            "status": "completed",
            "filename": "a.mp4",
            "gcs_path": "users/user-a/a.mp4",
            "result_json": {"transcription": {"text": "private-a"}},
        },
        {
            "id": "job-b",
            "user_id": "user-b",
            "video_hash": "shared-hash",
            "status": "completed",
            "filename": "b.mp4",
            "gcs_path": "users/user-b/b.mp4",
            "result_json": {"transcription": {"text": "private-b"}},
        },
    ]


def test_reads_are_isolated_by_owner():
    repository = TranscriptionRepository(lambda: Client(rows()))

    result = repository.get_transcription("shared-hash", "user-b")

    assert result["transcription"]["text"] == "private-b"
    assert result["media_key"] == "users/user-b/b.mp4"
    assert repository.get_transcription("shared-hash", "unknown-user") is None


def test_update_and_delete_are_isolated_by_owner():
    records = rows()
    repository = TranscriptionRepository(lambda: Client(records))

    assert repository.update_transcription(
        "shared-hash",
        "user-a",
        {"transcription": {"text": "updated-a"}},
    )
    assert records[0]["result_json"]["transcription"]["text"] == "updated-a"
    assert records[1]["result_json"]["transcription"]["text"] == "private-b"

    assert repository.delete("shared-hash", "user-a")
    assert [record["user_id"] for record in records] == ["user-b"]


def test_local_mode_uses_the_same_supabase_repository(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    repository = TranscriptionRepository(lambda: Client(rows()))

    assert repository.get_transcription("shared-hash", "user-a") is not None


def test_media_key_lookup_is_owner_scoped():
    repository = TranscriptionRepository(lambda: Client(rows()))

    assert repository.get_job_by_media_key("users/user-a/a.mp4", "user-a")["id"] == "job-a"
    assert repository.get_job_by_media_key("users/user-a/a.mp4", "user-b") is None


def test_repository_does_not_fall_back_when_supabase_fails():
    def unavailable_client():
        raise RuntimeError("supabase unavailable")

    repository = TranscriptionRepository(unavailable_client)

    try:
        repository.get_transcription("hash", "user-a")
    except RuntimeError as exc:
        assert str(exc) == "supabase unavailable"
    else:
        raise AssertionError("repository must propagate persistence failures")


def test_legacy_persistence_symbols_are_absent():
    backend = Path(__file__).parents[1]
    assert not (backend / "database.py").exists()
    source = "\n".join(
        path.read_text(errors="ignore")
        for path in backend.rglob("*.py")
        if not {"local_data", "tests", "venv"}.intersection(path.parts)
    )
    for symbol in (
        "FirestoreBackend",
        "SQLiteBackend",
        "DATABASE_TYPE",
        "FIRESTORE_COLLECTION",
        "_last_transcription_data",
        "current_transcription",
    ):
        assert symbol not in source
