import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import auth_new


class _FakeSupabase:
    """Just enough of the Supabase client for register(), with an atomic use_invite_code."""

    def __init__(self, rpc_error=None):
        self.profiles = {}
        self.auth_users = set()
        self.invite_used_by = None
        self.rpc_error = rpc_error
        self.next_id = 0

    def new_auth_user(self):
        self.next_id += 1
        user_id = f"user-{self.next_id}"
        self.auth_users.add(user_id)
        return user_id

    def table(self, name):
        assert name == "user_profiles"
        return _Profiles(self)

    def rpc(self, name, params):
        assert name == "use_invite_code"
        db = self

        class _Call:
            def execute(self_inner):
                if db.rpc_error:
                    raise db.rpc_error
                if db.invite_used_by is None:
                    db.invite_used_by = params["user_id_input"]
                    return SimpleNamespace(data=True)
                return SimpleNamespace(data=False)

        return _Call()

    @property
    def auth(self):
        db = self
        return SimpleNamespace(
            sign_up=lambda _payload: SimpleNamespace(user=SimpleNamespace(id=db.new_auth_user())),
            admin=SimpleNamespace(delete_user=lambda user_id: db.auth_users.discard(user_id)),
        )


class _Profiles:
    def __init__(self, db):
        self.db = db
        self.op = None
        self.filters = {}
        self.row = None

    def select(self, _columns):
        self.op = "select"
        return self

    def insert(self, row):
        self.op = "insert"
        self.row = row
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        profiles = self.db.profiles
        if self.op == "insert":
            profiles[self.row["id"]] = self.row
            return SimpleNamespace(data=[self.row])
        matches = [
            row for row in profiles.values()
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.op == "delete":
            for row in matches:
                profiles.pop(row["id"])
        return SimpleNamespace(data=matches)


@pytest.fixture
def db(monkeypatch):
    fake = _FakeSupabase()
    monkeypatch.setattr(auth_new.SupabaseService, "get_client", staticmethod(lambda: fake))
    monkeypatch.setattr(auth_new.SupabaseService, "get_auth_client", staticmethod(lambda: fake))
    monkeypatch.setattr(auth_new.SupabaseService, "new_auth_client", staticmethod(lambda: fake))
    # Both registrations have already passed the early check before either
    # claims the code, which is the window the atomic claim has to close.
    monkeypatch.setattr(auth_new, "_verify_invite_code", lambda _code: True)
    return fake


def _register(email):
    request = auth_new.RegisterRequest(email=email, password="correct-horse-battery", invite_code="code-1")
    return asyncio.run(auth_new.register(request))


def test_only_one_of_two_registrations_keeps_the_invite_code(db):
    winner = _register("first@example.com")

    with pytest.raises(HTTPException) as exc:
        _register("second@example.com")

    assert exc.value.status_code == 400
    assert db.invite_used_by == winner.user_id
    assert list(db.profiles) == [winner.user_id]
    assert db.auth_users == {winner.user_id}


def test_failed_claim_rolls_the_registration_back(monkeypatch, db):
    db.rpc_error = RuntimeError("rpc unavailable")

    with pytest.raises(HTTPException) as exc:
        _register("first@example.com")

    assert exc.value.status_code == 400
    assert db.profiles == {}
    assert db.auth_users == set()
    assert db.invite_used_by is None
