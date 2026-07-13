"""
Tests for the Live Scoreboard audio controls (Sound cues + TTS).

Covers Fix A (sound preference in st.session_state), Fix B/C (TTS routed to
the browser via spoken_commentary, opt-in pyttsx3), Fix D (friendly TTS
labels + functional dropdown), and the "Test sound" helpers not mutating state.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from tournament_platform.app.services import audio_cues
from tournament_platform.app.services.voice_tts import (
    TTSConfirmationAdapter,
    TTSMode,
)


# ---------------------------------------------------------------------------
# Streamlit stub installed into sys.modules (the helpers `import streamlit`
# locally, so patching sys.modules is the reliable hook). The session_state
# proxy supports both dict-style and attribute-style access, like real Streamlit.
# ---------------------------------------------------------------------------
class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


_streamlit = MagicMock()
_streamlit.session_state = _SessionState()
_components_v1 = MagicMock()
_components_v1.html = MagicMock()
_streamlit.components = MagicMock()
_streamlit.components.v1 = _components_v1
sys.modules["streamlit"] = _streamlit


def _set_session(state: dict) -> None:
    _streamlit.session_state = _SessionState(state)
    _streamlit.checkbox.reset_mock()
    _streamlit.rerun.reset_mock()
    _components_v1.html.reset_mock()


def _enabled_adapter(mode):
    return TTSConfirmationAdapter(enabled=True, mode=mode.value)


# ---------------------------------------------------------------------------
# Fix A — sound cues stored per-session in st.session_state
# ---------------------------------------------------------------------------

class TestSoundCuesSessionState:
    def test_toggle_writes_session_state_not_only_env(self):
        from tournament_platform.app.services import ui_feedback as uf

        os.environ.pop("SCORE_ENABLE_SOUNDS", None)
        _set_session({})
        _streamlit.checkbox.return_value = True

        uf.render_sound_toggle()

        assert _streamlit.session_state.get("sound_cues_enabled") is True
        assert os.environ.get("SCORE_ENABLE_SOUNDS") == "true"

    def test_play_cue_reads_session_state(self):
        from tournament_platform.app.services import ui_feedback as uf

        os.environ.pop("SCORE_ENABLE_SOUNDS", None)
        _set_session({"sound_cues_enabled": True})

        uf.play_cue("point")
        assert _components_v1.html.called

        _components_v1.html.reset_mock()
        _streamlit.session_state["sound_cues_enabled"] = False
        uf.play_cue("point")
        assert not _components_v1.html.called

    def test_sound_preference_survives_rerun(self):
        from tournament_platform.app.services import ui_feedback as uf

        # Another session/restart flips the env to false; the per-user session
        # preference must win on rerun (Streamlit preserves the widget value).
        os.environ["SCORE_ENABLE_SOUNDS"] = "false"
        _set_session({})
        _streamlit.checkbox.return_value = True
        uf.render_sound_toggle()  # user turns on -> session True, env true
        os.environ["SCORE_ENABLE_SOUNDS"] = "false"
        _streamlit.checkbox.return_value = True  # preserved across rerun
        uf.render_sound_toggle()

        assert _streamlit.session_state.get("sound_cues_enabled") is True


# ---------------------------------------------------------------------------
# Fix B/C — TTS routed to browser spoken_commentary
# ---------------------------------------------------------------------------

class TestTTSToBrowser:
    def test_maybe_speak_routes_to_browser_when_should_speak(self):
        _set_session(
            {"voice_tts_adapter": _enabled_adapter(TTSMode.AUDIO_EVERY_SCORE)}
        )
        with patch(
            "tournament_platform.app.services.audio_cues.speak_commentary"
        ) as mock_speak:
            audio_cues.maybe_speak_tts("Red leads 5 to 3", "increment")
            mock_speak.assert_called_once()
            _, kwargs = mock_speak.call_args
            assert kwargs["key"].startswith("tts_increment_")

    def test_maybe_speak_is_noop_when_should_not_speak(self):
        _set_session(
            {"voice_tts_adapter": _enabled_adapter(TTSMode.AUDIO_EVERY_SCORE)}
        )
        with patch(
            "tournament_platform.app.services.audio_cues.speak_commentary"
        ) as mock_speak:
            audio_cues.maybe_speak_tts("some text", "unknown")
            mock_speak.assert_not_called()

    def test_maybe_speak_is_noop_when_disabled(self):
        _set_session(
            {
                "voice_tts_adapter": TTSConfirmationAdapter(
                    enabled=False, mode=TTSMode.AUDIO_EVERY_SCORE.value
                )
            }
        )
        with patch(
            "tournament_platform.app.services.audio_cues.speak_commentary"
        ) as mock_speak:
            audio_cues.maybe_speak_tts("Red leads 5 to 3", "increment")
            mock_speak.assert_not_called()

    def test_maybe_speak_is_noop_when_no_adapter(self):
        _set_session({})
        with patch(
            "tournament_platform.app.services.audio_cues.speak_commentary"
        ) as mock_speak:
            audio_cues.maybe_speak_tts("Red leads 5 to 3", "increment")
            mock_speak.assert_not_called()


# ---------------------------------------------------------------------------
# Fix D — friendly TTS dropdown labels + functional enabled flip
# ---------------------------------------------------------------------------

class TestTTSDropdown:
    def test_options_are_friendly_labels_not_raw_values(self):
        values, labels = audio_cues.tts_mode_options()
        assert "audio_every_score" not in labels
        assert "Every score" in labels
        assert "Off" in labels
        for label in labels:
            assert label in audio_cues.TTS_FRIENDLY_LABELS.values()

    def test_apply_selection_enables_non_off_mode(self):
        adapter = TTSConfirmationAdapter(enabled=False, mode=TTSMode.OFF.value)
        audio_cues.apply_tts_selection(adapter, TTSMode.AUDIO_AFTER_GAME.value)
        assert adapter.mode == TTSMode.AUDIO_AFTER_GAME
        assert adapter.enabled is True

    def test_apply_selection_disables_off(self):
        adapter = TTSConfirmationAdapter(
            enabled=True, mode=TTSMode.AUDIO_EVERY_SCORE.value
        )
        audio_cues.apply_tts_selection(adapter, TTSMode.OFF.value)
        assert adapter.mode == TTSMode.OFF
        assert adapter.enabled is False


# ---------------------------------------------------------------------------
# Test sound helpers — never mutate match state or the DB
# ---------------------------------------------------------------------------

class TestTestSoundHelpers:
    def test_build_message_does_not_mutate_state(self):
        from tournament_platform.services.match_manager import MatchManager

        mm = MatchManager()
        mm._add_point("A")
        mm._add_point("A")
        score_before = mm.state.get_score_string()
        history_before = len(mm.state.match_history)

        msg = audio_cues.build_test_tts_message(mm)

        assert isinstance(msg, str) and msg
        assert mm.state.get_score_string() == score_before
        assert len(mm.state.match_history) == history_before

    def test_maybe_speak_does_not_mutate_state(self):
        from tournament_platform.services.match_manager import MatchManager

        mm = MatchManager()
        mm._add_point("A")
        mm._add_point("A")
        _set_session(
            {"voice_tts_adapter": _enabled_adapter(TTSMode.AUDIO_EVERY_SCORE)}
        )
        score_before = mm.state.get_score_string()
        history_before = len(mm.state.match_history)

        with patch(
            "tournament_platform.app.services.audio_cues.speak_commentary"
        ):
            msg = audio_cues.build_test_tts_message(mm)
            audio_cues.maybe_speak_tts(msg, "increment")

        assert mm.state.get_score_string() == score_before
        assert len(mm.state.match_history) == history_before
