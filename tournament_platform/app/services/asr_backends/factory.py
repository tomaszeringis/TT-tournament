"""
ASR Backend Factory

Selects and instantiates the configured ASR backend based on environment
variables. Provides fallback logic when the preferred backend is unavailable.
"""

from __future__ import annotations

import logging
from typing import Optional

from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.app.services.asr_backends.faster_whisper_backend import FasterWhisperBackend
from tournament_platform.app.services.voice_vocab import VoiceVocabulary

logger = logging.getLogger(__name__)

_BACKENDS: dict[str, type[ASRBackend]] = {}
try:
    from tournament_platform.app.services.asr_backends.speechbrain_backend import SpeechBrainBackend

    _BACKENDS["speechbrain"] = SpeechBrainBackend
except Exception:
    pass

_BACKENDS["faster_whisper"] = FasterWhisperBackend


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
    def backend_status(backend_name: Optional[str] = None) -> BackendStatus:
        try:
            backend = ASRBackendFactory.create(backend_name=backend_name)
            return backend.get_status()
        except Exception as e:
            return BackendStatus(
                backend_name=backend_name or "unknown",
                available=False,
                load_error=str(e),
            )
