"""
Regression tests for the "voice stops scoring after Game 1" bug.

These exercise the real page helpers (canonical apply path, game-boundary
reset, rerun request) and the service-layer dedup so the first voice
command of Game 2 is never suppressed as a duplicate of the last command
of Game 1.

Import strategy mirrors a bare import (no browser/audio): Streamlit and a
few optional UI extras are stubbed, and the real scoring services run.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal Streamlit + ecosystem stubs so the page module imports without a
# browser or audio device.
# ---------------------------------------------------------------------------


class _SessionStateProxy(dict):
    """Dict that also supports attribute access, like real Streamlit session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


_streamlit = MagicMock()
_streamlit.session_state = _SessionStateProxy()
_streamlit.rerun = MagicMock()
_streamlit.experimental_rerun = MagicMock()
_streamlit.warning = MagicMock()
_streamlit.success = MagicMock()
_streamlit.info = MagicMock()
_streamlit.caption = MagicMock()
_streamlit.toast = MagicMock()
_streamlit.button = MagicMock(return_value=False)
_streamlit.toggle = MagicMock(return_value=False)
_streamlit.checkbox = MagicMock(return_value=False)
_streamlit.number_input = MagicMock(return_value=0.0)
_streamlit.selectbox = MagicMock(return_value="")
_streamlit.audio_input = MagicMock(return_value=None)
_streamlit.runtime = MagicMock()
_streamlit.runtime.scriptrunner = MagicMock()
_streamlit.runtime.scriptrunner.get_script_run_ctx = MagicMock(return_value=None)
_streamlit.components = MagicMock()
_streamlit.components.v1 = MagicMock()

sys.modules["streamlit"] = _streamlit
sys.modules["streamlit.runtime.scriptrunner"] = _streamlit.runtime.scriptrunner
sys.modules["streamlit.components"] = _streamlit.components
sys.modules["streamlit.components.v1"] = _streamlit.components.v1

_optional_ui = [
    "streamlit_shadcn_ui",
    "streamlit_shadcn_ui.py_components",
    "streamlit_shadcn_ui.py_components.select",
    "streamlit_extras",
    "streamlit_extras.stylable_container",
]
for _m in _optional_ui:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

for _mod in list(sys.modules.keys()):
    if "voice_scorekeeper" in _mod:
        del sys.modules[_mod]


def _import_page():
    # The page imports cleanly with Streamlit stubbed. No DB/selector patches
    # are required for these scoring-path tests (MatchManager uses an in-memory
    # engine and only touches the DB when persisting a submitted result).
    import tournament_platform.app.pages.voice_scorekeeper as vs

    return vs


def _seed_two_player_match(vs):
    mm = vs.st.session_state.match_manager
    # Player A wins Game 1, 11-7. Interleave so B reaches 7 before
    # A's 11th point (otherwise B's extra points fall into Game 2).
    for _ in range(7):
        mm._add_point("A")
        mm._add_point("B")
    for _ in range(4):
        mm._add_point("A")
    return mm


@pytest.fixture()
def page(monkeypatch):
    vs = _import_page()
    vs.st = _streamlit  # alias used by the page code
    # Fresh session state for each test.
    from tournament_platform.services.match_manager import MatchManager
    from tournament_platform.app.services.voice.confirmation import (
        VoiceConfirmationStateMachine,
    )
    from tournament_platform.app.services.voice_audit import EventLogger

    ss = _SessionStateProxy({
        "match_manager": MatchManager(),
        "voice_scoring_enabled": True,
        "voice_listening": False,
        "quick_voice_mode": "off",
        "voice_strict_mode": False,
        "voice_noise_filtering": False,
        "voice_noise_threshold": 0.0,
        "voice_last_applied_event_key": None,
        "voice_last_applied_event_ts": 0.0,
        "last_applied_voice_event_ids": [],
        "quick_voice_last_player": None,
        "quick_voice_last_ts": 0.0,
        "voice_confirmation_machine": VoiceConfirmationStateMachine(ttl_seconds=8.0),
        "pending_confirmations": [],
        "last_voice_transcript": "",
        "last_voice_event": None,
        "last_voice_feedback": "",
        "voice_event_log": [],
        "voice_event_logger": EventLogger(),
        "voice_selected_match_id": 1,
        "voice_selected_player1_name": "Red",
        "voice_selected_player2_name": "Blue",
        "voice_selected_player1_id": 1,
        "voice_selected_player2_id": 2,
        "completed_games": [],
        "match_complete": False,
        "pending_result_submission": False,
        "result_submitted": False,
        "_voice_needs_rerun": False,
        "_voice_rerun_reason": "",
    })
    monkeypatch.setattr(vs, "st", _streamlit)
    _streamlit.session_state = ss
    yield vs, ss


