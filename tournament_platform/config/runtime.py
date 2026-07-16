"""Runtime configuration helper.

Decouples "the Streamlit app is running" from "an external FastAPI backend is
reachable". The Streamlit app is fully functional in *local Streamlit mode*
(tournament management, manual scoring, live scoreboard, match analytics, voice
scorekeeper, and admin tools all talk to the local SQLite database directly). An
external API backend (for example a local FastAPI server exposed through ngrok)
is only used when it is explicitly configured via ``API_BASE_URL``.

Runtime modes
-------------
* ``local_streamlit``        — no external API configured; app uses local services.
* ``external_api``           — API configured and reachable.
* ``optional_api_unavailable`` — API configured but unreachable and not required;
  the app falls back to local services.
* ``required_unavailable``    — API configured, unreachable, and ``API_REQUIRED=true``;
  a clear error is shown (the app still does not crash).

Resolution priority for every value:
  1. environment variable
  2. Streamlit secret
  3. safe default
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any


def get_secret_optional(key: str) -> Optional[str]:
    """Return a Streamlit secret value, or ``None`` if it is missing/unavailable.

    Never raises — Streamlit Cloud and local runs both work whether or not
    ``st.secrets`` is configured.
    """
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets:
            value = st.secrets.get(key)
            if value:
                return str(value)
    except Exception:
        pass
    return None


def _resolve_first(key: str, default: Optional[str] = None) -> Optional[str]:
    """Resolve a value from env var first, then Streamlit secret, then default."""
    env = os.getenv(key)
    if env:
        return env
    secret = get_secret_optional(key)
    if secret:
        return secret
    return default


def _resolve_api_base_url() -> Optional[str]:
    """Resolve the external API base URL.

    Priority:
      1. ``API_BASE_URL`` environment variable
      2. ``API_BASE_URL`` Streamlit secret
      3. no external API configured -> ``None`` (local Streamlit mode)
    """
    return _resolve_first("API_BASE_URL")


def _resolve_api_token() -> Optional[str]:
    """Resolve the optional API bearer token (env, then secret)."""
    return _resolve_first("API_TOKEN")


def _resolve_api_required() -> bool:
    """Resolve whether the external API is required (env, then secret, default false)."""
    raw = _resolve_first("API_REQUIRED", "false")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_ollama_model() -> str:
    """Resolve the Ollama model used by the bridge/local calls.

    Priority: ``OLLAMA_MODEL`` env/secret, then ``llama3.1:8b`` fallback.
    """
    return _resolve_first("OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b"


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration for the Streamlit app."""

    is_streamlit_cloud: bool
    api_base_url: Optional[str]
    api_required: bool
    api_token: Optional[str]
    ollama_model: str
    mode: str

    @property
    def external_api(self) -> bool:
        """Whether an external API backend is configured."""
        return bool(self.api_base_url)

    def auth_headers(self) -> dict:
        """Return ``Authorization: Bearer <token>`` headers when a token is set.

        The token is never logged or exposed in the UI.
        """
        if self.api_token:
            return {"Authorization": f"Bearer {self.api_token}"}
        return {}


def get_runtime_config() -> RuntimeConfig:
    """Build the runtime configuration from env/secrets."""
    api_base_url = _resolve_api_base_url()
    api_token = _resolve_api_token()
    api_required = _resolve_api_required()
    ollama_model = _resolve_ollama_model()

    is_streamlit_cloud = bool(
        os.getenv("STREAMLIT_SERVER_HEADLESS")
        or os.getenv("STREAMLIT_SHARING_MODE")
        or os.getenv("STREAMLIT_CLOUD")
    )

    # Base mode: external API is configured or not. The unavailable variants
    # (optional_api_unavailable / required_api_unavailable) are derived from an
    # actual connectivity check in ``get_app_status`` / ``get_ollama_status``.
    if api_base_url:
        mode = "external_api"
    else:
        mode = "local_streamlit"

    return RuntimeConfig(
        is_streamlit_cloud=is_streamlit_cloud,
        api_base_url=api_base_url,
        api_required=api_required,
        api_token=api_token,
        ollama_model=ollama_model,
        mode=mode,
    )


def get_api_token() -> Optional[str]:
    """Return the configured API bearer token, or ``None`` if unset."""
    return _resolve_api_token()


def get_ollama_model() -> str:
    """Return the configured Ollama model (env/secret, then ``llama3.1:8b``)."""
    return _resolve_ollama_model()


def get_ollama_status() -> Dict[str, Any]:
    """Resolve Ollama availability through the FastAPI bridge when configured.

    When an external API is configured, this queries ``/ollama/status`` (which
    reaches local Ollama on the laptop). When no API is configured, the app is
    in local Streamlit mode and reports the configured model without claiming
    availability (Ollama is reached directly by local services instead).

    Returns a dict with keys: ``available`` (bool|None), ``model`` (str),
    ``through_api`` (bool), ``error`` (str|None).
    """
    cfg = get_runtime_config()
    if cfg.api_base_url:
        try:
            from tournament_platform.app.api_client import api_client

            status = api_client.ollama_status()
            if status is None:
                # API reachable check handled separately; treat as unknown here.
                return {
                    "available": None,
                    "model": cfg.ollama_model,
                    "through_api": True,
                    "error": "API status check failed",
                }
            return {
                "available": bool(status.get("available")),
                "model": cfg.ollama_model,
                "through_api": True,
                "error": status.get("error"),
            }
        except Exception as exc:
            return {
                "available": None,
                "model": cfg.ollama_model,
                "through_api": True,
                "error": str(exc),
            }
    return {
        "available": None,
        "model": cfg.ollama_model,
        "through_api": False,
        "error": None,
    }
