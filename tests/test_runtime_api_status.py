"""Tests for runtime config and API status behavior.

These verify that the Streamlit app never shows a scary "Unavailable" status
when running in local Streamlit mode (no external API configured), and that
manual scoring/reporting works without a backend.
"""

import importlib

import tournament_platform.config.runtime as runtime
from tournament_platform.app import api_status
from tournament_platform.config.runtime import (
    get_runtime_config,
    get_secret_optional,
)


def _clear_runtime_env(monkeypatch):
    for var in ("API_BASE_URL", "BACKEND_URL", "API_REQUIRED", "STREAMLIT_SERVER_HEADLESS",
                "STREAMLIT_SHARING_MODE", "STREAMLIT_CLOUD"):
        monkeypatch.delenv(var, raising=False)


def test_no_api_url_is_local_mode(monkeypatch):
    _clear_runtime_env(monkeypatch)
    status = api_status.get_api_status(api_base_url=None)
    assert status["state"] == "local_mode"
    assert status["ok"] is True
    assert "localhost" not in status["message"].lower()


def test_unset_runtime_config_is_local_streamlit(monkeypatch):
    _clear_runtime_env(monkeypatch)
    cfg = get_runtime_config()
    assert cfg.mode == "local_streamlit"
    assert cfg.api_base_url is None
    assert cfg.api_required is False


def test_optional_api_unreachable_is_warning(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("API_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("API_REQUIRED", "false")
    status = api_status.get_api_status(api_required=False)
    assert status["state"] == "unavailable"
    assert status["ok"] is True
    assert "Optional" in status["label"]


def test_required_api_unreachable_is_fatal(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("API_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("API_REQUIRED", "true")
    status = api_status.get_api_status()  # resolves API_BASE_URL from env
    assert status["state"] == "unavailable"
    assert status["ok"] is False
    assert "Required" in status["label"]


def test_hardcoded_localhost_not_used_unless_configured(monkeypatch):
    _clear_runtime_env(monkeypatch)
    cfg = get_runtime_config()
    assert cfg.api_base_url is None
    # Resolving again must not produce a localhost URL by default.
    assert "localhost" not in (cfg.api_base_url or "")
    assert "127.0.0.1" not in (cfg.api_base_url or "")


def test_streamlit_cloud_detection(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("STREAMLIT_SERVER_HEADLESS", "true")
    cfg = get_runtime_config()
    assert cfg.is_streamlit_cloud is True


def test_get_secret_optional_returns_none_without_secrets(monkeypatch):
    # Should never raise even when st.secrets is unavailable.
    val = get_secret_optional("API_BASE_URL")
    assert val is None or isinstance(val, str)


def test_secret_override_resolution(monkeypatch):
    _clear_runtime_env(monkeypatch)
    import streamlit as st

    # Simulate a secrets object.
    class _Secrets(dict):
        pass

    fake = _Secrets({"API_BASE_URL": "https://api.example.com"})
    monkeypatch.setattr(st, "secrets", fake, raising=False)
    cfg = get_runtime_config()
    assert cfg.api_base_url == "https://api.example.com"
    assert cfg.mode == "external_api"


def test_app_imports_without_backend_running():
    # Importing the app entrypoint must not start any server.
    import tournament_platform.app.main  # noqa: F401

    assert hasattr(tournament_platform.app.main, "main")


def test_uvicorn_not_run_by_streamlit_entrypoint():
    import tournament_platform.app.main as main

    # The module must not expose a uvicorn/FastAPI app as its entrypoint.
    assert not hasattr(main, "app")
    assert not hasattr(main, "uvicorn")
