"""Ownership invariants, checked through the HTTP API of the real app (main.app).

User B (or a caller without a session) must not read or change user A's data, a
job without an owner belongs to nobody, and a normal user can't reach admin
routes. The real auth middleware, routers, JobQueueService and
TranscriptionRepository run unchanged; only the edges are faked: the Supabase
client singleton (an in-memory table store that records which rows each write
matched and every RPC), the media storage (no GCS; records the keys it signs or
deletes), the Supabase token check and the speaker voice-print store. Nothing
here reaches a network, a real database or production.

This file is add-only. The assertions are about outcomes (no data of theirs in
the response, no row of theirs changed, no key of theirs signed), not about how a
route gets there, so a route may move its ownership check into SQL or log an
audit row without breaking them. Exact status codes are pinned only where the
contract is 404 for a resource the caller does not own. Known gaps live in
tests/test_ownership_gaps.py, which reuses these fakes.
"""

import asyncio
import fnmatch
import re
import sys
import types
from types import SimpleNamespace

import httpx
import pytest

from config import settings
from services.media_storage import GCSMediaStorage

SHOTS = settings.GCS_SCREENSHOTS_PREFIX
A_SHOT = f"{SHOTS}user-a/hash-a/1.00.jpg"
ORPHAN_SHOT = f"{SHOTS}hash-orphan/1.00.jpg"
INTERNAL_KEY = "internal-test-key"

USERS = {
    "tok-user-a": "user-a",
    "tok-user-b": "user-b",
    "tok-admin": "admin",
}

# Strings that only exist in A's stored rows and storage keys. Request ids (hash-a, job-a)
# are deliberately absent: an error message may echo the id the caller sent.
A_SECRETS = (
    "A-SECRET",
    "a-secret-filename",
    "tok-share-a",
    "uploads/user-a",
    "processed/user-a",
    "screenshots/user-a",
)
ORPHAN_SECRETS = ("ORPHAN-SECRET", "tok-share-orphan", "processed/orphan", "uploads/orphan", ORPHAN_SHOT)
# Owners whose rows a caller other than themselves must never change. None is the ownerless job.
PROTECTED_OWNERS = ("user-a", None)


def _job(job_id, user_id, video_hash, status, secret, token, filename, media_key, shot=None):
    segment = {"start": 0.0, "end": 1.0, "text": f"{secret}-TEXT", "speaker": "SPEAKER_00"}
    if shot:
        segment["screenshot_url"] = shot
    return {
        "id": job_id,
        "user_id": user_id,
        "video_hash": video_hash,
        "status": status,
        "filename": filename,
        "file_size_bytes": 1234,
        "progress": 100 if status == "completed" else 10,
        "gcs_path": media_key,
        "access_token": token,
        "result_json": {
            "transcription": {"language": "en", "segments": [segment]},
            "gcs_path": media_key,
        },
        "result_srt": f"1\n00:00:00,000 --> 00:00:01,000\n{secret}-SRT\n",
        "result_vtt": f"WEBVTT\n\n00:00.000 --> 00:01.000\n{secret}-VTT\n",
        "created_at": "2026-01-01T00:00:00+00:00",
        "retry_count": 0,
    }


def _rows():
    return {
        "jobs": [
            _job("job-a", "user-a", "hash-a", "completed", "A-SECRET", "tok-share-a",
                 "a-secret-filename.mp4", "processed/user-a/a-secret-filename.mp4", A_SHOT),
            _job("job-a-failed", "user-a", "hash-a-failed", "failed", "A-SECRET", "tok-share-a-failed",
                 "a-secret-filename-failed.mp4", "uploads/user-a/failed.mp4"),
            _job("job-a-running", "user-a", "hash-a-running", "processing", "A-SECRET", "tok-share-a-running",
                 "a-secret-filename-running.mp4", "uploads/user-a/running.mp4"),
            _job("job-a-shared", "user-a", "hash-shared", "completed", "A-SECRET", "tok-share-a-shared",
                 "a-secret-filename-shared.mp4", "processed/user-a/shared.mp4"),
            _job("job-b", "user-b", "hash-b", "completed", "B-OWN", "tok-share-b",
                 "b-own.mp4", "processed/user-b/b-own.mp4", f"{SHOTS}user-b/hash-b/1.00.jpg"),
            _job("job-b-shared", "user-b", "hash-shared", "completed", "B-OWN", "tok-share-b-shared",
                 "b-own-shared.mp4", "processed/user-b/shared.mp4"),
            _job("job-orphan", None, "hash-orphan", "completed", "ORPHAN-SECRET", "tok-share-orphan",
                 "orphan.mp4", "processed/orphan/orphan.mp4", ORPHAN_SHOT),
            _job("job-orphan-failed", None, "hash-orphan-failed", "failed", "ORPHAN-SECRET",
                 "tok-share-orphan-failed", "orphan-failed.mp4", "uploads/orphan/failed.mp4"),
        ],
        "user_profiles": [
            {"id": uid, "email": f"{uid}@test", "email_verified": True, "is_admin": uid == "admin",
             "created_at": "2026-01-01T00:00:00+00:00"}
            for uid in USERS.values()
        ],
    }


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _sql_eq(left, right):
    """SQL comparison: NULL equals nothing, values compare as text like PostgREST filters."""
    return left is not None and right is not None and str(left) == str(right)


