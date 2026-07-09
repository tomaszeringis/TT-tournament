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


def _get_env_float(name: str, default: float) -> float:
    """Read a float environment variable with a default."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


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

# ---------------------------------------------------------------------------
# Voice Scorekeeper — feature flags (all default OFF; local-first baseline)
# ---------------------------------------------------------------------------
VOICE_ENABLE_SPEAKER_ID: bool = _get_env_bool("VOICE_ENABLE_SPEAKER_ID", False)
VOICE_ENABLE_MULTILINGUAL: bool = _get_env_bool("VOICE_ENABLE_MULTILINGUAL", False)  # excluded from implementation per directive
VOICE_ENABLE_TTS_CONFIRMATION: bool = _get_env_bool("VOICE_ENABLE_TTS_CONFIRMATION", False)
VOICE_TTS_MODE: str = _get_env_str("VOICE_TTS_MODE", "off")  # off | visual_only | audio_after_game | audio_every_score | audio_on_uncertainty
VOICE_TTS_PROVIDER: str = _get_env_str("VOICE_TTS_PROVIDER", "offline")  # offline | cloud
VOICE_ENABLE_NOISE_FILTERING: bool = _get_env_bool("VOICE_ENABLE_NOISE_FILTERING", False)
VOICE_NOISE_THRESHOLD: float = _get_env_float("VOICE_NOISE_THRESHOLD", 0.0)
VOICE_STRICT_MODE: bool = _get_env_bool("VOICE_STRICT_MODE", False)
VOICE_ENABLE_LLM_INTERPRETER: bool = _get_env_bool("VOICE_ENABLE_LLM_INTERPRETER", False)
VOICE_ENABLE_MOBILE_AGENT: bool = _get_env_bool("VOICE_ENABLE_MOBILE_AGENT", False)
VOICE_DEBUG_EVENTS: bool = _get_env_bool("VOICE_DEBUG_EVENTS", False)
VOICE_SPEAKER_MODE: str = _get_env_str("VOICE_SPEAKER_MODE", "manual")  # manual | enrollment | off
VOICE_SPEAKER_REQUIRE: str = _get_env_str("VOICE_SPEAKER_REQUIRE", "")  # comma list of allowed speakers
VOICE_ASR_VOCAB_FILE: str = _get_env_str("VOICE_ASR_VOCAB_FILE", "")
VOICE_RETENTION_DAYS: int = int(os.environ.get("VOICE_RETENTION_DAYS", "0"))
VOICE_ASR_BACKEND: str = _get_env_str("VOICE_ASR_BACKEND", "faster_whisper")
VOICE_ASR_FALLBACK_BACKEND: str = _get_env_str("VOICE_ASR_FALLBACK_BACKEND", "faster_whisper")
VOICE_ASR_MODEL_SIZE: str = _get_env_str("VOICE_ASR_MODEL_SIZE", "base.en")
VOICE_ASR_DEVICE: str = _get_env_str("VOICE_ASR_DEVICE", "cpu")
VOICE_ASR_COMPUTE_TYPE: str = _get_env_str("VOICE_ASR_COMPUTE_TYPE", "int8")
VOICE_ENABLE_CONFIRMATION: bool = _get_env_bool("VOICE_ENABLE_CONFIRMATION", True)
VOICE_DATASET_OPT_IN: bool = _get_env_bool("VOICE_DATASET_OPT_IN", False)
