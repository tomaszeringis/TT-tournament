"""
Lightweight feature flags and service settings for the Tournament Platform.

Reads from environment variables (and .env via python-dotenv) with safe defaults
so quick-win AI features can be enabled or disabled without code changes.
"""

import os

try:
    from dotenv import load_dotenv

    # Resolve the project root by walking up from this file's directory until
    # we find pyproject.toml.  This makes .env loading independent of the
    # current working directory.
    _settings_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = _settings_dir
    while _project_root != os.path.dirname(_project_root):
        if os.path.isfile(os.path.join(_project_root, "pyproject.toml")):
            break
        _project_root = os.path.dirname(_project_root)
    else:
        _project_root = _settings_dir

    _dotenv_path = os.path.join(_project_root, ".env")
    # override=False so explicitly-set process environment variables win over
    # the local-only .env file (which is not present on Streamlit Cloud).
    if os.path.isfile(_dotenv_path):
        load_dotenv(_dotenv_path, override=False)
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
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


def _get_env_float(name: str, default: float) -> float:
    """Read a float environment variable with a default."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a default."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _clamp_endpointing(raw: str) -> str:
    """Parse endpointing ms and clamp to [250, 400] per plan §6 validation rules."""
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        val = 300
    return str(max(250, min(400, val)))


def _clamp_ambient_seconds(raw: float) -> float:
    """Clamp ambient health-check window to [1, 10] per plan §6 validation rules."""
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 2.0
    return max(1.0, min(10.0, val))


def _validate_deepgram_language(value: str) -> str:
    """Validate Deepgram language is 'lt' or 'en' (no silent fallback)."""
    normalized = value.strip().lower()
    if normalized not in ("lt", "en"):
        raise ValueError(
            f"Invalid VOICE_DEEPGRAM_LANGUAGE='{value}'. Must be 'lt' or 'en'."
        )
    return normalized


def _validate_local_vad_mode(value: str) -> str:
    """Validate VOICE_LOCAL_VAD_MODE."""
    normalized = value.strip().lower()
    if normalized not in ("continuous", "gated", "disabled"):
        raise ValueError(
            f"Invalid VOICE_LOCAL_VAD_MODE='{value}'. "
            "Must be 'continuous', 'gated', or 'disabled'."
        )
    return normalized


# ---------------------------------------------------------------------------
# API / Service URLs
# ---------------------------------------------------------------------------
# Import overlapping values from the main config to keep a single source of truth.
from tournament_platform.config import settings as _app_settings  # noqa: E402

API_BASE_URL: str = _get_env_str("API_BASE_URL", _app_settings.API_BASE_URL or "")

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
VOICE_STREAMING_ASR_BACKEND: str = _get_env_str("VOICE_STREAMING_ASR_BACKEND", "")
VOICE_ASR_FALLBACK_BACKEND: str = _get_env_str("VOICE_ASR_FALLBACK_BACKEND", "faster_whisper")
VOICE_ASR_MODEL_SIZE: str = _get_env_str("VOICE_ASR_MODEL_SIZE", "tiny.en")
VOICE_ASR_DEVICE: str = _get_env_str("VOICE_ASR_DEVICE", "cpu")
VOICE_ASR_COMPUTE_TYPE: str = _get_env_str("VOICE_ASR_COMPUTE_TYPE", "int8")
VOICE_ASR_VOSK_MODEL_PATH: str = _get_env_str("VOICE_ASR_VOSK_MODEL_PATH", "model")
VOICE_ENABLE_CONFIRMATION: bool = _get_env_bool("VOICE_ENABLE_CONFIRMATION", True)
VOICE_DATASET_OPT_IN: bool = _get_env_bool("VOICE_DATASET_OPT_IN", False)
VOICE_ENABLE_WAKE_WORD: bool = _get_env_bool("VOICE_ENABLE_WAKE_WORD", False)
VOICE_WAKE_WORD: str = _get_env_str("VOICE_WAKE_WORD", "")
HF_TOKEN: str = _get_env_str("HF_TOKEN", "")

# ---------------------------------------------------------------------------
# Commentary Template System
# ---------------------------------------------------------------------------
VOICE_ENABLE_COMMENTARY_TEMPLATES: bool = _get_env_bool("VOICE_ENABLE_COMMENTARY_TEMPLATES", True)
VOICE_ENABLE_COMMENTARY_OLLAMA_REWRITE: bool = _get_env_bool("VOICE_ENABLE_COMMENTARY_OLLAMA_REWRITE", False)
VOICE_COMMENTARY_OLLAMA_MODEL: str = _get_env_str("VOICE_COMMENTARY_OLLAMA_MODEL", _app_settings.OLLAMA_MODEL)
VOICE_COMMENTARY_OLLAMA_TIMEOUT: float = _get_env_float("VOICE_COMMENTARY_OLLAMA_TIMEOUT", 2.0)

# ---------------------------------------------------------------------------
# Audio Rally Assistant (TT Sounds)
# ---------------------------------------------------------------------------
TT_SOUNDS_ENABLED: bool = _get_env_bool("TT_SOUNDS_ENABLED", False)
TT_SOUNDS_ABS_MIN_ENERGY: float = _get_env_float("TT_SOUNDS_ABS_MIN_ENERGY", 0.03)
TT_SOUNDS_THRESHOLD_MULTIPLIER: float = _get_env_float("TT_SOUNDS_THRESHOLD_MULTIPLIER", 4.0)
TT_SOUNDS_NOISE_FLOOR_DECAY: float = _get_env_float("TT_SOUNDS_NOISE_FLOOR_DECAY", 0.95)
TT_SOUNDS_COOLDOWN_MS: float = _get_env_float("TT_SOUNDS_COOLDOWN_MS", 80.0)
TT_SOUNDS_WINDOW_MS: float = _get_env_float("TT_SOUNDS_WINDOW_MS", 5.0)
TT_SOUNDS_EVENT_WINDOW_MS: float = _get_env_float("TT_SOUNDS_EVENT_WINDOW_MS", 15.0)
TT_SOUNDS_MIN_INTERVAL_MS: float = _get_env_float("TT_SOUNDS_MIN_INTERVAL_MS", 30.0)
TT_SOUNDS_DEBUG: bool = _get_env_bool("TT_SOUNDS_DEBUG", False)
TT_SOUNDS_MODEL_DIR: str = _get_env_str("TT_SOUNDS_MODEL_DIR", "")

# ---------------------------------------------------------------------------
# Voice Scorekeeper — Deepgram Nova-3 streaming provider (pilot)
# ---------------------------------------------------------------------------
# Feature flag: when VOICE_DEEPGRAM_ENABLED=true and VOICE_ASR_BACKEND=deepgram,
# the voice scorekeeper connects to Deepgram's Listen v1 WebSocket.
# Default is OFF so existing local-first behavior is unchanged.
VOICE_DEEPGRAM_ENABLED: bool = _get_env_bool("VOICE_DEEPGRAM_ENABLED", False)
VOICE_DEEPGRAM_API_KEY: str = _get_env_str("VOICE_DEEPGRAM_API_KEY", "")
VOICE_DEEPGRAM_MODEL: str = _get_env_str("VOICE_DEEPGRAM_MODEL", "nova-3")
VOICE_DEEPGRAM_LANGUAGE: str = _get_env_str("VOICE_DEEPGRAM_LANGUAGE", "lt")
VOICE_DEEPGRAM_ENDPOINTING_MS: int = int(_clamp_endpointing(
    _get_env_str("VOICE_DEEPGRAM_ENDPOINTING_MS", "300")
))
VOICE_DEEPGRAM_INTERIM_RESULTS: bool = _get_env_bool("VOICE_DEEPGRAM_INTERIM_RESULTS", True)
VOICE_DEEPGRAM_KEEPALIVE_SECONDS: float = _get_env_float("VOICE_DEEPGRAM_KEEPALIVE_SECONDS", 4.0)
VOICE_DEEPGRAM_SAMPLE_RATE: int = _get_env_int("VOICE_DEEPGRAM_SAMPLE_RATE", 16000)
VOICE_DEEPGRAM_CHANNELS: int = _get_env_int("VOICE_DEEPGRAM_CHANNELS", 1)
VOICE_DEEPGRAM_KEYTERMS_ENABLED: bool = _get_env_bool("VOICE_DEEPGRAM_KEYTERMS_ENABLED", True)
VOICE_DEEPGRAM_MAX_KEYTERMS: int = _get_env_int("VOICE_DEEPGRAM_MAX_KEYTERMS", 100)
VOICE_DEEPGRAM_CONNECT_TIMEOUT_SECONDS: float = _get_env_float("VOICE_DEEPGRAM_CONNECT_TIMEOUT_SECONDS", 10.0)
VOICE_DEEPGRAM_RECONNECT_ATTEMPTS: int = _get_env_int("VOICE_DEEPGRAM_RECONNECT_ATTEMPTS", 3)
VOICE_DEEPGRAM_REGION: str = _get_env_str("VOICE_DEEPGRAM_REGION", "default")

# ---------------------------------------------------------------------------
# Voice Scorekeeper — Audio health check & VAD calibration (Deepgram pilot)
# ---------------------------------------------------------------------------
VOICE_AUDIO_HEALTH_CHECK_ENABLED: bool = _get_env_bool("VOICE_AUDIO_HEALTH_CHECK_ENABLED", True)
VOICE_AUDIO_HEALTH_CHECK_REQUIRED: bool = _get_env_bool("VOICE_AUDIO_HEALTH_CHECK_REQUIRED", False)
VOICE_AUDIO_HEALTH_AMBIENT_SECONDS: int = int(_clamp_ambient_seconds(
    _get_env_float("VOICE_AUDIO_HEALTH_AMBIENT_SECONDS", 2.0)
))
VOICE_AUDIO_HEALTH_SAMPLE_COMMAND_ENABLED: bool = _get_env_bool("VOICE_AUDIO_HEALTH_SAMPLE_COMMAND_ENABLED", False)
VOICE_AUDIO_HEALTH_STORE_AUDIO: bool = _get_env_bool("VOICE_AUDIO_HEALTH_STORE_AUDIO", False)

VOICE_LOCAL_VAD_MODE: str = _get_env_str("VOICE_LOCAL_VAD_MODE", "continuous")
VOICE_LOCAL_VAD_ALLOW_DEGRADED_FALLBACK: bool = _get_env_bool("VOICE_LOCAL_VAD_ALLOW_DEGRADED_FALLBACK", True)
VOICE_VAD_TRAILING_AUDIO_MS: int = _get_env_int("VOICE_VAD_TRAILING_AUDIO_MS", 400)

VOICE_DEEPGRAM_FINALIZE_TIMEOUT_MS: int = _get_env_int("VOICE_DEEPGRAM_FINALIZE_TIMEOUT_MS", 1200)
VOICE_DEEPGRAM_MAX_UTTERANCE_MS: int = _get_env_int("VOICE_DEEPGRAM_MAX_UTTERANCE_MS", 10000)
VOICE_MIC_START_TIMEOUT_SECONDS: float = _get_env_float("VOICE_MIC_START_TIMEOUT_SECONDS", 15.0)
VOICE_PROCESSOR_WAIT_TIMEOUT_SECONDS: float = _get_env_float("VOICE_PROCESSOR_WAIT_TIMEOUT_SECONDS", 10.0)

# ---------------------------------------------------------------------------
# Vision Umpire — feature flags (all default OFF; assisted-only baseline)
# ---------------------------------------------------------------------------
VISION_ENABLED: bool = _get_env_bool("VISION_ENABLED", False)
VISION_MODE: str = _get_env_str("VISION_MODE", "assisted")  # assisted | auto | off
VISION_CONFIDENCE_THRESHOLD: float = _get_env_float("VISION_CONFIDENCE_THRESHOLD", 0.7)
VISION_BENCHMARK_PRECISION: float = _get_env_float("VISION_BENCHMARK_PRECISION", 0.9)
