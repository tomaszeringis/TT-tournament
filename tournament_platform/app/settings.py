"""
App-level settings for the Tournament Platform Streamlit frontend.

These settings are used by the Streamlit app to configure API client behavior.
Values are read from environment variables with safe defaults.
"""

import os
from typing import Optional

from tournament_platform.app.services.voice.hf_token import apply_hf_token

apply_hf_token()


def _get_env_str(name: str, default: str) -> str:
    """Read a string environment variable with a default."""
    return os.environ.get(name, default)


def _get_env_str_or_none(name: str) -> Optional[str]:
    """Read an optional string environment variable; return ``None`` if unset."""
    value = os.environ.get(name)
    return value if value else None


def _get_env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a default."""
    value = os.environ.get(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# API / Backend
# ---------------------------------------------------------------------------
# Base URL used by the Streamlit frontend to reach the FastAPI backend.
#
# Defaults to ``None`` (not configured) so the Streamlit app runs in local
# Streamlit mode without pinging a nonexistent localhost backend. Set
# ``API_BASE_URL`` only when a real external backend exists. Local development
# may set ``API_BASE_URL=http://localhost:8000`` explicitly.
API_BASE_URL: Optional[str] = _get_env_str_or_none("API_BASE_URL")

# Timeout for API requests in seconds.
API_TIMEOUT_SECONDS: int = _get_env_int("API_TIMEOUT_SECONDS", 10)

# Show debug details in error messages (for development only).
# In production, this should be False to avoid exposing sensitive information.
SHOW_DEBUG_DETAILS: bool = _get_env_bool("SHOW_DEBUG_DETAILS", False)

# ---------------------------------------------------------------------------
# Voice Latency Diagnostics
# ---------------------------------------------------------------------------
# Enable latency tracing data collection. When true, span start/finish
# events are recorded to a bounded in-memory history.
VOICE_LATENCY_TRACE: bool = _get_env_bool("VOICE_LATENCY_TRACE", False)

# Enable the latency diagnostics UI on the Voice Scorekeeper page.
# Requires VOICE_LATENCY_TRACE to be true for data collection.
VOICE_SHOW_LATENCY: bool = _get_env_bool("VOICE_SHOW_LATENCY", False)

# Bounded history size for latency events. Validated to the range 20–2000.
VOICE_LATENCY_HISTORY_SIZE: int = _get_env_int("VOICE_LATENCY_HISTORY_SIZE", 200)