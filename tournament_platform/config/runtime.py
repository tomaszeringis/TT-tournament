"""Runtime configuration helper.

Decouples "the Streamlit app is running" from "an external FastAPI backend is
reachable". The Streamlit app is fully functional in *local Streamlit mode*
(tournament management, manual scoring, live scoreboard, match analytics, voice
scorekeeper, and admin tools all talk to the local SQLite database directly). An
external API backend is only required when it is explicitly configured.
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


def _resolve_api_base_url() -> Optional[str]:
    """Resolve the external API base URL.

    Priority:
      1. ``API_BASE_URL`` environment variable
      2. ``API_BASE_URL`` Streamlit secret
      3. no external API configured -> ``None`` (local Streamlit mode)
    """
    env = os.getenv("API_BASE_URL")
    if env:
        return env
    secret = get_secret_optional("API_BASE_URL")
    if secret:
        return secret
    return None


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration for the Streamlit app."""

    is_streamlit_cloud: bool
    api_base_url: Optional[str]
    api_required: bool
    mode: str

    @property
    def external_api(self) -> bool:
        """Whether an external API backend is configured."""
        return bool(self.api_base_url)


def get_runtime_config() -> RuntimeConfig:
    """Build the runtime configuration from env/secrets."""
    api_base_url = _resolve_api_base_url()

    is_streamlit_cloud = bool(
        os.getenv("STREAMLIT_SERVER_HEADLESS")
        or os.getenv("STREAMLIT_SHARING_MODE")
        or os.getenv("STREAMLIT_CLOUD")
    )

    api_required = os.getenv("API_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}

    if api_base_url:
        mode = "external_api"
    else:
        mode = "local_streamlit"

    return RuntimeConfig(
        is_streamlit_cloud=is_streamlit_cloud,
        api_base_url=api_base_url,
        api_required=api_required,
        mode=mode,
    )
