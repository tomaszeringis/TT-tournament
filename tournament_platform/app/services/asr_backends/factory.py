"""
ASR Backend Factory

Selects and instantiates the configured ASR backend based on environment
variables. Provides fallback logic when the preferred backend is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.app.services.asr_backends.faster_whisper_backend import FasterWhisperBackend
from tournament_platform.app.services.asr_backends.vosk_adapter import VoskGrammarASR
from tournament_platform.app.services.voice_vocab import VoiceVocabulary

logger = logging.getLogger(__name__)

_BACKENDS: dict[str, type[ASRBackend]] = {}
_STREAMING_BACKENDS: dict[str, type] = {}
try:
    from tournament_platform.app.services.asr_backends.speechbrain_backend import SpeechBrainBackend

    _BACKENDS["speechbrain"] = SpeechBrainBackend
except Exception:
    pass

_BACKENDS["faster_whisper"] = FasterWhisperBackend
_BACKENDS["vosk"] = VoskGrammarASR

try:
    from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

    _STREAMING_BACKENDS["deepgram"] = DeepgramASRBackend
except Exception:
    pass


@dataclass(frozen=True)
class StreamingBackendResult:
    """Structured result from streaming backend creation.

    Replaces silent ``None`` returns with a safe, actionable result.
    Never contains API keys, authorization headers, or raw provider URLs.
    """

    available: bool
    reason_code: Optional[str] = None
    safe_message: str = ""
    backend: Optional[object] = None

    @staticmethod
    def not_configured(reason_code: str, safe_message: str) -> "StreamingBackendResult":
        return StreamingBackendResult(
            available=False,
            reason_code=reason_code,
            safe_message=safe_message,
        )

    @staticmethod
    def configured(backend: object) -> "StreamingBackendResult":
        return StreamingBackendResult(
            available=True,
            reason_code=None,
            safe_message=f"Using streaming ASR backend: {getattr(backend, 'backend_name', type(backend).__name__)}",
            backend=backend,
        )


@dataclass(frozen=True)
class StreamingBackendStatus:
    """Structured availability status for a streaming backend.

    Separates registration, installation, enablement, credentials, and
    configuration validity so the UI can show precise guidance.
    Never contains API keys or raw exception text.
    """

    provider: str
    registered: bool = False
    sdk_available: bool = False
    enabled: bool = False
    credentials_configured: bool = False
    config_valid: bool = False
    reason_code: Optional[str] = None
    safe_message: Optional[str] = None

    @property
    def available(self) -> bool:
        """True only when all layers are satisfied (no live connection check)."""
        return (
            self.registered
            and self.sdk_available
            and self.enabled
            and self.credentials_configured
            and self.config_valid
            and self.reason_code is None
        )


class ASRBackendFactory:
    """
    Factory for creating ASR backends.

    Reads VOICE_ASR_BACKEND from environment variables (default: faster_whisper).
    If the requested backend fails to instantiate and
    VOICE_ASR_FALLBACK_BACKEND is set, the factory falls back to that backend.
    """

    @staticmethod
    def create(
        backend_name: Optional[str] = None,
        vocabulary: Optional[VoiceVocabulary] = None,
    ) -> ASRBackend:
        import os

        name = backend_name or os.environ.get("VOICE_ASR_BACKEND", "faster_whisper").lower().strip()
        name = name.replace("-", "_")

        if name == "deepgram":
            name = "faster_whisper"
            logger.warning(
                "VOICE_ASR_BACKEND=deepgram is deprecated for batch selection. "
                "Deepgram is a streaming-only provider. "
                "Use VOICE_STREAMING_ASR_BACKEND=deepgram for streaming, "
                "and VOICE_ASR_BACKEND=faster_whisper for batch."
            )

        fallback_name = os.environ.get("VOICE_ASR_FALLBACK_BACKEND", "").lower().strip().replace("-", "_")

        backend_cls = _BACKENDS.get(name)
        if backend_cls is None:
            logger.warning("Unknown ASR backend '%s', falling back to faster_whisper", name)
            backend_cls = FasterWhisperBackend

        try:
            backend = backend_cls(vocabulary=vocabulary)
            if backend.is_available():
                logger.info("Using ASR backend: %s", backend.backend_name)
                return backend
            logger.warning(
                "ASR backend '%s' is not available: %s",
                backend.backend_name,
                backend.get_status().load_error,
            )
        except Exception as e:
            logger.warning("Failed to initialize ASR backend '%s': %s", name, e)

        if fallback_name and fallback_name in _BACKENDS:
            try:
                fallback_cls = _BACKENDS[fallback_name]
                fallback_backend = fallback_cls(vocabulary=vocabulary)
                if fallback_backend.is_available():
                    logger.info("Falling back to ASR backend: %s", fallback_backend.backend_name)
                    return fallback_backend
                logger.warning(
                    "Fallback ASR backend '%s' is not available: %s",
                    fallback_backend.backend_name,
                    fallback_backend.get_status().load_error,
                )
            except Exception as e:
                logger.warning("Failed to initialize fallback ASR backend '%s': %s", fallback_name, e)

        logger.warning("No ASR backend available, returning %s", FasterWhisperBackend.backend_name)
        return FasterWhisperBackend(vocabulary=vocabulary)

    @staticmethod
    def create_streaming(
        backend_name: Optional[str] = None,
    ) -> StreamingBackendResult:
        """Create a streaming ASR backend (e.g. Deepgram).

        Returns a structured result with availability and reason code.
        Never returns bare ``None`` — the caller always gets an explicit
        available flag and a safe message.
        """
        import os

        name = backend_name or os.environ.get("VOICE_STREAMING_ASR_BACKEND", "").lower().strip()
        name = name.replace("-", "_")

        if not name:
            legacy_name = os.environ.get("VOICE_ASR_BACKEND", "").lower().strip().replace("-", "_")
            if legacy_name == "deepgram":
                logger.warning(
                    "VOICE_ASR_BACKEND=deepgram is deprecated for streaming selection. "
                    "Use VOICE_STREAMING_ASR_BACKEND=deepgram."
                )
                name = "deepgram"
            else:
                name = legacy_name

        if name not in _STREAMING_BACKENDS:
            return StreamingBackendResult.not_configured(
                reason_code="provider_not_registered",
                safe_message=(
                    f"Streaming provider '{name}' is not registered by this build. "
                    "Install the provider package and restart."
                ),
            )

        backend_cls = _STREAMING_BACKENDS[name]

        # Read configuration from environment (already loaded by settings/bootstrap)
        # Canonical name: VOICE_DEEPGRAM_API_KEY
        # Deprecated fallback: DEEPGRAM_API_KEY
        api_key = os.environ.get("VOICE_DEEPGRAM_API_KEY", "").strip()
        if not api_key:
            api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
        model = os.environ.get("VOICE_DEEPGRAM_MODEL", "nova-3").strip()
        language = os.environ.get("VOICE_DEEPGRAM_LANGUAGE", "lt").strip().lower()
        enabled = os.environ.get("VOICE_DEEPGRAM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

        if not enabled:
            return StreamingBackendResult.not_configured(
                reason_code="provider_disabled",
                safe_message=(
                    "Deepgram is disabled. "
                    "Set VOICE_DEEPGRAM_ENABLED=true in .env or process environment."
                ),
            )

        if not api_key:
            return StreamingBackendResult.not_configured(
                reason_code="api_key_missing",
                safe_message=(
                    "Deepgram API key is missing. "
                    "Set VOICE_DEEPGRAM_API_KEY in .env or Streamlit secrets."
                ),
            )

        if language not in ("lt", "en"):
            return StreamingBackendResult.not_configured(
                reason_code="invalid_configuration",
                safe_message=f"Invalid VOICE_DEEPGRAM_LANGUAGE='{language}'. Must be 'lt' or 'en'.",
            )

        try:
            endpointing_ms = int(
                float(os.environ.get("VOICE_DEEPGRAM_ENDPOINTING_MS", "300").strip())
            )
        except (TypeError, ValueError):
            endpointing_ms = 300
        endpointing_ms = max(250, min(400, endpointing_ms))

        try:
            sample_rate = int(
                float(os.environ.get("VOICE_DEEPGRAM_SAMPLE_RATE", "16000").strip())
            )
        except (TypeError, ValueError):
            sample_rate = 16000

        try:
            channels = int(
                float(os.environ.get("VOICE_DEEPGRAM_CHANNELS", "1").strip())
            )
        except (TypeError, ValueError):
            channels = 1

        keyterms_raw = os.environ.get("VOICE_DEEPGRAM_KEYTERMS", "").strip()
        keyterms = [k.strip() for k in keyterms_raw.split(",") if k.strip()] or None

        try:
            backend = backend_cls(
                api_key=api_key,
                model=model,
                language=language,
                endpointing_ms=endpointing_ms,
                sample_rate=sample_rate,
                channels=channels,
                keyterms=keyterms,
            )
        except Exception as exc:
            logger.warning("Failed to construct streaming backend '%s': %s", name, exc)
            return StreamingBackendResult.not_configured(
                reason_code="backend_creation_failed",
                safe_message=f"Failed to construct {name} backend: {type(exc).__name__}",
            )

        if backend.is_available():
            logger.info("Using streaming ASR backend: %s", backend.backend_name)
            return StreamingBackendResult.configured(backend)

        status = backend.get_status()
        reason = "invalid_configuration"
        if status.load_error and "API key" in str(status.load_error):
            reason = "api_key_missing"

        return StreamingBackendResult.not_configured(
            reason_code=reason,
            safe_message=status.load_error or f"{name} backend is not available",
        )

    @staticmethod
    def streaming_backends() -> dict[str, type]:
        """Return the dict of registered streaming backend classes."""
        return dict(_STREAMING_BACKENDS)

    @staticmethod
    def streaming_backend_status(backend_name: str = "deepgram") -> "StreamingBackendStatus":
        """Return a structured availability status for a streaming backend.

        Does NOT construct a live WebSocket connection.  Checks registration,
        SDK importability, enablement flag, and API key presence.
        """
        import os

        name = backend_name.lower().strip().replace("-", "_")
        registered = name in _STREAMING_BACKENDS

        if not registered:
            return StreamingBackendStatus(
                provider=name,
                registered=False,
                sdk_available=False,
                enabled=False,
                credentials_configured=False,
                config_valid=False,
                reason_code="provider_not_registered",
                safe_message=(
                    f"The '{name}' streaming provider is not registered by this build."
                ),
            )

        # Try to verify SDK is importable without constructing a backend
        sdk_available = False
        try:
            from deepgram import DeepgramClient  # noqa: F401
            sdk_available = True
        except ImportError:
            pass

        enabled = os.environ.get("VOICE_DEEPGRAM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
        api_key = os.environ.get("VOICE_DEEPGRAM_API_KEY", "").strip()
        if not api_key:
            api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
        credentials_configured = bool(api_key)

        language = os.environ.get("VOICE_DEEPGRAM_LANGUAGE", "lt").strip().lower()
        config_valid = language in ("lt", "en")

        if not sdk_available:
            return StreamingBackendStatus(
                provider=name,
                registered=True,
                sdk_available=False,
                enabled=enabled,
                credentials_configured=credentials_configured,
                config_valid=config_valid,
                reason_code="sdk_missing",
                safe_message=(
                    "Deepgram support is configured, but deepgram-sdk is not installed "
                    "in the active Python environment."
                ),
            )

        if not enabled:
            return StreamingBackendStatus(
                provider=name,
                registered=True,
                sdk_available=True,
                enabled=False,
                credentials_configured=credentials_configured,
                config_valid=config_valid,
                reason_code="provider_disabled",
                safe_message=(
                    "Deepgram is disabled. "
                    "Set VOICE_DEEPGRAM_ENABLED=true in .env or Streamlit secrets."
                ),
            )

        if not credentials_configured:
            return StreamingBackendStatus(
                provider=name,
                registered=True,
                sdk_available=True,
                enabled=True,
                credentials_configured=False,
                config_valid=config_valid,
                reason_code="api_key_missing",
                safe_message=(
                    "Deepgram is installed but not configured. "
                    "Set VOICE_DEEPGRAM_API_KEY in .env or Streamlit secrets."
                ),
            )

        if not config_valid:
            return StreamingBackendStatus(
                provider=name,
                registered=True,
                sdk_available=True,
                enabled=True,
                credentials_configured=True,
                config_valid=False,
                reason_code="invalid_configuration",
                safe_message=f"Invalid VOICE_DEEPGRAM_LANGUAGE='{language}'. Must be 'lt' or 'en'.",
            )

        return StreamingBackendStatus(
            provider=name,
            registered=True,
            sdk_available=True,
            enabled=True,
            credentials_configured=True,
            config_valid=True,
            reason_code=None,
            safe_message=None,
        )

    @staticmethod
    def backend_status(backend_name: Optional[str] = None) -> BackendStatus:
        import os

        name = backend_name or os.environ.get("VOICE_ASR_BACKEND", "faster_whisper").lower().strip()
        name = name.replace("-", "_")

        if name == "deepgram":
            logger.warning(
                "VOICE_ASR_BACKEND=deepgram is deprecated for batch selection. "
                "Deepgram is a streaming-only provider. "
                "Use VOICE_STREAMING_ASR_BACKEND=deepgram for streaming, "
                "and VOICE_ASR_BACKEND=faster_whisper for batch."
            )
            name = "faster_whisper"

        backend_cls = _BACKENDS.get(name)
        if backend_cls is None:
            return BackendStatus(
                backend_name=name,
                available=False,
                load_error=f"Unknown ASR backend '{name}'",
            )

        try:
            if name in _STREAMING_BACKENDS:
                api_key = os.environ.get("VOICE_DEEPGRAM_API_KEY", "").strip()
                if not api_key:
                    api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
                backend = backend_cls(api_key=api_key)
            else:
                backend = backend_cls()
            return backend.get_status()
        except Exception as e:
            return BackendStatus(
                backend_name=name,
                available=False,
                load_error=str(e),
            )
