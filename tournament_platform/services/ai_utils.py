"""
Shared AI utilities for model availability and status checks.

On Streamlit Cloud (or any time ``API_BASE_URL`` is configured) these functions
never instantiate the local Ollama client and never contact ``localhost:11434``.
Instead they resolve availability through the FastAPI bridge
(``tournament_platform.app.services.ai_provider``), which reaches local Ollama
on the laptop. Direct local Ollama is only used in local Streamlit mode when
``ALLOW_DIRECT_OLLAMA=true``.
"""

import logging
from typing import Tuple, Optional, List

from tournament_platform.config import settings

logger = logging.getLogger(__name__)


def _is_cloud_bridge_mode() -> bool:
    """True when an external FastAPI bridge is the active AI provider."""
    try:
        from tournament_platform.app.services.ai_provider import resolve_provider

        return resolve_provider() == "api_bridge"
    except Exception:
        return False


def _local_ollama_status(model: str) -> dict:
    """Probe the local Ollama client directly (local development only)."""
    import ollama

    status = {
        "ollama_connected": False,
        "model_available": False,
        "current_model": model,
        "fallback_model": None,
        "error": None,
    }
    try:
        available_models_resp = ollama.list()
        if hasattr(available_models_resp, "models"):
            model_names = [m.model for m in available_models_resp.models]
        else:
            model_names = [m.get("name") for m in available_models_resp.get("models", [])]
        status["ollama_connected"] = len(model_names) > 0
        if model_names:
            status["model_available"] = True
            status["current_model"] = model
    except Exception as e:
        logger.warning("Local Ollama status check failed: %s", e)
        status["error"] = str(e)
    return status


def _local_available_ollama_models() -> List[str]:
    """List local Ollama models (local development only)."""
    import ollama

    try:
        available_models_resp = ollama.list()
        if hasattr(available_models_resp, "models"):
            return [m.model for m in available_models_resp.models]
        return [m.get("name") for m in available_models_resp.get("models", [])]
    except Exception as e:
        logger.warning("Error connecting to local Ollama: %s", e)
        return []


def get_available_ollama_models() -> list:
    """
    Get list of available Ollama models for the active provider.

    In Cloud/external API mode this queries the bridge (no local Ollama client).
    In local mode (``ALLOW_DIRECT_OLLAMA=true``) it uses the local client.
    Returns an empty list if Ollama is unavailable or no provider is active.
    Never raises and never connects to ``localhost:11434`` in Cloud.
    """
    try:
        from tournament_platform.app.services.ai_provider import list_models

        return list_models()
    except Exception as e:
        logger.warning("Ollama model list failed: %s", e)
        return []


def get_ollama_model_with_fallback(preferred_model: str = None) -> Tuple[str, bool]:
    """
    Get the best available Ollama model with fallback logic.

    Args:
        preferred_model: The preferred model name (defaults to settings.OLLAMA_MODEL)

    Returns:
        Tuple of (model_name, is_fallback) where is_fallback indicates
        if a fallback was used instead of the preferred model.
    """
    preferred = preferred_model or settings.OLLAMA_MODEL
    model_names = get_available_ollama_models()

    if not model_names:
        return preferred, False  # Will fail later with connection error

    # Check for preferred model
    if preferred in model_names:
        return preferred, False

    # Try fallbacks
    fallbacks = [
        "llama3.1:8b",
        "llama3:latest",
        "llama3:8b",
        "llama3.2:3b",
        "llama3.2:1b",
    ]

    for fallback in fallbacks:
        if fallback in model_names:
            logger.info(f"Ollama model fallback: {preferred} -> {fallback}")
            return fallback, True

    # No model found, return preferred (will error on use)
    return preferred, False


def get_ai_status() -> dict:
    """
    Get comprehensive AI system status for the active provider.

    In Cloud/external API mode this resolves Ollama availability through the
    FastAPI bridge, so the local Ollama client is never contacted and the
    "Failed to connect to Ollama" error never appears. When no provider is
    active it returns a graceful template-fallback status (no error, no
    scary red Ollama banner).
    """
    try:
        from tournament_platform.app.services.ai_provider import get_ai_status as _provider_status

        if _is_cloud_bridge_mode() or not _is_local_direct_allowed():
            return _provider_status()
    except Exception as e:
        logger.warning("AI status via provider failed: %s", e)

    # Local direct mode.
    model = settings.OLLAMA_MODEL
    return _local_ollama_status(model)


def _is_local_direct_allowed() -> bool:
    try:
        from tournament_platform.app.services.ai_provider import allow_direct_ollama

        return allow_direct_ollama()
    except Exception:
        return False


def ensure_model_available(model: str = None, silent: bool = False) -> str:
    """
    Ensure the specified model is available, with fallback.

    In Cloud/external API mode this is a no-op that returns the configured model
    (availability is governed by the bridge). In local mode it raises only when
    no local model is available.
    """
    preferred = model or settings.OLLAMA_MODEL
    model_names = get_available_ollama_models()

    if not model_names:
        if _is_cloud_bridge_mode():
            # Bridge mode: model availability is reported by /ollama/status;
            # do not raise a scary local-Ollama error on Streamlit Cloud.
            return preferred
        raise ValueError(
            f"Cannot connect to Ollama at {settings.OLLAMA_HOST}. "
            f"Please ensure Ollama is running ('ollama serve')."
        )

    if preferred in model_names:
        return preferred

    # Try fallbacks
    fallbacks = ["llama3.1:8b", "llama3:latest", "llama3:8b", "llama3.2:3b", "llama3.2:1b"]
    for fallback in fallbacks:
        if fallback in model_names:
            if not silent:
                print(f"Warning: Model '{preferred}' not found. Falling back to '{fallback}'.")
            return fallback

    return preferred
