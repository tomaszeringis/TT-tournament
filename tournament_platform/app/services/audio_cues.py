"""
Audio controls for the Live Scoreboard — Sound cues + browser-native TTS.

Extracted from ``voice_scorekeeper.py`` so the wiring (TTS label mapping,
mode→enabled selection, and browser speech routing) is unit-testable without
importing the full page (which pulls on the whole Streamlit/audio stack).

Key guarantees:
- Sound preferences live in ``st.session_state`` (per-user), not process env.
- TTS is routed to the operator's browser via ``spoken_commentary``
  (Web Speech API); server-side ``pyttsx3`` is an opt-in fallback only.
- Selecting a TTS mode also flips ``enabled`` so the dropdown is functional.
"""

from __future__ import annotations

import logging

from tournament_platform.app.components.spoken_commentary import speak_commentary
from tournament_platform.app.services.voice_tts import TTSMode

logger = logging.getLogger(__name__)

# Friendly TTS dropdown labels mapped to the internal TTSMode values.
TTS_FRIENDLY_LABELS = {
    "off": "Off",
    "visual_only": "Visual only (no sound)",
    "audio_every_score": "Every score",
    "audio_after_game": "Game end only",
    "audio_on_uncertainty": "Important events only",
}


def tts_mode_options() -> tuple:
    """Return (internal_values, friendly_labels) for the TTS selectbox."""
    values = [m.value for m in TTSMode]
    labels = [TTS_FRIENDLY_LABELS.get(v, v) for v in values]
    return values, labels


def apply_tts_selection(adapter, new_mode_value: str):
    """Apply a selected TTS mode to the adapter.

    Selecting any mode other than ``off`` enables speech; ``off`` disables it.
    This is what makes the dropdown functional for end users.
    """
    adapter.mode = TTSMode(new_mode_value)
    adapter.enabled = (new_mode_value != "off")
    return adapter


def maybe_speak_tts(
    text: str,
    event_type: str,
    adapter=None,
    confidence: float = 1.0,
    requires_confirmation: bool = False,
) -> None:
    """Route a spoken confirmation to the browser, if the TTS mode allows it.

    Audio is synthesized in the operator's browser via the Web Speech API
    (``spoken_commentary``), never on the server, so the user actually hears
    the confirmation in a Streamlit web deployment. Runs synchronously in the
    current callback (not a background thread) so the ``components.html``
    fragment is emitted before any ``st.rerun()``.
    """
    if not text:
        return
    if adapter is None:
        import streamlit as st
        adapter = st.session_state.get("voice_tts_adapter")
    if adapter is None:
        return
    if not adapter.should_speak(
        event_type,
        confidence=confidence,
        requires_confirmation=requires_confirmation,
    ):
        return
    import time
    key = f"tts_{event_type}_{abs(hash(text))}_{int(time.time() * 1000)}"
    try:
        speak_commentary(text, key=key)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Browser TTS suppressed: %s", exc)


def build_test_tts_message(match_manager) -> str:
    """Build a sample spoken-score line from the current match state."""
    state = match_manager.state
    _a = state.player_a
    _b = state.player_b
    _sa = state.score_a
    _sb = state.score_b
    if _sa == _sb:
        return f"{_a} {_sa} to {_sb} {_b}. Scores level."
    _leader = _a if _sa > _sb else _b
    return f"{_leader} leads {max(_sa, _sb)} to {min(_sa, _sb)}."
