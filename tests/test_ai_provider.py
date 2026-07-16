"""
Tests for the AI provider routing and Cloud-safe Ollama behavior.

These verify that on Streamlit Cloud (API_BASE_URL configured + reachable) the
app uses the FastAPI bridge and never instantiates the local Ollama client or
connects to localhost:11434. Status functions must not raise or log the
"Failed to connect to Ollama" error in Cloud mode.
"""

import importlib
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def cloud_env(monkeypatch):
    """Simulate Streamlit Cloud with a reachable external API bridge."""
    monkeypatch.setenv("API_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("STREAMLIT_SERVER_HEADLESS", "true")
    monkeypatch.delenv("ALLOW_DIRECT_OLLAMA", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    # Reload runtime + provider so env is picked up.
    import tournament_platform.config.runtime as runtime
    import tournament_platform.app.services.ai_provider as provider
    import tournament_platform.services.ai_utils as ai_utils
    import tournament_platform.app.api_status as api_status

    importlib.reload(runtime)
    importlib.reload(provider)
    importlib.reload(ai_utils)
    importlib.reload(api_status)
    # Make the bridge appear reachable (no real HTTP in tests).
    monkeypatch.setattr(
        api_status, "get_api_status", lambda *a, **k: {"state": "connected"}
    )
    return runtime, provider, ai_utils


def test_cloud_resolves_api_bridge(cloud_env):
    runtime, provider, ai_utils = cloud_env
    assert provider.resolve_provider() == "api_bridge"


def test_cloud_direct_ollama_not_allowed(cloud_env):
    runtime, provider, ai_utils = cloud_env
    assert provider.allow_direct_ollama() is False


def test_cloud_ai_status_does_not_call_local_ollama(cloud_env):
    """get_ai_status in Cloud must not use the local Ollama client (localhost:11434)."""
    runtime, provider, ai_utils = cloud_env
    with patch.object(provider, "_api_client") as mock_client_cls:
        client = MagicMock()
        client.ollama_status.return_value = {"available": True, "models": ["llama3.1:8b"]}
        mock_client_cls.return_value = client
        with patch("tournament_platform.services.ai_utils._local_ollama_status") as mock_local:
            mock_local.return_value = {"ollama_connected": True}
            status = ai_utils.get_ai_status()
    # The local client helper must not be touched in Cloud bridge mode.
    mock_local.assert_not_called()
    assert status["provider"] == "api_bridge"
    assert "localhost" not in str(status.get("error"))


def test_cloud_get_available_models_uses_bridge(cloud_env):
    runtime, provider, ai_utils = cloud_env
    with patch.object(provider, "_api_client") as mock_client_cls:
        client = MagicMock()
        client.ollama_status.return_value = {"available": True, "models": ["llama3.1:8b"]}
        mock_client_cls.return_value = client
        models = ai_utils.get_available_ollama_models()
    assert models == ["llama3.1:8b"]


def test_cloud_ai_status_unavailable_returns_no_localhost_error(cloud_env):
    """When the bridge reports Ollama down, status is unavailable (no crash, no localhost)."""
    runtime, provider, ai_utils = cloud_env
    with patch.object(provider, "_api_client") as mock_client_cls:
        client = MagicMock()
        client.ollama_status.return_value = {"available": False, "error": "connection refused"}
        mock_client_cls.return_value = client
        status = ai_utils.get_ai_status()
    assert status["ollama_connected"] is False
    assert status["provider"] == "api_bridge"


def test_local_direct_ollama_allowed_when_opted_in(monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("STREAMLIT_SERVER_HEADLESS", raising=False)
    monkeypatch.setenv("ALLOW_DIRECT_OLLAMA", "true")
    import tournament_platform.config.runtime as runtime
    import tournament_platform.app.services.ai_provider as provider

    importlib.reload(runtime)
    importlib.reload(provider)
    assert provider.allow_direct_ollama() is True


def test_local_fallback_without_api(monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("STREAMLIT_SERVER_HEADLESS", raising=False)
    monkeypatch.delenv("ALLOW_DIRECT_OLLAMA", raising=False)
    import tournament_platform.config.runtime as runtime
    import tournament_platform.app.services.ai_provider as provider

    importlib.reload(runtime)
    importlib.reload(provider)
    assert provider.resolve_provider() == "template_fallback"


def test_ai_engine_chat_uses_bridge_in_cloud(cloud_env):
    """AIEngine._chat_with_fallback must route through the bridge on Cloud."""
    runtime, provider, ai_utils = cloud_env
    import tournament_platform.services.ai_engine as ai_engine

    importlib.reload(ai_engine)
    with patch("tournament_platform.app.services.ai_provider.ollama_chat") as mock_chat:
        mock_chat.return_value = {"ok": True, "message": "bridge answer"}
        result = ai_engine.AIEngine()._chat_with_fallback(
            messages=[{"role": "user", "content": "hi"}]
        )
    assert result["message"]["content"] == "bridge answer"
    mock_chat.assert_called_once()


def test_ai_engine_init_does_not_list_local_in_cloud(cloud_env):
    """AIEngine.__init__ must not call ollama.list() in Cloud bridge mode."""
    runtime, provider, ai_utils = cloud_env
    import tournament_platform.services.ai_engine as ai_engine

    importlib.reload(ai_engine)
    with patch("tournament_platform.services.ai_engine.ollama") as mock_ollama:
        ai_engine.AIEngine()
    mock_ollama.list.assert_not_called()
