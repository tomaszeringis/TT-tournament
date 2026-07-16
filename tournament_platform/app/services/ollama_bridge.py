"""Ollama bridge facade for Streamlit AI features.

This module is the single decision point for how the Streamlit app reaches
Ollama:

* **Local Streamlit mode** (no ``API_BASE_URL``): call local Ollama directly
  on the laptop via the ``ollama`` Python client (same machine).
* **External API mode** (``API_BASE_URL`` configured AND reachable): route
  through the FastAPI bridge (``/ollama/generate``, ``/ollama/chat``) which is
  exposed via ngrok. Streamlit Cloud never talks to Ollama directly.

Every call degrades gracefully: if Ollama/API is unavailable the methods
return ``None`` (or ``ok=false``) instead of raising, so manual scoring,
match analytics, and commentary templates keep working.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _runtime():
    from tournament_platform.config.runtime import get_runtime_config

    return get_runtime_config()


def _api_client():
    from tournament_platform.app.api_client import api_client

    return api_client


def _local_models() -> List[str]:
    """Return locally available Ollama model names (empty list if down)."""
    try:
        from tournament_platform.services import ai_utils

        return ai_utils.get_available_ollama_models()
    except Exception as exc:
        logger.warning("Local Ollama model check failed: %s", exc)
        return []


def _local_generate(
    prompt: str,
    model: Optional[str],
    system: Optional[str],
    temperature: float,
) -> Optional[Dict[str, Any]]:
    """Call local Ollama via the ``ollama`` Python client."""
    try:
        import ollama

        kwargs: Dict[str, Any] = {
            "model": model or _runtime().ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            kwargs["system"] = system
        resp = ollama.generate(**kwargs)
        return {
            "ok": True,
            "model": resp.get("model", model),
            "response": resp.get("response", ""),
            "raw": resp,
        }
    except Exception as exc:
        logger.warning("Local Ollama generate failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _local_chat(
    messages: List[Dict[str, str]],
    model: Optional[str],
    temperature: float,
) -> Optional[Dict[str, Any]]:
    """Call local Ollama chat via the ``ollama`` Python client."""
    try:
        import ollama

        resp = ollama.chat(
            model=model or _runtime().ollama_model,
            messages=messages,
            stream=False,
            options={"temperature": temperature},
        )
        content = resp.get("message", {}).get("content", "")
        return {
            "ok": True,
            "model": resp.get("model", model),
            "message": content,
            "raw": resp,
        }
    except Exception as exc:
        logger.warning("Local Ollama chat failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def generate(
    prompt: str,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """Generate text via Ollama.

    Uses the FastAPI bridge when an external API is configured and reachable,
    otherwise the local ``ollama`` client. Returns ``None`` on transport
    failure, or ``{"ok": false, "error": ...}`` when Ollama itself errors.
    """
    cfg = _runtime()
    if cfg.api_base_url:
        from tournament_platform.app import api_status

        if api_status.get_api_status(cfg.api_base_url, cfg.api_required, cfg.api_token)["state"] == "connected":
            return _api_client().ollama_generate(
                prompt=prompt, model=model, system=system, temperature=temperature
            )
        # API configured but not reachable -> fall back to local if possible,
        # else return None so callers use templates.
        if cfg.is_streamlit_cloud:
            return None
    return _local_generate(prompt=prompt, model=model, system=system, temperature=temperature)


def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """Chat via Ollama (see :func:`generate` for routing/fallback rules)."""
    cfg = _runtime()
    if cfg.api_base_url:
        from tournament_platform.app import api_status

        if api_status.get_api_status(cfg.api_base_url, cfg.api_required, cfg.api_token)["state"] == "connected":
            return _api_client().ollama_chat(messages=messages, model=model, temperature=temperature)
        if cfg.is_streamlit_cloud:
            return None
    return _local_chat(messages=messages, model=model, temperature=temperature)


def status() -> Dict[str, Any]:
    """Return a unified Ollama status dict for diagnostics UI.

    Keys: ``available`` (bool|None), ``through_api`` (bool), ``model`` (str),
    ``error`` (str|None), ``mode`` (str).
    """
    from tournament_platform.config.runtime import get_ollama_status

    return get_ollama_status()