def _postgrest_value(raw):
    return None if raw == "null" else raw


def _split_top_level(text):
    parts, depth, current = [], 0, ""
    for char in text:
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        depth += char == "("
        depth -= char == ")"
        current += char
    return parts + [current] if current else parts


class FakeQuery:
    """The postgrest query builder surface the app uses, with SQL NULL semantics.

    Unknown methods raise AttributeError, which the routes turn into a 500 and the
    tests report. This file is add-only: to support a new builder method, add a new
    file under tests/invariants/ whose fixture subclasses FakeQuery/FakeSupabase,
    or ask the owner to extend this one; never weaken an assertion instead.
    """

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.payload = "select", None
        self.filters, self._limit, self._range, self._order = [], None, None, []
        self._single, self._negate_next = None, False

    # --- operations ---------------------------------------------------------
    def select(self, *_columns, count=None, **_kwargs):
        if self.op not in ("update", "delete", "insert", "upsert"):
            self.op = "select"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def insert(self, payload, **_kwargs):
        self.op, self.payload = "insert", payload
        return self

    def upsert(self, payload, **_kwargs):
        self.op, self.payload = "upsert", payload
        return self

    # --- filters ------------------------------------------------------------
    def _add(self, predicate):
        if self._negate_next:
            self._negate_next = False
            self.filters.append(lambda row: not predicate(row))
        else:
            self.filters.append(predicate)
        return self

    @property
    def not_(self):
        self._negate_next = True
        return self

    def eq(self, column, value):
        return self._add(lambda row: _sql_eq(row.get(column), value))

    def neq(self, column, value):
        return self._add(lambda row: row.get(column) is not None and not _sql_eq(row.get(column), value))

    def in_(self, column, values):
        values = [str(v) for v in values if v is not None]
        return self._add(lambda row: row.get(column) is not None and str(row.get(column)) in values)

    def is_(self, column, value):
        if isinstance(value, str):
            value = {"null": None, "true": True, "false": False}.get(value.lower(), value)
        expected = value
        return self._add(lambda row: row.get(column) is expected if expected in (None, True, False)
                         else row.get(column) == expected)

    def match(self, conditions):
        for column, value in conditions.items():
            self.eq(column, value)
        return self

    def _compare(self, column, value, test):
        return self._add(lambda row: row.get(column) is not None and test(str(row.get(column)), str(value)))

    def gt(self, column, value):
        return self._compare(column, value, lambda a, b: a > b)

    def gte(self, column, value):
        return self._compare(column, value, lambda a, b: a >= b)

    def lt(self, column, value):
        return self._compare(column, value, lambda a, b: a < b)

    def lte(self, column, value):
        return self._compare(column, value, lambda a, b: a <= b)

    def like(self, column, pattern):
        glob = pattern.replace("%", "*").replace("_", "?")
        return self._add(lambda row: row.get(column) is not None and fnmatch.fnmatchcase(str(row.get(column)), glob))

    def ilike(self, column, pattern):
        glob = pattern.replace("%", "*").replace("_", "?").lower()
        return self._add(lambda row: row.get(column) is not None
                         and fnmatch.fnmatchcase(str(row.get(column)).lower(), glob))

    def or_(self, expression, **_kwargs):
        """PostgREST or=(a.eq.1,b.is.null,c.in.(x,y)); supports eq, neq, is and in."""
        clauses = []
        for part in _split_top_level(expression):
            column, op, raw = part.split(".", 2)
            if op == "in":
                values = [v for v in raw.strip("()").split(",") if v]
                clauses.append(lambda row, c=column, vs=values: row.get(c) is not None and str(row.get(c)) in vs)
            elif op == "is":
                clauses.append(lambda row, c=column, v=_postgrest_value(raw): row.get(c) is v
                               if v is None else str(row.get(c)).lower() == v)
            elif op == "eq":
                clauses.append(lambda row, c=column, v=raw: _sql_eq(row.get(c), v))
            elif op == "neq":
                clauses.append(lambda row, c=column, v=raw: row.get(c) is not None and not _sql_eq(row.get(c), v))
            else:
                raise NotImplementedError(f"FakeQuery.or_ does not support '{op}' in {expression!r}")
        return self._add(lambda row: any(clause(row) for clause in clauses))

    # --- shaping ------------------------------------------------------------
    def order(self, column, desc=False, **_kwargs):
        self._order.append((column, desc))
        return self

    def limit(self, value, **_kwargs):
        self._limit = value
        return self

    def range(self, start, end, **_kwargs):
        self._range = (start, end)
        return self

    def single(self):
        self._single = "single"
        return self

    def maybe_single(self):
        self._single = "maybe"
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        matches = [row for row in rows if all(f(row) for f in self.filters)]

        if self.op in ("insert", "upsert"):
            new_rows = self.payload if isinstance(self.payload, list) else [self.payload]
            self.db.writes.append(SimpleNamespace(op=self.op, table=self.table, payload=self.payload,
                                                  matched=[], inserted=[dict(r) for r in new_rows]))
            rows.extend(dict(r) for r in new_rows)
            return SimpleNamespace(data=[dict(r) for r in new_rows], count=len(new_rows))
        if self.op in ("update", "delete"):
            self.db.writes.append(SimpleNamespace(op=self.op, table=self.table, payload=self.payload,
                                                  matched=[dict(r) for r in matches], inserted=[]))
            if self.op == "update":
                for row in matches:
                    row.update(self.payload)
            else:
                self.db.tables[self.table] = [row for row in rows if row not in matches]
            return SimpleNamespace(data=[dict(r) for r in matches], count=len(matches))

        for column, desc in reversed(self._order):
            matches.sort(key=lambda row: str(row.get(column) or ""), reverse=desc)
        total = len(matches)
        if self._range:
            matches = matches[self._range[0]: self._range[1] + 1]
        if self._limit is not None:
            matches = matches[: self._limit]
        data = [dict(r) for r in matches]
        if self._single:
            if len(data) != 1 and self._single == "single":
                raise RuntimeError(f"single() expected one row from {self.table}, got {len(data)}")
            data = data[0] if data else None
        return SimpleNamespace(data=data, count=total)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.writes = []
        self.rpcs = []

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params=None):
        self.rpcs.append((name, dict(params or {})))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=None))

    @property
    def auth(self):
        raise AssertionError("the data client's auth API must not be reached in these tests")


