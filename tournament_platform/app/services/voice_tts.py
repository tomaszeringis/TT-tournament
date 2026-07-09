"""
Voice TTS Confirmation (Phase 4)

Offline-first text-to-speech adapter for voice scorekeeping confirmations.
Modes:
- off: no TTS
- visual_only: no audio, just visual feedback (default when enabled)
- audio_after_game: speak after each completed game
- audio_every_score: speak after every accepted score event
- audio_on_uncertainty: speak only when confidence is low or confirmation is required

The adapter is feature-flagged via VOICE_ENABLE_TTS_CONFIRMATION and
VOICE_TTS_MODE. It never blocks scoring; TTS runs in a background thread
and its output is never routed back to the ASR.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TTSMode(str, Enum):
    """TTS feedback modes."""
    OFF = "off"
    VISUAL_ONLY = "visual_only"
    AUDIO_AFTER_GAME = "audio_after_game"
    AUDIO_EVERY_SCORE = "audio_every_score"
    AUDIO_ON_UNCERTAINTY = "audio_on_uncertainty"


class TTSProvider(str, Enum):
    """TTS backend providers."""
    OFFLINE = "offline"
    CLOUD = "cloud"  # placeholder; not implemented


class TTSConfirmationAdapter:
    """
    Offline-first TTS adapter for voice scorekeeping.

    Uses pyttsx3 for offline speech. Cloud providers are not implemented
    but the interface allows future extension.
    """

    def __init__(
        self,
        mode: str = TTSMode.VISUAL_ONLY.value,
        provider: str = TTSProvider.OFFLINE.value,
        enabled: bool = False,
    ):
        self.mode = TTSMode(mode) if mode else TTSMode.OFF
        self.provider = TTSProvider(provider) if provider else TTSProvider.OFFLINE
        self.enabled = enabled
        self._speak_queue: list[str] = []
        self._lock = threading.Lock()

    def should_speak(self, event_type: str, confidence: float = 1.0, requires_confirmation: bool = False) -> bool:
        """
        Determine whether TTS should speak for the given event.

        Args:
            event_type: The voice event type (increment, set_score, undo, etc.)
            confidence: ASR confidence (0.0–1.0)
            requires_confirmation: Whether the event requires explicit confirmation

        Returns:
            True if TTS should produce audio for this event.
        """
        if not self.enabled or self.mode == TTSMode.OFF:
            return False
        if self.mode == TTSMode.VISUAL_ONLY:
            return False
        if self.mode == TTSMode.AUDIO_AFTER_GAME:
            return event_type in ("game_won", "match_won")
        if self.mode == TTSMode.AUDIO_EVERY_SCORE:
            return event_type in ("increment", "set_score", "undo")
        if self.mode == TTSMode.AUDIO_ON_UNCERTAINTY:
            return confidence < 0.7 or requires_confirmation
        return False

    def speak(self, text: str, *, blocking: bool = False) -> None:
        """
        Speak the given text.

        Args:
            text: The text to speak.
            blocking: If True, block until speech completes (not recommended in Streamlit).
        """
        if not self.enabled or self.mode == TTSMode.OFF or self.mode == TTSMode.VISUAL_ONLY:
            return
        if not text:
            return

        if blocking:
            self._speak_sync(text)
        else:
            threading.Thread(
                target=self._speak_sync,
                args=(text,),
                daemon=True,
            ).start()

    def _speak_sync(self, text: str) -> None:
        """Synchronous speech in a background thread."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
            engine.setProperty("volume", 0.9)
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            logger.debug("TTS suppressed (%s): %s", self.provider, exc)

    def queue(self, text: str) -> None:
        """Queue text for later speaking (used for batch confirmations)."""
        with self._lock:
            self._speak_queue.append(text)

    def flush_queue(self) -> None:
        """Speak all queued texts and clear the queue."""
        with self._lock:
            texts = list(self._speak_queue)
            self._speak_queue.clear()
        for text in texts:
            self.speak(text)
