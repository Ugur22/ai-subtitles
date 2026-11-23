import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import keys


class _Query:
    def __init__(self, table):
        self.table = table
        self.filters = {}
        self.pending = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def insert(self, row):
        self.pending = ("insert", row)
        return self

    def update(self, fields):
        self.pending = ("update", fields)
        return self

    def execute(self):
        matches = [
            row for row in self.table.rows
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.pending is None:
            return SimpleNamespace(data=matches)
        op, payload = self.pending
        self.table.writes.append(op)
        if op == "insert":
            self.table.rows.append(dict(payload))
            return SimpleNamespace(data=[payload])
        for row in matches:
            row.update(payload)
        return SimpleNamespace(data=matches)


class _Table:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []


class _Client:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "user_api_keys"
        return _Query(self._table)


def _setup(monkeypatch, rows, verdict):
    table = _Table(rows)
    monkeypatch.setattr(keys.SupabaseService, "get_client", staticmethod(lambda: _Client(table)))

    async def fake_encryption_key():
        return b"k" * 32

    async def fake_test(_provider, _api_key):
        return verdict

    monkeypatch.setattr(keys, "get_encryption_key", fake_encryption_key)
    monkeypatch.setattr(keys, "encrypt_api_key", lambda key, _enc: f"enc:{key}")
    monkeypatch.setattr(keys, "test_provider_key", fake_test)
    return table


def _add(provider, api_key):
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-1"}))
    body = keys.AddKeyRequest(provider=provider, api_key=api_key)
    return asyncio.run(keys.add_key.__wrapped__(request, body))


def test_invalid_key_is_rejected_and_not_saved(monkeypatch):
    table = _setup(monkeypatch, [], (False, "Invalid API key"))

    with pytest.raises(HTTPException) as excinfo:
        _add("openai", "sk-wrong")

    assert excinfo.value.status_code == 400
    assert "Invalid API key" in excinfo.value.detail
    assert table.rows == []
    assert table.writes == []


def test_valid_key_is_saved_as_valid(monkeypatch):
    table = _setup(monkeypatch, [], (True, None))

    _add("openai", "sk-good-1234")

    assert len(table.rows) == 1
    row = table.rows[0]
    assert row["is_valid"] is True
    assert row["encrypted_key"] == "enc:sk-good-1234"
    assert row["validated_at"]


def test_invalid_replacement_keeps_existing_working_key(monkeypatch):
    existing = {
        "id": "row-1",
        "user_id": "user-1",
        "provider": "xai",
        "encrypted_key": "enc:old-good",
        "is_valid": True,
    }
    table = _setup(monkeypatch, [existing], (False, "Invalid API key"))

    with pytest.raises(HTTPException):
        _add("xai", "xai-wrong")

    assert table.rows == [existing]
    assert existing["encrypted_key"] == "enc:old-good"
    assert table.writes == []
