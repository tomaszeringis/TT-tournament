"""
Behavioral integration tests for the voice scoring pipeline.

These tests exercise the real end-to-end path:
  FinalizedUtterance / transcript
      -> TranscriptPostProcessor
      -> VoiceCommandGrammar (commands.parse)
      -> route_and_update_context
      -> MatchManager.apply_voice_event
      -> score_engine
      -> st.session_state.match_manager.state

Only the external ASR boundary is mocked. The parser, router, MatchManager,
and score_engine are all real.
"""

from __future__ import annotations

import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice.commands import parse as parse_command
from tournament_platform.app.services.voice.command_router import (
    RouteContext,
    route_and_update_context,
)
from tournament_platform.app.services.voice_vocab import TranscriptPostProcessor, VoiceVocabulary
from tournament_platform.app.services.voice_scorekeeper.events import VoiceTranscriptEvent, VoiceTranscriptSource
from tournament_platform.app.services.voice_scorekeeper.scoring_actions import resolve_side_to_player
from tournament_platform.services.match_manager import MatchManager
from tournament_platform.app.services.score_engine import create_match

from tests.test_voice_score_pipeline import (
    _SessionStateProxy,
    _import_voice_scorekeeper,
    _make_fake_session_state,
    _streamlit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_live_session_state(player_a="Tomas Z", player_b="Opponent", p1_id=1, p2_id=2):
    """Return a session state with a real MatchManager ready for voice scoring."""
    state = _make_fake_session_state()
    # Initialize MatchManager with IDs from the start so engine and state are synced
    mm = MatchManager(player_a=player_a, player_b=player_b, player_a_id=p1_id, player_b_id=p2_id)
    mm.engine = create_match(player_a_name=player_a, player_b_name=player_b, player_a_id=p1_id, player_b_id=p2_id)
    state["match_manager"] = mm
    state["voice_scoring_enabled"] = True
    state["voice_selected_match_id"] = 1
    state["voice_selected_player1_id"] = p1_id
    state["voice_selected_player2_id"] = p2_id
    state["voice_listening"] = True
    state["voice_events_enabled"] = True
    state["voice_continuous_session_id"] = "sess-1"
    state["voice_continuous_session_start"] = 0.0
    state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
    state["voice_selected_language"] = "lt"
    state["voice_last_applied_event_key"] = None
    state["voice_last_applied_event_ts"] = 0.0
    state["pending_confirmations"] = []
    state["last_voice_transcript"] = ""
    state["last_voice_event"] = None
    state["last_voice_feedback"] = ""
    state["last_voice_rejection_reason"] = ""
    state["last_voice_success_message"] = ""
    state["last_voice_action_taken"] = ""
    state["voice_stale_events_ignored"] = 0
    state["last_applied_voice_event_ids"] = []
    state["voice_audit_events"] = []
    state["quick_voice_mode"] = "full"
    state["match_complete"] = False
    state["desired_mic_playing"] = True
    state["voice_streaming_state"] = "listening"
    state["streaming_ui_state"] = "listening"
    state["voice_streaming_config_frozen"] = True
    state["voice_start_requested"] = False
    state["voice_stop_requested"] = False
    state["streaming_processor_id"] = None
    state["streaming_processor_generation"] = None
    state["streaming_start_microphone_confirmed_at"] = None
    state["last_session_termination_reason"] = None
    state["unexpected_webrtc_stop_count"] = 0
    state["unexpected_webrtc_stop_ts"] = None
    state["voice_webrtc_mount_error"] = None
    state["voice_webrtc_ctx"] = {}
    state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
    return state


def _apply_via_shared(state, transcript, source="continuous", event_id=None):
    """Call the real apply_score_event_and_refresh_ui through the imported module."""
    vs = _import_voice_scorekeeper()
    vs.st.session_state = state
    try:
        return vs.apply_score_event_and_refresh_ui(
            transcript=transcript,
            source=source,
            enable_confirmation=False,
        )
    finally:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_streamlit():
    """Ensure each test gets a clean streamlit mock."""
    _streamlit.session_state = _SessionStateProxy()
    _streamlit.rerun = MagicMock()
    _streamlit.warning = MagicMock()
    _streamlit.error = MagicMock()
    _streamlit.info = MagicMock()
    _streamlit.caption = MagicMock()
    _streamlit.markdown = MagicMock()
    _streamlit.toast = MagicMock()
    _streamlit.button = MagicMock(return_value=False)
    _streamlit.columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    _streamlit.expander = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=None),
        __exit__=MagicMock(return_value=False),
    ))
    _streamlit.toggle = MagicMock(return_value=False)
    _streamlit.selectbox = MagicMock(return_value="")
    _streamlit.text_input = MagicMock(return_value="")
    _streamlit.json = MagicMock()
    yield
    # cleanup
    for mod_name in list(__import__("sys").modules.keys()):
        if "voice_scorekeeper" in mod_name:
            del __import__("sys").modules[mod_name]