class FakeStorage(GCSMediaStorage):
    """Keeps the real key-ownership rules of the production adapter; no GCS calls."""

    def __init__(self, objects):
        self.objects = set(objects)
        self.signed = []
        self.deleted = []

    def file_exists(self, object_key):
        return object_key in self.objects

    def generate_download_url(self, object_key, expiry_seconds=None):
        self.signed.append(object_key)
        return f"https://signed.test/{object_key}?sig=fake"

    def parse_screenshot_key(self, reference):
        if reference and reference.startswith(SHOTS):
            return reference.split("?", 1)[0]
        return None

    def delete_file(self, object_key):
        self.deleted.append(object_key)
        return True

    def delete_screenshots(self, user_id, video_hash):
        self.deleted.append(f"{SHOTS}{user_id}/{video_hash}/")
        return True


class FakeVoicePrints:
    """Per-user enrolled speakers, keyed the way SpeakerRecognitionSystem is called."""

    def __init__(self):
        self.speakers = {"user-a": {"Alice": {"name": "Alice", "samples": 3}}}

    def list_speakers(self, user_id):
        return list(self.speakers.get(user_id, {}))

    def get_speaker_info(self, user_id, name):
        return self.speakers[user_id][name]

    def remove_speaker(self, user_id, name):
        return self.speakers.get(user_id, {}).pop(name, None) is not None

    def identify_speaker(self, *_args, **_kwargs):
        raise AssertionError("identify_speaker must not run for a transcription the caller does not own")


