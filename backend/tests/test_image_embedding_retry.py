import httpx
import pytest

from services import image_embedding_service as image_module

RETRY_HELPERS = [
    ("_upsert_with_retry", "image_embeddings", "upsert"),
    ("_insert_face_presence_with_retry", "image_face_presence", "insert"),
]


class _Session:
    closed = False

    def close(self):
        self.closed = True


class _Query:
    def __init__(self, failures):
        self._failures = failures

    def execute(self):
        if self._failures:
            raise self._failures.pop(0)


class _Table:
    def __init__(self, failures):
        self._failures = failures

    def upsert(self, *_args, **_kwargs):
        return _Query(self._failures)

    def insert(self, *_args, **_kwargs):
        return _Query(self._failures)


class _Client:
    def __init__(self, failures):
        self.postgrest = type("Postgrest", (), {"session": _Session()})()
        self._failures = failures
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return _Table(self._failures)


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    monkeypatch.setattr(image_module.time, "sleep", lambda _seconds: None)


@pytest.mark.parametrize("helper_name,table,_op", RETRY_HELPERS)
def test_transient_disconnect_retries_without_closing_shared_client(helper_name, table, _op):
    client = _Client([httpx.RemoteProtocolError("Server disconnected")])
    helper = getattr(image_module.ImageEmbeddingService, helper_name)

    helper(object(), client, [{"id": 1}], 1, 1)

    assert client.tables == [table, table]
    assert client.postgrest.session.closed is False


@pytest.mark.parametrize("helper_name,_table,_op", RETRY_HELPERS)
def test_exhausted_retries_raise_last_error_and_leave_client_open(helper_name, _table, _op):
    errors = [httpx.ReadError(f"boom {i}") for i in range(3)]
    client = _Client(list(errors))
    helper = getattr(image_module.ImageEmbeddingService, helper_name)

    with pytest.raises(httpx.ReadError) as raised:
        helper(object(), client, [{"id": 1}], 1, 1)

    assert raised.value is errors[-1]
    assert client.postgrest.session.closed is False
