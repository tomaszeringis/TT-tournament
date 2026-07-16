"""
Smoke tests for the FastAPI Ollama bridge and the Streamlit client/bridge facade.

These verify:
* ``/health`` returns OK.
* ``/ollama/status`` returns ``available=false`` (HTTP 200) when Ollama is down,
  and ``available=true`` when Ollama is reachable -- FastAPI must not crash.
* ``/ollama/generate`` works and returns a clean payload.
* ``/ollama/generate`` returns HTTP 401 with an invalid/missing bearer token when
  ``API_TOKEN`` is set.
* The Streamlit ``ApiClient`` sends the bearer token and does not call localhost
  when running on Streamlit Cloud.
* The ``ollama_bridge`` facade falls back gracefully when the API is unavailable.
"""

import importlib
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    """Build a FastAPI TestClient with a clean token env."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    # Reload the server module so module-level token/URL are re-read from env.
    import tournament_platform.api.server as server

    importlib.reload(server)
    from fastapi.testclient import TestClient

    return TestClient(server.app), server


def _fake_async_client(get_response=None, post_response=None, capture=None):
    """Build a lightweight async context manager mimicking httpx.AsyncClient.

    If ``capture`` is a dict, the JSON payload of the most recent POST request
    is stored under ``capture["post"]`` and GET under ``capture["get"]``.
    """

    class _Fake:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **k):
            if capture is not None:
                capture["get"] = k.get("json")
            if isinstance(get_response, Exception):
                raise get_response
            return get_response

        async def post(self, url, **k):
            if capture is not None:
                capture["post"] = k.get("json")
            if isinstance(post_response, Exception):
                raise post_response
            return post_response

    return _Fake()


def test_health_ok(client):
    test_client, _ = client
    resp = test_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_ollama_status_unavailable_when_down(client):
    """Ollama down -> available=false, HTTP 200 (never crash)."""
    test_client, server = client
    with patch.object(server, "OLLAMA_BASE_URL", "http://127.0.0.1:39999"):
        resp = test_client.get("/ollama/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "error" in body


def test_ollama_status_available_when_up(client):
    """Ollama up -> available=true with model list."""
    test_client, server = client
    fake = MagicMock()
    fake.json.return_value = {"models": [{"name": "llama3.1:8b"}, {"name": "nomic-embed-text"}]}
    fake.raise_for_status = MagicMock()

    import httpx

    with patch.object(httpx, "AsyncClient", return_value=_fake_async_client(get_response=fake)):
        resp = test_client.get("/ollama/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert "llama3.1:8b" in body["models"]


def test_ollama_generate_works(client):
    """Generate returns a clean payload when Ollama responds."""
    test_client, server = client
    fake = MagicMock()
    fake.json.return_value = {"model": "llama3.1:8b", "response": "Hello from Ollama"}
    fake.raise_for_status = MagicMock()

    import httpx

    capture = {}
    with patch.object(httpx, "AsyncClient", return_value=_fake_async_client(post_response=fake, capture=capture)):
        resp = test_client.post(
            "/ollama/generate",
            json={"prompt": "hi", "model": "llama3.1:8b"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["response"] == "Hello from Ollama"
    # Verify Ollama received stream=false.
    assert capture["post"]["stream"] is False


def test_ollama_generate_bad_ollama_returns_ok_false(client):
    """Ollama error -> ok=false, HTTP 200 (no 5xx crash)."""
    test_client, server = client

    import httpx

    with patch.object(httpx, "AsyncClient", return_value=_fake_async_client(post_response=httpx.HTTPError("boom"))):
        resp = test_client.post("/ollama/generate", json={"prompt": "hi"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_ollama_endpoints_require_token_when_set(client, monkeypatch):
    """When API_TOKEN is set, /ollama/* returns 401 without a valid token."""
    import os

    monkeypatch.setenv("API_TOKEN", "secret-123")
    import importlib as _il

    import tournament_platform.api.server as server

    _il.reload(server)
    from fastapi.testclient import TestClient

    test_client = TestClient(server.app)

    # No token.
    assert test_client.get("/ollama/status").status_code == 401
    # Wrong token.
    assert test_client.get(
        "/ollama/status", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    # Correct token.
    assert test_client.get(
        "/ollama/status", headers={"Authorization": "Bearer secret-123"}
    ).status_code == 200


def test_ollama_chat_works(client):
    test_client, server = client
    fake = MagicMock()
    fake.json.return_value = {
        "model": "llama3.1:8b",
        "message": {"role": "assistant", "content": "hi there"},
    }
    fake.raise_for_status = MagicMock()

    import httpx

    with patch.object(httpx, "AsyncClient", return_value=_fake_async_client(post_response=fake)):
        resp = test_client.post(
            "/ollama/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["message"] == "hi there"


def test_client_sends_bearer_token(monkeypatch):
    """ApiClient.ollama_generate sends the bearer token from API_TOKEN."""
    monkeypatch.setenv("API_TOKEN", "tok-xyz")
    import importlib as _il

    import tournament_platform.app.api_client as ac

    _il.reload(ac)
    from tournament_platform.app.api_client import ApiClient

    with patch("tournament_platform.app.api_client.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "response": "x", "model": "m"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = ApiClient(base_url="https://api.example.com")
        client.ollama_generate(prompt="hi")

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok-xyz"
        assert "/ollama/generate" in mock_post.call_args.args[0]


def test_client_never_calls_localhost_on_cloud(monkeypatch):
    """On Streamlit Cloud, ollama_generate returns None for an unreachable API."""
    monkeypatch.setenv("API_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("STREAMLIT_SERVER_HEADLESS", "true")
    monkeypatch.delenv("API_TOKEN", raising=False)
    import importlib as _il
    import requests

    import tournament_platform.config.runtime as runtime
    import tournament_platform.app.api_client as ac

    _il.reload(runtime)
    _il.reload(ac)

    from tournament_platform.app.api_client import ApiClient

    with patch("tournament_platform.app.api_client.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError()

        client = ApiClient(base_url="https://api.example.com")
        # Unreachable API on Cloud -> graceful None (no localhost fallback).
        assert client.ollama_generate(prompt="hi") is None


def test_bridge_fallback_when_api_unavailable(monkeypatch):
    """ollama_bridge.generate falls back to local Ollama when API is down locally."""
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("STREAMLIT_SERVER_HEADLESS", raising=False)
    import importlib as _il

    import tournament_platform.config.runtime as runtime
    import tournament_platform.app.services.ollama_bridge as bridge

    _il.reload(runtime)
    _il.reload(bridge)

    fake_ollama = MagicMock()
    fake_ollama.generate.return_value = {
        "model": "llama3.1:8b",
        "response": "local response",
    }
    with patch.dict("sys.modules", {"ollama": fake_ollama}):
        result = bridge.generate(prompt="hi")

    assert result is not None
    assert result["ok"] is True
    assert result["response"] == "local response"


def test_bridge_uses_api_when_connected(monkeypatch):
    """ollama_bridge.generate uses the API bridge when connected."""
    monkeypatch.setenv("API_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("STREAMLIT_SERVER_HEADLESS", raising=False)
    import importlib as _il

    import tournament_platform.config.runtime as runtime
    import tournament_platform.app.api_client as ac
    import tournament_platform.app.api_status as api_status_mod
    import tournament_platform.app.services.ollama_bridge as bridge

    _il.reload(runtime)
    _il.reload(ac)
    _il.reload(api_status_mod)
    _il.reload(bridge)

    with patch.object(api_status_mod, "get_api_status", return_value={"state": "connected"}):
        with patch.object(ac.api_client, "ollama_generate", return_value={"ok": True, "response": "via api"}) as mock_gen:
            result = bridge.generate(prompt="hi")

    assert result == {"ok": True, "response": "via api"}
    mock_gen.assert_called_once()


def test_app_uses_local_mode_without_api(monkeypatch):
    """Without API_BASE_URL the runtime mode is local_streamlit."""
    monkeypatch.delenv("API_BASE_URL", raising=False)
    import importlib as _il

    import tournament_platform.config.runtime as runtime

    _il.reload(runtime)
    cfg = runtime.get_runtime_config()
    assert cfg.mode == "local_streamlit"
    assert isinstance(cfg.ollama_model, str) and cfg.ollama_model
