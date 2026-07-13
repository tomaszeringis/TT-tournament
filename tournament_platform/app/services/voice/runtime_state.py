"""
Voice Runtime State (Phase 1)

Centralizes the voice scorekeeper state that was previously scattered across
20+ st.session_state keys. Provides explicit snapshot/restore semantics so
Streamlit reruns are safe and debuggable.

Design rules:
- Never mutate this object from a background thread.
- Non-serializable instances (EventLogger, TTS adapter, speaker tagger) are
  re-initialized from settings on startup, not serialized.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SESSION_KEY = "voice_runtime_state"
_LOCK = threading.Lock()


@dataclass
class VoiceRuntimeState:
    """Single source of truth for voice scorekeeper UI state."""

    # ------------------------------------------------------------------ #
    # Match context
    # ------------------------------------------------------------------ #
    selected_match_id: Optional[int] = None
    selected_tournament_id: Optional[int] = None
    selected_player1_id: Optional[int] = None
    selected_player1_name: str = ""
    selected_player2_id: Optional[int] = None
    selected_player2_name: str = ""
    match_options: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Listening
    # ------------------------------------------------------------------ #
    listening: bool = False
    mode: str = "push_to_talk"  # "push_to_talk" | "continuous"
    asr_engine: str = "faster_whisper"
    asr_status: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Last event / transcript
    # ------------------------------------------------------------------ #
    last_transcript: str = ""
    last_event_hash: str = ""
    last_event_ts: float = 0.0
    last_feedback: str = ""
    last_error: str = ""

    # ------------------------------------------------------------------ #
    # Confirmation queue
    # ------------------------------------------------------------------ #
    pending_confirmations: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Duplicate suppression
    # ------------------------------------------------------------------ #
    cooldown_until_ts: float = 0.0
    last_applied_event_key: Optional[str] = None
    last_applied_event_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # Mic / noise
    # ------------------------------------------------------------------ #
    mic_calibration: Dict[str, Any] = field(default_factory=dict)
    noise_filtering: bool = False
    noise_threshold: float = 0.0
    strict_mode: bool = False
    last_chunk_rms: float = 0.0
    rms_samples: List[float] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Command log (bounded)
    # ------------------------------------------------------------------ #
    command_log: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Parsed result cache (for UI)
    # ------------------------------------------------------------------ #
    parsed_result: Optional[Dict[str, Any]] = None
    score_input: str = "0-0"

    # ------------------------------------------------------------------ #
    # Dataset recorder
    # ------------------------------------------------------------------ #
    dataset_record_audio: bool = False

    # ------------------------------------------------------------------ #
    # Commentary / spoken feedback
    # ------------------------------------------------------------------ #
    commentary_enabled: bool = False
    commentary_style: str = "neutral"
    commentary_verbosity: str = "standard"
    commentary_voice: str = "default"
    commentary_language: str = "en"
    commentary_muted: bool = False
    pending_commentary: Optional[Dict[str, Any]] = None
    last_commentary_event_id: Optional[str] = None
    last_commentary_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for session_state storage."""
        data = copy.deepcopy(self.__dict__)
        # Drop non-serializable runtime instances if any snuck in.
        data.pop("event_logger", None)
        data.pop("tts_adapter", None)
        data.pop("speaker_tagger", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceRuntimeState":
        """Rebuild from a plain dict."""
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


def _get_session_state(session_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the streamlit session_state dict, or the provided test double."""
    if session_state is not None:
        return session_state
    import streamlit as st
    return st.session_state


def get_state(session_state: Optional[Dict[str, Any]] = None) -> VoiceRuntimeState:
    """Return the current VoiceRuntimeState, initializing if needed."""
    ss = _get_session_state(session_state)
    with _LOCK:
        raw = ss.get(_SESSION_KEY)
        if raw is None:
            state = VoiceRuntimeState()
            _save_state(state, ss)
            return state
        if isinstance(raw, dict):
            return VoiceRuntimeState.from_dict(raw)
        return raw


def set_state(state: VoiceRuntimeState, session_state: Optional[Dict[str, Any]] = None) -> None:
    """Persist the given VoiceRuntimeState to session_state."""
    ss = _get_session_state(session_state)
    _save_state(state, ss)


def _save_state(state: VoiceRuntimeState, ss: Dict[str, Any]) -> None:
    ss[_SESSION_KEY] = state.to_dict()


def reset_state(session_state: Optional[Dict[str, Any]] = None) -> VoiceRuntimeState:
    """Reset to a fresh state and return it."""
    ss = _get_session_state(session_state)
    with _LOCK:
        ss[_SESSION_KEY] = None
    return VoiceRuntimeState()


def migrate_from_session_state(session_state: Optional[Dict[str, Any]] = None) -> None:
    """One-time migration from legacy scattered keys to VoiceRuntimeState."""
    ss = _get_session_state(session_state)
    state = get_state(ss)
    if (
        state.selected_match_id is not None
        or state.last_transcript
        or state.pending_confirmations
    ):
        return

    legacy_map = {
        "voice_selected_match_id": "selected_match_id",
        "voice_selected_tournament_id": "selected_tournament_id",
        "voice_selected_player1_id": "selected_player1_id",
        "voice_selected_player1_name": "selected_player1_name",
        "voice_selected_player2_id": "selected_player2_id",
        "voice_selected_player2_name": "selected_player2_name",
        "voice_match_options": "match_options",
        "voice_listening": "listening",
        "voice_scoring_enabled": None,
        "last_voice_transcript": "last_transcript",
        "last_voice_feedback": "last_feedback",
        "voice_noise_filtering": "noise_filtering",
        "voice_noise_threshold": "noise_threshold",
        "voice_strict_mode": "strict_mode",
        "voice_rms_samples": "rms_samples",
        "voice_last_chunk_rms": "last_chunk_rms",
        "voice_parsed_result": "parsed_result",
        "voice_score_input": "score_input",
        "voice_last_applied_event_key": "last_applied_event_key",
        "voice_last_applied_event_ts": "last_applied_event_ts",
        "pending_confirmations": "pending_confirmations",
        "voice_dataset_record_audio": "dataset_record_audio",
        "commentary_enabled": "commentary_enabled",
        "commentary_style": "commentary_style",
        "commentary_verbosity": "commentary_verbosity",
        "commentary_voice": "commentary_voice",
        "commentary_language": "commentary_language",
        "commentary_muted": "commentary_muted",
        "pending_commentary": "pending_commentary",
        "last_commentary_event_id": "last_commentary_event_id",
        "last_commentary_text": "last_commentary_text",
    }

    migrated = False
    for legacy_key, new_key in legacy_map.items():
        if legacy_key in ss and new_key:
            setattr(state, new_key, ss[legacy_key])
            migrated = True

    if migrated:
        logger.info("Migrated legacy voice session_state keys to VoiceRuntimeState")
        _save_state(state, ss)


def sync_legacy_keys(state: VoiceRuntimeState, session_state: Optional[Dict[str, Any]] = None) -> None:
    """Write key fields back to legacy session_state keys for compatibility."""
    ss = _get_session_state(session_state)
    with _LOCK:
        ss["voice_selected_match_id"] = state.selected_match_id
        ss["voice_selected_tournament_id"] = state.selected_tournament_id
        ss["voice_selected_player1_id"] = state.selected_player1_id
        ss["voice_selected_player1_name"] = state.selected_player1_name
        ss["voice_selected_player2_id"] = state.selected_player2_id
        ss["voice_selected_player2_name"] = state.selected_player2_name
        ss["voice_match_options"] = state.match_options
        ss["voice_listening"] = state.listening
        ss["last_voice_transcript"] = state.last_transcript
        ss["last_voice_feedback"] = state.last_feedback
        ss["voice_noise_filtering"] = state.noise_filtering
        ss["voice_noise_threshold"] = state.noise_threshold
        ss["voice_strict_mode"] = state.strict_mode
        ss["voice_rms_samples"] = state.rms_samples
        ss["voice_last_chunk_rms"] = state.last_chunk_rms
        ss["voice_parsed_result"] = state.parsed_result
        ss["voice_score_input"] = state.score_input
        ss["voice_last_applied_event_key"] = state.last_applied_event_key
        ss["voice_last_applied_event_ts"] = state.last_applied_event_ts
        ss["pending_confirmations"] = state.pending_confirmations
        ss["voice_dataset_record_audio"] = state.dataset_record_audio
        ss["commentary_enabled"] = state.commentary_enabled
        ss["commentary_style"] = state.commentary_style
        ss["commentary_verbosity"] = state.commentary_verbosity
        ss["commentary_voice"] = state.commentary_voice
        ss["commentary_language"] = state.commentary_language
        ss["commentary_muted"] = state.commentary_muted
        ss["pending_commentary"] = state.pending_commentary
        ss["last_commentary_event_id"] = state.last_commentary_event_id
        ss["last_commentary_text"] = state.last_commentary_text