class TestVoiceContinuesAfterFirstGame:
    def test_quick_voice_blue_after_game_one_increments(self, page):
        vs, ss = page
        mm = _seed_two_player_match(vs)
        assert mm.engine.games_won_a == 1
        assert mm.engine.score_a == 0
        assert mm.engine.match_status == "game_won"

        # Simulate a "blue" utterance recognized in Quick Voice mode at Game 2 start.
        vs.st.session_state.quick_voice_mode = "quick"
        vs._process_quick_voice_event("blue")

        assert mm.engine.score_a == 1
        assert mm.engine.score_b == 0
        assert mm.engine.match_status == "in_progress"
        # Same phrase must not have been suppressed on the new game.
        assert ss["quick_voice_last_status"] == "accepted"

    def test_full_voice_point_player_one_after_game_one(self, page):
        vs, ss = page
        mm = _seed_two_player_match(vs)
        assert mm.engine.games_won_a == 1
        assert mm.engine.score_a == 0

        result = vs._process_voice_transcript(
            "point player one", source="debug", enable_confirmation=False
        )
        assert result["success"] is True
        assert mm.engine.score_a == 1
        assert mm.engine.score_b == 0

    def test_full_voice_point_player_two_after_game_one(self, page):
        vs, ss = page
        mm = _seed_two_player_match(vs)
        result = vs._process_voice_transcript(
            "point player two", source="debug", enable_confirmation=False
        )
        assert result["success"] is True
        assert mm.engine.score_b == 1

    def test_duplicate_cooldown_does_not_block_next_game(self, page):
        vs, ss = page
        mm = _seed_two_player_match(vs)
        # Repeat the last Game 1 command ("blue") at the very start of Game 2.
        # With game-index-aware dedup this must be accepted, not ignored.
        result = vs._process_voice_transcript(
            "blue", source="debug", enable_confirmation=False
        )
        assert result["success"] is True
        assert result["reason"] != "duplicate_suppressed"
        assert mm.engine.score_a == 1

    def test_voice_off_blocks_commands(self, page):
        vs, ss = page
        mm = _seed_two_player_match(vs)
        ss["voice_scoring_enabled"] = False
        result = vs._process_voice_transcript(
            "blue", source="webrtc", enable_confirmation=False
        )
        assert result["success"] is False
        assert result["reason"] == "voice_scoring_disabled"
        assert mm.engine.score_a == 0

    def test_apply_requests_rerun(self, page):
        vs, ss = page
        _seed_two_player_match(vs)
        result = vs._process_voice_transcript(
            "point player one", source="debug", enable_confirmation=False
        )
        assert result["success"] is True
        assert ss["_voice_needs_rerun"] is True

    def test_game_boundary_reset_clears_dedup(self, page):
        vs, ss = page
        # Simulate a stale last-applied key from Game 1.
        ss["voice_last_applied_event_key"] = "deadbeef"
        ss["voice_last_applied_event_ts"] = __import__("time").time()
        ss["quick_voice_last_player"] = "A"
        ss["quick_voice_last_ts"] = __import__("time").time()
        vs._reset_voice_game_boundary_state()
        assert ss["voice_last_applied_event_key"] is None
        assert ss["voice_last_applied_event_ts"] == 0.0
        assert ss["quick_voice_last_player"] is None

    def test_match_complete_blocks_voice(self, page):
        vs, ss = page
        mm = vs.st.session_state.match_manager
        # Best-of-1 so the first completed game ends the match.
        mm.apply_format(11, 1, "A")
        from tournament_platform.app.services.score_engine import set_score

        set_score(mm.engine, 11, 0)
        assert mm.engine.match_status == "match_won"
        result = vs._process_voice_transcript(
            "point player one", source="debug", enable_confirmation=False
        )
        assert result["success"] is False
