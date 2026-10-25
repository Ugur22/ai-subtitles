import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from middleware.csrf import CSRFProtectionMiddleware

ALLOWED = "https://app.example.com"


class Payload(BaseModel):
    value: str = ""


class _Client:
    """Sends requests straight to the ASGI app (Starlette's TestClient needs an older httpx)."""

    def __init__(self, app):
        self.app = app

    def request(self, method, url, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(send())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def options(self, url, **kwargs):
        return self.request("OPTIONS", url, **kwargs)


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/read")
    def read():
        return {"ok": True}

    @app.post("/write")
    def write(payload: Payload):
        return {"value": payload.value}

    @app.post("/empty")
    def empty():
        return {"ok": True}

    @app.delete("/remove")
    def remove():
        return {"ok": True}

    # Same order as main.py: CSRF inside CORS.
    app.add_middleware(CSRFProtectionMiddleware, allowed_origins=[ALLOWED + "/"])
    app.add_middleware(CORSMiddleware, allow_origins=[ALLOWED], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    return _Client(app)


JSON = {"Content-Type": "application/json"}


def test_post_from_unlisted_origin_is_refused(client):
    response = client.post("/write", json={"value": "x"}, headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_null_origin_is_refused(client):
    assert client.post("/write", json={"value": "x"}, headers={"Origin": "null"}).status_code == 403


def test_delete_from_unlisted_origin_is_refused(client):
    assert client.delete("/remove", headers={"Origin": "https://evil.example"}).status_code == 403


def test_listed_origin_passes_whatever_the_case_or_trailing_slash(client):
    for origin in (ALLOWED, ALLOWED.upper(), ALLOWED + "/"):
        response = client.post("/write", json={"value": "x"}, headers={"Origin": origin})
        assert response.status_code == 200


def test_request_without_origin_is_unaffected(client):
    assert client.post("/write", json={"value": "x"}).status_code == 200


def test_same_host_origin_is_allowed(client):
    assert client.post("/write", json={"value": "x"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_safe_methods_are_never_checked(client):
    assert client.get("/read", headers={"Origin": "https://evil.example"}).status_code == 200


def test_body_without_content_type_is_refused(client):
    response = client.post("/write", content=b'{"value": "x"}')

    assert response.status_code == 415


def test_body_without_content_type_is_refused_even_from_a_listed_origin(client):
    response = client.post("/write", content=b'{"value": "x"}', headers={"Origin": ALLOWED})

    assert response.status_code == 415


def test_json_body_with_content_type_passes(client):
    assert client.post("/write", content=b'{"value": "x"}', headers=JSON).json() == {"value": "x"}


def test_empty_post_without_content_type_passes(client):
    assert client.post("/empty").status_code == 200


def test_preflight_from_listed_origin_is_answered_and_not_blocked(client):
    response = client.options(
        "/write",
        headers={"Origin": ALLOWED, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