@pytest.fixture(scope="module")
def app():
    import main
    return main.app


@pytest.fixture
def world(monkeypatch):
    import middleware.auth as auth
    import services.job_queue_service as job_queue_service
    import services.media_storage as media_storage
    from services.supabase_service import SupabaseService

    db = FakeSupabase(_rows())
    storage = FakeStorage({
        "processed/user-a/a-secret-filename.mp4",
        "processed/user-b/b-own.mp4",
        "processed/orphan/orphan.mp4",
        A_SHOT,
        ORPHAN_SHOT,
    })
    voice_prints = FakeVoicePrints()

    async def verify(token):
        user_id = USERS.get(token)
        if not user_id:
            return None
        return {"id": user_id, "email": f"{user_id}@test", "email_confirmed_at": "2026-01-01T00:00:00Z"}

    async def no_refresh(_token):
        return None

    def no_auth_client(*_args, **_kwargs):
        raise AssertionError("Supabase Auth must not be reached in these tests")

    def no_worker(*_args, **_kwargs):
        raise AssertionError("the worker must not be dispatched in these tests")

    auth.clear_all_token_cache()
    monkeypatch.setattr(SupabaseService, "_client", db)
    monkeypatch.setattr(SupabaseService, "get_auth_client", classmethod(no_auth_client))
    monkeypatch.setattr(SupabaseService, "new_auth_client", classmethod(no_auth_client))
    monkeypatch.setattr(auth, "_verify_supabase_token_async", verify)
    monkeypatch.setattr(auth, "_refresh_supabase_session_async", no_refresh)
    monkeypatch.setattr(media_storage, "_media_storage", storage)
    monkeypatch.setattr(settings, "ENABLE_GCS_UPLOADS", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", INTERNAL_KEY)
    monkeypatch.setattr(job_queue_service.JobQueueService, "trigger_worker_job", staticmethod(no_worker))
    speaker_module = types.ModuleType("speaker_recognition")
    speaker_module.get_speaker_recognition_system = lambda: voice_prints
    monkeypatch.setitem(sys.modules, "speaker_recognition", speaker_module)
    yield SimpleNamespace(db=db, storage=storage, voice_prints=voice_prints)
    auth.clear_all_token_cache()


def call(app, method, path, cookie=None, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            if cookie:
                client.cookies.set("auth_token", cookie)
            return await client.request(method, path, follow_redirects=False, **kwargs)
    return asyncio.run(run())


def leaked(response, secrets):
    """The secrets that appear anywhere in the response the caller can read."""
    visible = response.text + " " + " ".join(f"{k}: {v}" for k, v in response.headers.items())
    return [secret for secret in secrets if secret in visible]


def _owner(row):
    return row["user_id"] if "user_id" in row else row.get("id")


def _is_protected_key(key):
    return "user-a" in key or "orphan" in key


def assert_nothing_of_theirs_touched(world, caller, secrets=A_SECRETS + ORPHAN_SECRETS):
    """No write, RPC or storage call reached a row or key the caller does not own.

    Writes and RPCs scoped to the caller's own id are allowed (an audit row, an
    owner-filtered SQL function that matches nothing).
    """
    for write in world.db.writes:
        touched = write.matched + write.inserted
        foreign = [r for r in touched if caller is None or _owner(r) != caller or _owner(r) in PROTECTED_OWNERS]
        assert foreign == [], f"{write.op} on {write.table} touched rows the caller does not own: {foreign}"
        assert [s for s in secrets + ("user-a",) if s in repr(write.payload)] == [], \
            f"{write.op} on {write.table} wrote another user's data: {write.payload!r}"
    for name, params in world.db.rpcs:
        owner_params = {k: v for k, v in params.items() if k.endswith("user_id")}
        assert caller is not None and owner_params and set(owner_params.values()) == {caller}, \
            f"RPC {name} was not scoped to the caller: {params}"
    assert [k for k in world.storage.signed if _is_protected_key(k)] == [], "signed another owner's media"
    assert [k for k in world.storage.deleted if _is_protected_key(k)] == [], "deleted another owner's media"


# ---------------------------------------------------------------------------
# A's job, seen by B or by a caller without a session
# ---------------------------------------------------------------------------

A_JOB_ROUTES = [
    pytest.param("GET", "/api/jobs/job-a", id="get"),
    pytest.param("DELETE", "/api/jobs/job-a-running", id="delete-cancel"),
    pytest.param("DELETE", "/api/jobs/job-a/permanent", id="delete-permanent"),
    pytest.param("POST", "/api/jobs/job-a-failed/retry", id="retry"),
    pytest.param("GET", "/api/jobs/job-a/share", id="share"),
    pytest.param("GET", "/api/jobs/job-a/download/srt", id="download-srt"),
    pytest.param("GET", "/api/jobs/job-a/download/json", id="download-json"),
    pytest.param("GET", "/api/jobs/job-a/download/srt?token=tok-share-b", id="download-with-b-token"),
    pytest.param("GET", "/api/jobs/job-a/video", id="video"),
    pytest.param("GET", "/api/jobs/job-a/video?token=tok-share-b", id="video-with-b-token"),
    pytest.param("GET", "/api/jobs/job-a/video_url", id="video-url"),
    pytest.param("GET", "/api/jobs/job-a/video_url?token=tok-share-b", id="video-url-with-b-token"),
    pytest.param("GET", f"/api/jobs/job-a/screenshot_url?gcs_path={A_SHOT}", id="screenshot-url"),
]
NON_OWNERS = [pytest.param("tok-user-b", id="b"), pytest.param(None, id="anonymous")]


@pytest.mark.parametrize("cookie", NON_OWNERS)
@pytest.mark.parametrize("method,path", A_JOB_ROUTES)
def test_non_owner_gets_none_of_a_jobs_data_and_changes_nothing(app, world, cookie, method, path):
    response = call(app, method, path, cookie=cookie)

    assert 400 <= response.status_code < 500, response.text
    assert leaked(response, A_SECRETS) == []
    assert_nothing_of_theirs_touched(world, USERS.get(cookie))


@pytest.mark.parametrize("method,path", [
    pytest.param("DELETE", "/api/jobs/job-a-running", id="delete-cancel"),
    pytest.param("DELETE", "/api/jobs/job-a/permanent", id="delete-permanent"),
    pytest.param("POST", "/api/jobs/job-a-failed/retry", id="retry"),
    pytest.param("GET", "/api/jobs/job-a/share", id="share"),
])
def test_b_gets_404_for_a_job(app, world, method, path):
    assert call(app, method, path, cookie="tok-user-b").status_code == 404


@pytest.mark.parametrize("path,expected", [
    ("/api/jobs/job-a", "A-SECRET-TEXT"),
    ("/api/jobs/job-a/share", "tok-share-a"),
    ("/api/jobs/job-a/video_url", "signed.test/processed/user-a"),
    (f"/api/jobs/job-a/screenshot_url?gcs_path={A_SHOT}", "signed.test/screenshots/user-a"),
    ("/api/jobs/job-a/download/srt?token=tok-share-a", "A-SECRET-SRT"),
])
def test_owner_control_a_reads_own_job(app, world, path, expected):
    """Proves the fakes are wired: the same requests succeed for the owner."""
    response = call(app, "GET", path, cookie="tok-user-a")

    assert response.status_code == 200, response.text
    assert expected in response.text


def test_owner_control_a_streams_own_video_with_share_token(app, world):
    response = call(app, "GET", "/api/jobs/job-a/video?token=tok-share-a")

    assert response.status_code == 302
    assert "processed/user-a" in response.headers["location"]


def test_b_cannot_sign_a_screenshot_through_bs_own_job(app, world):
    response = call(app, "GET", f"/api/jobs/job-b/screenshot_url?gcs_path={A_SHOT}", cookie="tok-user-b")

    assert 400 <= response.status_code < 500
    assert leaked(response, A_SECRETS) == []
    assert_nothing_of_theirs_touched(world, "user-b")


def test_b_job_list_contains_only_bs_jobs(app, world):
    response = call(app, "GET", "/api/jobs?tokens=tok-share-a", cookie="tok-user-b")

    assert response.status_code == 200, response.text
    assert {job["job_id"] for job in response.json()["jobs"]} == {"job-b", "job-b-shared"}
    assert leaked(response, A_SECRETS) == []


# ---------------------------------------------------------------------------
# A's transcription, screenshots and speakers
# ---------------------------------------------------------------------------

RENAME = {"original_speaker": "SPEAKER_00", "new_speaker_name": "Mallory"}
A_TRANSCRIPTION_ROUTES = [
    pytest.param("GET", "/transcription/hash-a", None, id="get-transcription"),
    pytest.param("DELETE", "/api/transcription/hash-a", None, id="delete-transcription"),
    pytest.param("GET", "/api/video/hash-a", None, id="video-by-hash"),
    pytest.param("GET", "/api/subtitles/nl?video_hash=hash-a", None, id="subtitles"),
    pytest.param("POST", "/api/speaker/transcription/hash-a/speaker", RENAME, id="rename-speaker"),
    pytest.param("POST", "/api/speaker/transcription/hash-a/auto_identify_speakers", None, id="auto-identify"),
]


@pytest.mark.parametrize("cookie", NON_OWNERS)
@pytest.mark.parametrize("method,path,body", A_TRANSCRIPTION_ROUTES)
def test_non_owner_gets_none_of_a_transcription_and_changes_nothing(app, world, cookie, method, path, body):
    response = call(app, method, path, cookie=cookie, json=body)

    assert 400 <= response.status_code < 500, response.text
    assert leaked(response, A_SECRETS) == []
    assert_nothing_of_theirs_touched(world, USERS.get(cookie))
    a_job = next(row for row in world.db.tables["jobs"] if row["id"] == "job-a")
    assert a_job["result_json"]["transcription"]["segments"][0]["speaker"] == "SPEAKER_00"


@pytest.mark.parametrize("method,path,body", A_TRANSCRIPTION_ROUTES)
def test_b_gets_404_for_a_transcription(app, world, method, path, body):
    assert call(app, method, path, cookie="tok-user-b", json=body).status_code == 404


@pytest.mark.parametrize("path,expected", [
    ("/transcription/hash-a", "A-SECRET-TEXT"),
    ("/api/subtitles/nl?video_hash=hash-a", "A-SECRET-TEXT"),
])
def test_owner_control_a_reads_own_transcription(app, world, path, expected):
    response = call(app, "GET", path, cookie="tok-user-a")

    assert response.status_code == 200, response.text
    assert expected in response.text


def test_owner_control_a_streams_own_video_by_hash(app, world):
    response = call(app, "GET", "/api/video/hash-a", cookie="tok-user-a")

    assert 300 <= response.status_code < 400, response.text
    assert "processed/user-a" in response.headers["location"]


def test_owner_control_a_transcription_screenshot_url_is_signed(app, world):
    response = call(app, "GET", "/transcription/hash-a", cookie="tok-user-a")

    segment = response.json()["transcription"]["segments"][0]
    assert segment["screenshot_url"] == f"https://signed.test/{A_SHOT}?sig=fake"


def test_same_file_uploaded_by_both_users_returns_each_their_own(app, world):
    response = call(app, "GET", "/transcription/hash-shared", cookie="tok-user-b")

    assert response.status_code == 200, response.text
    assert "B-OWN-TEXT" in response.text
    assert leaked(response, A_SECRETS) == []


def test_b_speaker_rename_on_shared_hash_changes_only_bs_job(app, world):
    response = call(app, "POST", "/api/speaker/transcription/hash-shared/speaker",
                    cookie="tok-user-b", json=RENAME)

    assert response.status_code == 200, response.text
    speakers = {row["id"]: row["result_json"]["transcription"]["segments"][0]["speaker"]
                for row in world.db.tables["jobs"]}
    assert speakers["job-b-shared"] == "Mallory"
    assert speakers["job-a-shared"] == "SPEAKER_00"
    assert_nothing_of_theirs_touched(world, "user-b")


def test_b_cannot_list_or_remove_a_enrolled_speakers(app, world):
    listing = call(app, "GET", "/api/speaker/list", cookie="tok-user-b")
    removal = call(app, "DELETE", "/api/speaker/Alice", cookie="tok-user-b")

    assert listing.status_code == 200 and listing.json()["count"] == 0
    assert leaked(listing, ("Alice",)) == []
    assert 400 <= removal.status_code < 500
    assert "Alice" in world.voice_prints.speakers["user-a"]


# ---------------------------------------------------------------------------
# A job without an owner belongs to nobody
# ---------------------------------------------------------------------------

ORPHAN_ROUTES = [
    pytest.param("GET", "/api/jobs/job-orphan", None, id="get"),
    pytest.param("DELETE", "/api/jobs/job-orphan", None, id="delete-cancel"),
    pytest.param("DELETE", "/api/jobs/job-orphan/permanent", None, id="delete-permanent"),
    pytest.param("POST", "/api/jobs/job-orphan-failed/retry", None, id="retry"),
    pytest.param("GET", "/api/jobs/job-orphan/share", None, id="share"),
    pytest.param("GET", "/api/jobs/job-orphan/video_url", None, id="video-url"),
    pytest.param("GET", f"/api/jobs/job-orphan/screenshot_url?gcs_path={ORPHAN_SHOT}", None, id="screenshot-url"),
    pytest.param("GET", "/transcription/hash-orphan", None, id="get-transcription"),
    pytest.param("DELETE", "/api/transcription/hash-orphan", None, id="delete-transcription"),
    pytest.param("GET", "/api/video/hash-orphan", None, id="video-by-hash"),
    pytest.param("POST", "/api/speaker/transcription/hash-orphan/speaker", RENAME, id="rename-speaker"),
]


@pytest.mark.parametrize("cookie", [
    pytest.param("tok-user-a", id="a"),
    pytest.param("tok-user-b", id="b"),
    pytest.param("tok-admin", id="admin"),
    pytest.param(None, id="anonymous"),
])
@pytest.mark.parametrize("method,path,body", ORPHAN_ROUTES)
def test_ownerless_job_is_no_access_for_every_caller(app, world, cookie, method, path, body):
    """Through a session, nobody can read or change a job whose owner is null.

    The share-token routes (/download, /video) are not listed: without a token they stop
    before looking at the job. Share-token access to ownerless jobs is a tracked gap in
    tests/test_ownership_gaps.py, not a guarantee of this file.
    """
    response = call(app, method, path, cookie=cookie, json=body)

    assert 400 <= response.status_code < 500, response.text
    assert leaked(response, ORPHAN_SECRETS) == []
    assert_nothing_of_theirs_touched(world, USERS.get(cookie))


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

GUESSES = {"user_id": "user-a", "job_id": "job-a", "video_hash": "hash-a"}
PATH_PARAM = re.compile(r"\{(\w+)(?::\w+)?\}")


def _admin_routes(app):
    """Routes under /api/admin plus any other route wrapped by require_admin."""
    import middleware.auth as auth

    def handler(request):
        return None

    admin_code = auth.require_admin(handler).__code__
    found = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if not (route.path.startswith("/api/admin") or getattr(endpoint, "__code__", None) is admin_code):
            continue
        path = PATH_PARAM.sub(lambda m: GUESSES.get(m.group(1), "guessed-id"), route.path)
        for method in sorted((getattr(route, "methods", None) or set()) - {"HEAD"}):
            found.append((method, path))
    return found


def test_admin_routes_are_found(app):
    routes = _admin_routes(app)
    assert len(routes) >= 3
    assert ("DELETE", "/api/admin/users/user-a") in routes


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "guessed-key"}], ids=["session", "guessed-internal-key"])
def test_normal_user_cannot_reach_any_admin_route(app, world, headers):
    reached = {}
    for method, path in _admin_routes(app):
        response = call(app, method, path, cookie="tok-user-b", headers=headers,
                        json={} if method in ("POST", "PUT", "PATCH") else None)
        if not 400 <= response.status_code < 500 or leaked(response, A_SECRETS + ("user-a@test",)):
            reached[f"{method} {path}"] = (response.status_code, response.text[:200])

    assert reached == {}
    assert_nothing_of_theirs_touched(world, "user-b")
    assert {row["id"] for row in world.db.tables["user_profiles"]} == set(USERS.values())


def test_admin_control_admin_session_reaches_admin_users(app, world):
    response = call(app, "GET", "/api/admin/users", cookie="tok-admin")

    assert response.status_code == 200, response.text
    assert "user-a@test" in response.text


def test_admin_control_correct_internal_key_reaches_admin_stats(app, world):
    response = call(app, "GET", "/api/admin/stats", headers={"X-Internal-Key": INTERNAL_KEY})

    assert response.status_code == 200, response.text
    assert response.json()["total_users"] == len(USERS)