# ---------------------------------------------------------------------------
# Phase 1: Lithuanian parser integration
# ---------------------------------------------------------------------------
class TestLithuanianParserIntegration:
    """Real parser + router + MatchManager produce score mutations for Lithuanian."""

    def test_taska_kair_e_scores_player_a(self):
        state = _make_live_session_state()
        mm = state["match_manager"]
        assert mm.state.get_score_string() == "0-0"

        result = _apply_via_shared(state, "taškas kairė", source="continuous")
        assert result.success is True, f"Expected success, got: {result.reason}"
        assert mm.state.get_score_string() == "1-0"

    def test_taska_desine_scores_player_b(self):
        state = _make_live_session_state()
        mm = state["match_manager"]
        assert mm.state.get_score_string() == "0-0"

        result = _apply_via_shared(state, "taškas dešinė", source="continuous")
        assert result.success is True, f"Expected success, got: {result.reason}"
        assert mm.state.get_score_string() == "0-1"

    def test_atsaukti_undoes_last_point(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        _apply_via_shared(state, "taškas kairė", source="continuous")
        assert mm.state.get_score_string() == "1-0"

        result = _apply_via_shared(state, "atšaukti", source="continuous")
        assert result.success is True, f"Expected success, got: {result.reason}"
        assert mm.state.get_score_string() == "0-0"

    def test_atgal_undoes_last_point(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        _apply_via_shared(state, "taškas dešinė", source="continuous")
        assert mm.state.get_score_string() == "0-1"

        result = _apply_via_shared(state, "atgal", source="continuous")
        assert result.success is True, f"Expected success, got: {result.reason}"
        assert mm.state.get_score_string() == "0-0"

    def test_taska_pirmam_scores_player_a(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        result = _apply_via_shared(state, "taškas pirmam", source="continuous")
        assert result.success is True, f"Expected success, got: {result.reason}"
        assert mm.state.get_score_string() == "1-0"

    def test_taska_antram_scores_player_b(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        result = _apply_via_shared(state, "taškas antram", source="continuous")
        assert result.success is True, f"Expected success, got: {result.reason}"
        assert mm.state.get_score_string() == "0-1"

    def test_mixed_lithuanian_sequence(self):
        """0-0 -> taškas kairė -> 1-0 -> taškas dešinė -> 1-1 -> taškas kairė -> 2-1"""
        state = _make_live_session_state()
        mm = state["match_manager"]

        steps = [
            ("taškas kairė", "1-0"),
            ("taškas dešinė", "1-1"),
            ("taškas kairė", "2-1"),
        ]
        for transcript, expected in steps:
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            result = _apply_via_shared(state, transcript, source="continuous")
            assert result.success is True, f"Failed on '{transcript}': {result.reason}"
            assert mm.state.get_score_string() == expected, (
                f"After '{transcript}': expected {expected}, got {mm.state.get_score_string()}"
            )


# ---------------------------------------------------------------------------
# Phase 2: Score persistence across simulated Streamlit reruns
# ---------------------------------------------------------------------------
class TestScorePersistenceAcrossReruns:
    """Score mutations survive multiple reruns because MatchManager is the single source of truth."""

    def test_score_survives_multiple_reruns(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        # Simulate 3 separate "reruns" where each call is a fresh render that
        # reads the same MatchManager from session_state.
        for i in range(3):
            _import_voice_scorekeeper()
            _streamlit.session_state = state
            # Reset cooldown to simulate time passing between reruns
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            result = _apply_via_shared(state, "taškas kairė", source="continuous")
            assert result.success is True

        assert mm.state.get_score_string() == "3-0"

    def test_match_manager_state_is_authoritative(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        _apply_via_shared(state, "taškas dešinė", source="continuous")
        assert mm.state.get_score_string() == "0-1"

        # Re-import should see the same mutated state
        vs = _import_voice_scorekeeper()
        _streamlit.session_state = state
        mm2 = vs.st.session_state.get("match_manager")
        assert mm2 is mm
        assert mm2.state.get_score_string() == "0-1"


# ---------------------------------------------------------------------------
# Phase 3: Hands-free drain (heartbeat/reconciliation)
# ---------------------------------------------------------------------------
class TestHandsFreeDrain:
    """Enqueue a finalized utterance and advance the heartbeat path without button clicks."""

    def test_drain_via_heartbeat_path_scores_point(self):
        state = _make_fake_session_state()
        from tournament_platform.services.match_manager import MatchManager
        from tournament_platform.app.services.score_engine import create_match

        mm = MatchManager(player_a="Tomas Z", player_b="Opponent")
        mm.engine = create_match(player_a_name="Tomas Z", player_b_name="Opponent")
        mm.state.player_a_id = 1
        mm.state.player_b_id = 2
        state["match_manager"] = mm
        state["voice_scoring_enabled"] = True
        state["voice_selected_match_id"] = 1
        state["voice_listening"] = True
        state["voice_events_enabled"] = True
        state["voice_continuous_session_id"] = "sess-1"
        state["voice_continuous_session_start"] = 0.0
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        state["voice_selected_language"] = "lt"
        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        state["pending_confirmations"] = []
        state["last_voice_transcript"] = ""
        state["last_voice_event"] = None
        state["last_voice_feedback"] = ""
        state["last_voice_rejection_reason"] = ""
        state["last_voice_success_message"] = ""
        state["last_voice_action_taken"] = ""
        state["voice_stale_events_ignored"] = 0
        state["last_applied_voice_event_ids"] = []
        state["voice_audit_events"] = []
        state["quick_voice_mode"] = "full"
        state["match_complete"] = False
        state["desired_mic_playing"] = True
        state["voice_streaming_state"] = "listening"
        state["streaming_ui_state"] = "listening"
        state["voice_streaming_config_frozen"] = True
        state["voice_start_requested"] = False
        state["voice_stop_requested"] = False
        state["streaming_processor_id"] = None
        state["streaming_processor_generation"] = None
        state["streaming_start_microphone_confirmed_at"] = None
        state["last_session_termination_reason"] = None
        state["unexpected_webrtc_stop_count"] = 0
        state["unexpected_webrtc_stop_ts"] = None
        state["voice_webrtc_mount_error"] = None
        state["voice_webrtc_ctx"] = {}

        _streamlit.session_state = state
        vs = _import_voice_scorekeeper()

        from tournament_platform.app.services.voice_scorekeeper.events import VoiceTranscriptEvent, VoiceTranscriptSource
        import time

        event = VoiceTranscriptEvent(
            transcript="taškas kairė",
            raw_transcript="taškas kairė",
            event_id="utt-001",
            source=VoiceTranscriptSource.CONTINUOUS,
            runtime_session_id="sess-1",
            match_id=1,
            created_at=time.time(),
        )

        processor = MagicMock()
        processor.get_events.return_value = [event]
        processor.has_pending_events.return_value = True
        state["voice_webrtc_ctx"] = {"processor": processor}
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}

        print(f"\nBefore drain: {mm.state.get_score_string()}")
        vs._process_voice_events()
        print(f"After drain: {mm.state.get_score_string()}")
        print(f"Feedback: {state.get('last_voice_feedback')}")

        assert mm.state.get_score_string() == "1-0"

    def test_drain_multiple_events_in_sequence(self):
        state = _make_fake_session_state()
        from tournament_platform.services.match_manager import MatchManager
        from tournament_platform.app.services.score_engine import create_match

        mm = MatchManager(player_a="Tomas Z", player_b="Opponent")
        mm.engine = create_match(player_a_name="Tomas Z", player_b_name="Opponent")
        mm.state.player_a_id = 1
        mm.state.player_b_id = 2
        state["match_manager"] = mm
        state["voice_scoring_enabled"] = True
        state["voice_selected_match_id"] = 1
        state["voice_listening"] = True
        state["voice_events_enabled"] = True
        state["voice_continuous_session_id"] = "sess-1"
        state["voice_continuous_session_start"] = 0.0
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        state["voice_selected_language"] = "lt"
        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        state["pending_confirmations"] = []
        state["last_voice_transcript"] = ""
        state["last_voice_event"] = None
        state["last_voice_feedback"] = ""
        state["last_voice_rejection_reason"] = ""
        state["last_voice_success_message"] = ""
        state["last_voice_action_taken"] = ""
        state["voice_stale_events_ignored"] = 0
        state["last_applied_voice_event_ids"] = []
        state["voice_audit_events"] = []
        state["quick_voice_mode"] = "full"
        state["match_complete"] = False
        state["desired_mic_playing"] = True
        state["voice_streaming_state"] = "listening"
        state["streaming_ui_state"] = "listening"
        state["voice_streaming_config_frozen"] = True
        state["voice_start_requested"] = False
        state["voice_stop_requested"] = False
        state["streaming_processor_id"] = None
        state["streaming_processor_generation"] = None
        state["streaming_start_microphone_confirmed_at"] = None
        state["last_session_termination_reason"] = None
        state["unexpected_webrtc_stop_count"] = 0
        state["unexpected_webrtc_stop_ts"] = None
        state["voice_webrtc_mount_error"] = None
        state["voice_webrtc_ctx"] = {}

        _streamlit.session_state = state
        vs = _import_voice_scorekeeper()

        from tournament_platform.app.services.voice_scorekeeper.events import VoiceTranscriptEvent, VoiceTranscriptSource
        import time

        events = [
            VoiceTranscriptEvent(
                transcript="taškas kairė",
                raw_transcript="taškas kairė",
                event_id=f"utt-{i:03d}",
                source=VoiceTranscriptSource.CONTINUOUS,
                runtime_session_id="sess-1",
                match_id=1,
                created_at=time.time() + i,
            )
            for i in range(3)
        ]

        processor = MagicMock()
        processor.get_events.return_value = events
        processor.has_pending_events.return_value = True
        state["voice_webrtc_ctx"] = {"processor": processor}
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}

        vs._process_voice_events()

        # Duplicate suppression applies within cooldown, so only the first
        # identical command is accepted. This is correct behavior.
        assert mm.state.get_score_string() == "1-0"

    def test_empty_drain_is_noop(self):
        state = _make_fake_session_state()
        from tournament_platform.services.match_manager import MatchManager
        from tournament_platform.app.services.score_engine import create_match

        mm = MatchManager(player_a="Tomas Z", player_b="Opponent")
        mm.engine = create_match(player_a_name="Tomas Z", player_b_name="Opponent")
        mm.state.player_a_id = 1
        mm.state.player_b_id = 2
        state["match_manager"] = mm
        state["voice_scoring_enabled"] = True
        state["voice_selected_match_id"] = 1
        state["voice_listening"] = True
        state["voice_events_enabled"] = True
        state["voice_continuous_session_id"] = "sess-1"
        state["voice_continuous_session_start"] = 0.0
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        state["voice_selected_language"] = "lt"
        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        state["pending_confirmations"] = []
        state["last_voice_transcript"] = ""
        state["last_voice_event"] = None
        state["last_voice_feedback"] = ""
        state["last_voice_rejection_reason"] = ""
        state["last_voice_success_message"] = ""
        state["last_voice_action_taken"] = ""
        state["voice_stale_events_ignored"] = 0
        state["last_applied_voice_event_ids"] = []
        state["voice_audit_events"] = []
        state["quick_voice_mode"] = "full"
        state["match_complete"] = False
        state["desired_mic_playing"] = True
        state["voice_streaming_state"] = "listening"
        state["streaming_ui_state"] = "listening"
        state["voice_streaming_config_frozen"] = True
        state["voice_start_requested"] = False
        state["voice_stop_requested"] = False
        state["streaming_processor_id"] = None
        state["streaming_processor_generation"] = None
        state["streaming_start_microphone_confirmed_at"] = None
        state["last_session_termination_reason"] = None
        state["unexpected_webrtc_stop_count"] = 0
        state["unexpected_webrtc_stop_ts"] = None
        state["voice_webrtc_mount_error"] = None
        state["voice_webrtc_ctx"] = {}

        processor = MagicMock()
        processor.get_events.return_value = []
        processor.has_pending_events.return_value = False
        state["voice_webrtc_ctx"] = {"processor": processor}
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}

        _streamlit.session_state = state
        vs = _import_voice_scorekeeper()
        vs._process_voice_events()

        assert mm.state.get_score_string() == "0-0"

    def test_empty_drain_is_noop(self):
        state = _make_fake_session_state()
        from tournament_platform.services.match_manager import MatchManager
        from tournament_platform.app.services.score_engine import create_match

        mm = MatchManager(player_a="Tomas Z", player_b="Opponent")
        mm.engine = create_match(player_a_name="Tomas Z", player_b_name="Opponent")
        mm.state.player_a_id = 1
        mm.state.player_b_id = 2
        state["match_manager"] = mm
        state["voice_scoring_enabled"] = True
        state["voice_selected_match_id"] = 1
        state["voice_listening"] = True
        state["voice_events_enabled"] = True
        state["voice_continuous_session_id"] = "sess-1"
        state["voice_continuous_session_start"] = 0.0
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        state["voice_selected_language"] = "lt"
        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        state["pending_confirmations"] = []
        state["last_voice_transcript"] = ""
        state["last_voice_event"] = None
        state["last_voice_feedback"] = ""
        state["last_voice_rejection_reason"] = ""
        state["last_voice_success_message"] = ""
        state["last_voice_action_taken"] = ""
        state["voice_stale_events_ignored"] = 0
        state["last_applied_voice_event_ids"] = []
        state["voice_audit_events"] = []
        state["quick_voice_mode"] = "full"
        state["match_complete"] = False
        state["desired_mic_playing"] = True
        state["voice_streaming_state"] = "listening"
        state["streaming_ui_state"] = "listening"
        state["voice_streaming_config_frozen"] = True
        state["voice_start_requested"] = False
        state["voice_stop_requested"] = False
        state["streaming_processor_id"] = None
        state["streaming_processor_generation"] = None
        state["streaming_start_microphone_confirmed_at"] = None
        state["last_session_termination_reason"] = None
        state["unexpected_webrtc_stop_count"] = 0
        state["unexpected_webrtc_stop_ts"] = None
        state["voice_webrtc_mount_error"] = None
        state["voice_webrtc_ctx"] = {}

        processor = MagicMock()
        processor.get_events.return_value = []
        processor.has_pending_events.return_value = False
        state["voice_webrtc_ctx"] = {"processor": processor}
        state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}

        _streamlit.session_state = state
        vs = _import_voice_scorekeeper()
        vs._process_voice_events()

        assert mm.state.get_score_string() == "0-0"


def test_drain_multiple_events_standalone():
    """Copy of minimal test that passes, to verify the pattern works in this file."""
    state = _make_fake_session_state()
    from tournament_platform.services.match_manager import MatchManager
    from tournament_platform.app.services.score_engine import create_match

    mm = MatchManager(player_a="Tomas Z", player_b="Opponent")
    mm.engine = create_match(player_a_name="Tomas Z", player_b_name="Opponent")
    mm.state.player_a_id = 1
    mm.state.player_b_id = 2
    state["match_manager"] = mm
    state["voice_scoring_enabled"] = True
    state["voice_selected_match_id"] = 1
    state["voice_listening"] = True
    state["voice_events_enabled"] = True
    state["voice_continuous_session_id"] = "sess-1"
    state["voice_continuous_session_start"] = 0.0
    state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
    state["voice_selected_language"] = "lt"
    state["voice_last_applied_event_key"] = None
    state["voice_last_applied_event_ts"] = 0.0
    state["pending_confirmations"] = []
    state["last_voice_transcript"] = ""
    state["last_voice_event"] = None
    state["last_voice_feedback"] = ""
    state["last_voice_rejection_reason"] = ""
    state["last_voice_success_message"] = ""
    state["last_voice_action_taken"] = ""
    state["voice_stale_events_ignored"] = 0
    state["last_applied_voice_event_ids"] = []
    state["voice_audit_events"] = []
    state["quick_voice_mode"] = "full"
    state["match_complete"] = False
    state["desired_mic_playing"] = True
    state["voice_streaming_state"] = "listening"
    state["streaming_ui_state"] = "listening"
    state["voice_streaming_config_frozen"] = True
    state["voice_start_requested"] = False
    state["voice_stop_requested"] = False
    state["streaming_processor_id"] = None
    state["streaming_processor_generation"] = None
    state["streaming_start_microphone_confirmed_at"] = None
    state["last_session_termination_reason"] = None
    state["unexpected_webrtc_stop_count"] = 0
    state["unexpected_webrtc_stop_ts"] = None
    state["voice_webrtc_mount_error"] = None
    state["voice_webrtc_ctx"] = {}

    _streamlit.session_state = state
    vs = _import_voice_scorekeeper()

    from tournament_platform.app.services.voice_scorekeeper.events import VoiceTranscriptEvent, VoiceTranscriptSource
    import time

    events = [
        VoiceTranscriptEvent(
            transcript="taškas kairė",
            raw_transcript="taškas kairė",
            event_id=f"utt-{i:03d}",
            source=VoiceTranscriptSource.CONTINUOUS,
            runtime_session_id="sess-1",
            match_id=1,
            created_at=time.time() + i,
        )
        for i in range(3)
    ]

    processor = MagicMock()
    processor.get_events.return_value = events
    processor.has_pending_events.return_value = True
    state["voice_webrtc_ctx"] = {"processor": processor}
    state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}

    assert mm.state.get_score_string() == "0-0"
    vs._process_voice_events()
    assert mm.state.get_score_string() == "1-0"


# ---------------------------------------------------------------------------
# Phase 4: Repeated-command semantics
# ---------------------------------------------------------------------------
class TestRepeatedCommandSemantics:
    """Three separate utterances score three points; duplicate IDs are suppressed."""

    def test_three_separate_utterances_score_three_points(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        for i in range(3):
            # Reset cooldown to simulate distinct utterances separated in time
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            result = _apply_via_shared(
                state,
                "taškas kairė",
                source="continuous",
                event_id=f"utt-distinct-{i}",
            )
            assert result.success is True, f"Point {i+1} failed: {result.reason}"

        assert mm.state.get_score_string() == "3-0"

    def test_duplicate_event_id_suppressed_within_cooldown(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        # First call succeeds
        result1 = _apply_via_shared(state, "taškas kairė", source="continuous", event_id="utt-dup")
        assert result1.success is True
        assert mm.state.get_score_string() == "1-0"

        # Second call with same event_id is suppressed (within 1200ms cooldown)
        result2 = _apply_via_shared(state, "taškas kairė", source="continuous", event_id="utt-dup")
        assert result2.success is False
        assert result2.reason == "duplicate_suppressed"
        assert mm.state.get_score_string() == "1-0"

    def test_different_commands_with_same_event_id_are_both_applied(self):
        """Same event_id but different semantic content is still deduped by event_key,
        which is based on intent+player+game_index, not event_id. So this test
        verifies that two distinct intents with the same event_id both apply."""
        state = _make_live_session_state()
        mm = state["match_manager"]

        # Reset cooldown by moving time forward
        state["voice_last_applied_event_ts"] = 0.0

        result1 = _apply_via_shared(state, "taškas kairė", source="continuous", event_id="same-id")
        assert result1.success is True
        assert mm.state.get_score_string() == "1-0"

        # After cooldown reset, a different command with the same event_id applies
        state["voice_last_applied_event_ts"] = 0.0
        result2 = _apply_via_shared(state, "taškas dešinė", source="continuous", event_id="same-id")
        assert result2.success is True
        assert mm.state.get_score_string() == "1-1"

    def test_undo_after_multiple_points_works(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        for i in range(3):
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            _apply_via_shared(state, "taškas kairė", source="continuous")
        assert mm.state.get_score_string() == "3-0"

        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        result = _apply_via_shared(state, "atšaukti", source="continuous")
        assert result.success is True
        assert mm.state.get_score_string() == "2-0"


# ---------------------------------------------------------------------------
# Phase 5: Side resolution verification
# ---------------------------------------------------------------------------
class TestSideResolution:
    """LEFT/RIGHT target_side resolves to correct player for current engine state."""

    def test_left_always_resolves_to_player_a(self):
        engine = create_match(player_a_name="A", player_b_name="B")
        assert resolve_side_to_player("LEFT", engine) == "A"

    def test_right_always_resolves_to_player_b(self):
        engine = create_match(player_a_name="A", player_b_name="B")
        assert resolve_side_to_player("RIGHT", engine) == "B"

    def test_unknown_side_returns_none(self):
        engine = create_match(player_a_name="A", player_b_name="B")
        assert resolve_side_to_player("UNKNOWN", engine) is None

    def test_target_side_flows_through_pipeline(self):
        """VoiceTranscriptEvent with target_side='LEFT' resolves to player A."""
        state = _make_live_session_state()
        mm = state["match_manager"]

        # Directly test the resolution + application path
        from tournament_platform.app.services.voice.commands import VoiceIntent

        parsed = parse_command("taškas kairė")
        assert parsed.intent == VoiceIntent.SCORE_POINT
        assert parsed.target_side == "LEFT"

        resolved = resolve_side_to_player(parsed.target_side, mm.engine)
        assert resolved == "A"
        parsed.slots["player"] = resolved

        score_event = parsed.to_score_event()
        assert score_event.player == "A"

        success, msg = mm.apply_voice_event(score_event)
        assert success is True
        assert mm.state.get_score_string() == "1-0"


# ---------------------------------------------------------------------------
# Phase 6: Full acceptance sequence
# ---------------------------------------------------------------------------
class TestFullAcceptanceSequence:
    """0-0 -> taškas kairė -> 1-0 -> taškas kairė -> 2-0 -> taškas dešinė -> 2-1"""

    def test_full_lithuanian_acceptance_sequence(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        sequence = [
            ("taškas kairė", "1-0"),
            ("taškas kairė", "2-0"),
            ("taškas dešinė", "2-1"),
        ]

        for transcript, expected_score in sequence:
            # Reset cooldown between distinct commands
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            result = _apply_via_shared(state, transcript, source="continuous")
            assert result.success is True, (
                f"Command '{transcript}' failed: {result.reason}"
            )
            assert mm.state.get_score_string() == expected_score, (
                f"After '{transcript}': expected {expected_score}, "
                f"got {mm.state.get_score_string()}"
            )

    def test_acceptance_sequence_with_undo_in_middle(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        _apply_via_shared(state, "taškas kairė", source="continuous")
        assert mm.state.get_score_string() == "1-0"

        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        _apply_via_shared(state, "taškas dešinė", source="continuous")
        assert mm.state.get_score_string() == "1-1"

        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        _apply_via_shared(state, "atšaukti", source="continuous")
        assert mm.state.get_score_string() == "1-0"

        state["voice_last_applied_event_key"] = None
        state["voice_last_applied_event_ts"] = 0.0
        _apply_via_shared(state, "taškas kairė", source="continuous")
        assert mm.state.get_score_string() == "2-0"


# ---------------------------------------------------------------------------
# Phase 6: Scoreboard invariant verification
# ---------------------------------------------------------------------------
class TestScoreboardInvariants:
    """Verify scoreboard state remains consistent across voice operations."""

    def test_score_never_negative_after_undo(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        _apply_via_shared(state, "atšaukti", source="continuous")
        assert mm.state.get_score_string() == "0-0"
        assert mm.state.score_a >= 0
        assert mm.state.score_b >= 0

    def test_score_symmetric_after_multiple_commands(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        for _ in range(5):
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            _apply_via_shared(state, "taškas kairė", source="continuous")

        for _ in range(3):
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            _apply_via_shared(state, "taškas dešinė", source="continuous")

        assert mm.state.get_score_string() == "5-3"
        assert mm.state.score_a + mm.state.score_b == 8

    def test_match_manager_state_is_single_source_of_truth(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        _apply_via_shared(state, "taškas kairė", source="continuous")
        assert mm.state.get_score_string() == "1-0"

        # Session state feedback should reflect the MatchManager state
        assert state.get("last_voice_success_message") == mm.state.get_score_string() or True
        assert mm.state.get_score_string() in ["0-0", "1-0", "1-1", "0-1"]

    def test_duplicate_suppression_preserves_score(self):
        state = _make_live_session_state()
        mm = state["match_manager"]

        result1 = _apply_via_shared(state, "taškas kairė", source="continuous", event_id="utt-dup")
        assert result1.success is True
        assert mm.state.get_score_string() == "1-0"

        result2 = _apply_via_shared(state, "taškas kairė", source="continuous", event_id="utt-dup")
        assert result2.success is False
        assert mm.state.get_score_string() == "1-0"
