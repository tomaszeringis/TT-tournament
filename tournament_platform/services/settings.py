"""
Lightweight feature flags and service settings for the Tournament Platform.

Reads from environment variables (and .env via python-dotenv) with safe defaults
so quick-win AI features can be enabled or disabled without code changes.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on process env only


def _get_env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def _get_env_str(name: str, default: str) -> str:
    """Read a string environment variable with a default."""
    return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# API / Service URLs
# ---------------------------------------------------------------------------
# Import overlapping values from the main config to keep a single source of truth.
from tournament_platform.config import settings as _app_settings  # noqa: E402

API_BASE_URL: str = _get_env_str("API_BASE_URL", _app_settings.API_BASE_URL)

# ---------------------------------------------------------------------------
# Ollama LLM
# ---------------------------------------------------------------------------
OLLAMA_MODEL: str = _get_env_str("OLLAMA_MODEL", _app_settings.OLLAMA_MODEL)

# ---------------------------------------------------------------------------
# Feature flags (quick wins)
# ---------------------------------------------------------------------------
ENABLE_VOICE_ENTRY: bool = _get_env_bool("ENABLE_VOICE_ENTRY", True)
ENABLE_RULES_ASSISTANT: bool = _get_env_bool("ENABLE_RULES_ASSISTANT", True)
ENABLE_RANKING_INTELLIGENCE: bool = _get_env_bool("ENABLE_RANKING_INTELLIGENCE", True)
ENABLE_SPOKEN_CONFIRMATION: bool = _get_env_bool("ENABLE_SPOKEN_CONFIRMATION", False)
KEEP_AUDIO_FILES: bool = _get_env_bool("KEEP_AUDIO_FILES", False)

# ---------------------------------------------------------------------------
# Speech / Whisper
# ---------------------------------------------------------------------------
SPEECH_MODEL_SIZE: str = _get_env_str("SPEECH_MODEL_SIZE", _app_settings.WHISPER_MODEL_SIZE)
