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
from typing import Optional


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


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration for the Streamlit app."""

    is_streamlit_cloud: bool
    api_base_url: Optional[str]
    api_required: bool
    api_token: Optional[str]
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

    is_streamlit_cloud = bool(
        os.getenv("STREAMLIT_SERVER_HEADLESS")
        or os.getenv("STREAMLIT_SHARING_MODE")
        or os.getenv("STREAMLIT_CLOUD")
    )

    if api_base_url:
        mode = "external_api" if not api_required else "external_api"
    else:
        mode = "local_streamlit"

    return RuntimeConfig(
        is_streamlit_cloud=is_streamlit_cloud,
        api_base_url=api_base_url,
        api_required=api_required,
        api_token=api_token,
        mode=mode,
    )


def get_api_token() -> Optional[str]:
    """Return the configured API bearer token, or ``None`` if unset."""
    return _resolve_api_token()
