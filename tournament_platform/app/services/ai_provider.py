"""AI provider routing for the Streamlit app.

This is the single decision point that decides how the Streamlit app reaches
Ollama. It supports three providers:

* ``api_bridge``      — call Ollama through the FastAPI ngrok bridge
                       (``/ollama/status``, ``/ollama/generate``, ``/ollama/chat``).
                       Used on Streamlit Cloud and anywhere ``API_BASE_URL`` is set
                       and reachable. The local Ollama client is never instantiated
                       in this mode, so no ``localhost:11434`` connection is attempted.
* ``local_ollama``    — call the local ``ollama`` Python client directly. Only used
                       in local Streamlit mode when ``ALLOW_DIRECT_OLLAMA=true`` and an
                       external API is not configured.
* ``template_fallback`` — no AI available; callers use static templates.

Selection rules:

* External API configured AND reachable -> ``api_bridge``.
* Local mode, ``ALLOW_DIRECT_OLLAMA=true``, no API -> ``local_ollama``.
* Otherwise -> ``template_fallback``.

None of these raise. Failures return structured fallbacks so manual scoring,
voice scorekeeper, scoreboard, and analytics keep working.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _runtime():
    from tournament_platform.config.runtime import get_runtime_config

    return get_runtime_config()


def _api_client():
    from tournament_platform.app.api_client import api_client

    return api_client


def _api_status_state() -> str:
    from tournament_platform.app import api_status

    cfg = _runtime()
    return api_status.get_api_status(cfg.api_base_url, cfg.api_required, cfg.api_token)["state"]


def is_streamlit_cloud() -> bool:
    """Whether the app is running on Streamlit Cloud."""
    return bool(_runtime().is_streamlit_cloud)


def allow_direct_ollama() -> bool:
    """Whether a direct local Ollama client is permitted.

    Only allowed when explicitly opted in via ``ALLOW_DIRECT_OLLAMA=true`` AND an
    external API is not configured. Never allowed on Streamlit Cloud.
    """
    if is_streamlit_cloud():
        return False
    if _runtime().api_base_url:
        return False
    return os.environ.get("ALLOW_DIRECT_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_provider() -> str:
    """Return the active provider: ``api_bridge``, ``local_ollama``, or ``template_fallback``."""
    cfg = _runtime()
    if cfg.api_base_url:
        if _api_status_state() == "connected":
            return "api_bridge"
        # API configured but unreachable. Use template fallback (no direct Ollama
        # on Cloud, and local direct Ollama is not implied just because the API
        # is down).
        return "template_fallback"
    if allow_direct_ollama():
        return "local_ollama"
    return "template_fallback"


def list_models() -> List[str]:
    """Return available Ollama model names for the active provider.

    In Cloud/external API mode this queries the bridge (which reaches local
    Ollama on the laptop). In local mode it uses the local client only when
    direct Ollama is allowed. Returns ``[]`` otherwise (never raises, never
    connects to ``localhost:11434`` in Cloud).
    """
    provider = resolve_provider()
    if provider == "api_bridge":
        try:
            status = _api_client().ollama_status()
            if status and status.get("available"):
                return status.get("models", []) or []
        except Exception as exc:
            logger.warning("AI provider: bridge model list failed: %s", exc)
        return []
    if provider == "local_ollama":
        try:
            import ollama

            resp = ollama.list()
            if hasattr(resp, "models"):
                return [m.model for m in resp.models]
            return [m.get("name") for m in resp.get("models", [])]
        except Exception as exc:
            logger.warning("AI provider: local model list failed: %s", exc)
            return []
    return []


def api_health() -> Optional[Dict[str, Any]]:
    """Call ``GET {API_BASE_URL}/health``; returns the JSON or ``None``."""
    return _api_client().health()


def ollama_status() -> Optional[Dict[str, Any]]:
    """Call ``GET {API_BASE_URL}/ollama/status``; returns the JSON or ``None``."""
    return _api_client().ollama_status()


def ollama_generate(
    prompt: str,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """Generate text. Routes through the bridge in external API mode; in local
    mode uses the local client only when direct Ollama is allowed. Returns
    ``None`` on failure (callers fall back to templates).
    """
    provider = resolve_provider()
    if provider == "api_bridge":
        return _api_client().ollama_generate(
            prompt=prompt, model=model, system=system, temperature=temperature
        )
    if provider == "local_ollama":
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
            logger.warning("AI provider: local generate failed: %s", exc)
            return {"ok": False, "error": str(exc)}
    return None


def ollama_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """Chat. Routes through the bridge in external API mode; in local mode uses
    the local client only when direct Ollama is allowed. Returns ``None`` on
    failure (callers fall back to templates).
    """
    provider = resolve_provider()
    if provider == "api_bridge":
        return _api_client().ollama_chat(messages=messages, model=model, temperature=temperature)
    if provider == "local_ollama":
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
            logger.warning("AI provider: local chat failed: %s", exc)
            return {"ok": False, "error": str(exc)}
    return None


def get_ai_status() -> Dict[str, Any]:
    """Return an AI status dict safe for Cloud.

    In external API mode the Ollama availability is taken from the bridge, so
    the local ``ollama`` client is never contacted. In local mode (direct Ollama
    allowed) it inspects the local client. Otherwise it reports a template
    fallback state without any ``localhost:11434`` connection attempt.
    """
    cfg = _runtime()
    provider = resolve_provider()

    if provider == "api_bridge":
        try:
            status = _api_client().ollama_status()
            available = bool(status.get("available")) if status else False
            return {
                "ollama_connected": available,
                "model_available": available,
                "current_model": cfg.ollama_model,
                "fallback_model": None,
                "error": (status.get("error") if status else "bridge unreachable"),
                "provider": "api_bridge",
            }
        except Exception as exc:
            return {
                "ollama_connected": False,
                "model_available": False,
                "current_model": cfg.ollama_model,
                "fallback_model": None,
                "error": str(exc),
                "provider": "api_bridge",
            }

    if provider == "local_ollama":
        try:
            from tournament_platform.services.ai_utils import _local_ollama_status

            return _local_ollama_status(cfg.ollama_model)
        except Exception as exc:
            return {
                "ollama_connected": False,
                "model_available": False,
                "current_model": cfg.ollama_model,
                "fallback_model": None,
                "error": str(exc),
                "provider": "local_ollama",
            }

    return {
        "ollama_connected": False,
        "model_available": False,
        "current_model": cfg.ollama_model,
        "fallback_model": None,
        "error": None,
        "provider": "template_fallback",
    }


def get_runtime_diagnostics() -> Dict[str, Any]:
    """Return diagnostics for the collapsed expander."""
    cfg = _runtime()
    provider = resolve_provider()
    api_state = _api_status_state()

    if provider == "api_bridge":
        ollama_route = "API bridge"
    elif provider == "local_ollama":
        ollama_route = "Direct local"
    else:
        ollama_route = "Fallback"

    return {
        "streamlit_cloud": cfg.is_streamlit_cloud,
        "api_base_url_configured": bool(cfg.api_base_url),
        "api_required": cfg.api_required,
        "api_health": api_state,
        "ollama_route": ollama_route,
        "ollama_model": cfg.ollama_model,
        "hf_token_configured": bool(os.environ.get("HF_TOKEN") or _secret_hf_token()),
        "direct_ollama_allowed": allow_direct_ollama(),
    }


def _secret_hf_token() -> Optional[str]:
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets:
            return st.secrets.get("HF_TOKEN")
    except Exception:
        pass
    return None
