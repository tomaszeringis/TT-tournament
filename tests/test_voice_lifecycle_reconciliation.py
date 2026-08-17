import pytest
from unittest.mock import MagicMock, patch
import streamlit as st
from tournament_platform.app.services.voice_scorekeeper.runtime import WebRtcRenderSnapshot
from tournament_platform.app.services.score_engine import MatchState as EngineMatchState

# Import the functions to test
# We need to mock webrtc_streamer and session_state
import tournament_platform.app.pages.voice_scorekeeper as vs

class MockContext:
    def __init__(self, playing=False, signalling=False):
        self.state = MagicMock(playing=playing, signalling=signalling)
        self.audio_processor = MagicMock()

class MockSessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return MagicMock()
    def __setattr__(self, key, value):
        self[key] = value

@pytest.fixture
def mock_ss():
    ss = MockSessionState()
    
    # Initialize required keys
    ss["voice_scoring_enabled"] = True
    ss["tt_sounds_enabled"] = False
    ss["desired_mic_playing"] = False
    ss["voice_streaming_state"] = "disabled"
    ss["streaming_ui_state"] = "disabled"
    ss["voice_streaming_config_frozen"] = False
    ss["voice_streaming_last_refresh"] = 0.0
    ss["voice_selected_match_id"] = 1
    ss["voice_selected_player1_id"] = 1
    ss["voice_selected_player2_id"] = 2
    ss["match_manager"] = MagicMock()
    ss["match_manager"].state.player_a = "Player A"
    ss["match_manager"].state.player_b = "Player B"
    ss["match_manager"].state.player_a_id = 1
    ss["match_manager"].state.player_b_id = 2
    ss["match_manager"].state.score_a = 0
    ss["match_manager"].state.score_b = 0
    ss["match_manager"].state.match_history = []
    ss["match_manager"].engine = EngineMatchState(
        player_a_name="Player A",
        player_b_name="Player B",
        player_a_id=1,
        player_b_id=2,
        points_to_win=11,
        best_of=3
    )
    
    ss["voice_speaker_tagger"] = MagicMock(mode="off")
    ss["last_voice_transcript"] = ""
    ss["last_voice_event"] = None
    ss["voice_webrtc_tracked_factory"] = MagicMock()
    
    return ss

def test_render_ui_initial_load(mock_ss):
    """Verify _render_ui runs without UnboundLocalError on initial load."""
    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper.st.session_state", mock_ss), \
         patch("streamlit_webrtc.webrtc_streamer", return_value=None), \
         patch("tournament_platform.app.pages.voice_scorekeeper.get_script_run_ctx", return_value=MagicMock()), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_page_header"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_tour"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.apply_global_styles"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_commentary_settings"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_active_match_selector"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_selected_match_summary"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.get_all_players", return_value=[]), \
         patch("tournament_platform.app.pages.voice_scorekeeper.persist_voice_match_to_db"):
        
        # This should not raise UnboundLocalError for _ss or _webrtc_snapshot
        try:
            vs._render_ui()
        except UnboundLocalError as e:
            pytest.fail(f"_render_ui raised UnboundLocalError: {e}")
        except Exception as e:
            # Other exceptions might occur due to complex mocks, but we care about UnboundLocalError
            if "UnboundLocalError" in str(e):
                pytest.fail(f"_render_ui raised UnboundLocalError (wrapped): {e}")
            pass

def test_render_voice_scoring_settings_diagnostics_path(mock_ss):
    """Verify _render_voice_scoring_settings handles factory diagnostics failure gracefully."""
    snapshot = WebRtcRenderSnapshot.unavailable()
    
    # Mock factory to raise exception when getting diagnostics
    mock_factory = MagicMock()
    mock_factory.get_diagnostics.side_effect = Exception("Factory crash")
    mock_ss.voice_webrtc_tracked_factory = mock_factory
    
    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper.st.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper._audio_callback_lock", MagicMock()):
        
        # This should not raise UnboundLocalError for _ss even if factory.get_diagnostics fails
        try:
            vs._render_voice_scoring_settings(snapshot=snapshot)
        except UnboundLocalError as e:
            pytest.fail(f"_render_voice_scoring_settings raised UnboundLocalError: {e}")
        except Exception as e:
            # Ignore other errors from rendering
            if "UnboundLocalError" in str(e):
                 pytest.fail(f"_render_voice_scoring_settings raised UnboundLocalError (wrapped): {e}")

def test_canonical_render_order_audit(mock_ss):
    """Verify the execution order: webrtc_streamer -> reconciliation -> drain."""
    # We use a spy-like approach to track call order
    call_order = []
    
    def spy_init(*args, **kwargs):
        call_order.append("init_webrtc")
        return WebRtcRenderSnapshot.unavailable()
        
    def spy_reconcile(*args, **kwargs):
        call_order.append("reconcile")
        
    def spy_drain(*args, **kwargs):
        call_order.append("drain")
        return MagicMock()

    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper.st.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper._initialize_webrtc_session", side_effect=spy_init), \
         patch("tournament_platform.app.pages.voice_scorekeeper._refresh_streaming_diagnostics", side_effect=spy_reconcile), \
         patch("tournament_platform.app.pages.voice_scorekeeper._process_voice_events", side_effect=spy_drain), \
         patch("tournament_platform.app.pages.voice_scorekeeper.get_script_run_ctx", return_value=MagicMock()), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_page_header"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_tour"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.apply_global_styles"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_commentary_settings"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_active_match_selector"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_selected_match_summary"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.get_all_players", return_value=[]), \
         patch("tournament_platform.app.pages.voice_scorekeeper.persist_voice_match_to_db"), \
         patch("tournament_platform.app.pages.voice_scorekeeper.render_voice_sections"):
        
        mock_ss["voice_streaming_config_frozen"] = True # Trigger reconciliation
        
        # Mock time to ensure reconciliation is triggered
        with patch("time.time", return_value=1000.0):
            mock_ss["voice_streaming_last_refresh"] = 0.0
            vs._render_ui()
            
    # Verify order: init_webrtc -> reconcile -> drain
    relevant_calls = [c for c in call_order if c in ("init_webrtc", "reconcile", "drain")]
    
    assert "init_webrtc" in relevant_calls
    assert "reconcile" in relevant_calls
    assert "drain" in relevant_calls
    
    # Check specific sequence
    init_idx = relevant_calls.index("init_webrtc")
    rec_idx = relevant_calls.index("reconcile")
    drain_idx = relevant_calls.index("drain")
    
    assert init_idx < rec_idx, "WebRTC initialization must happen before reconciliation"
    assert rec_idx < drain_idx, "Reconciliation must happen before event draining"

def test_diagnostics_ctx_name_error_regression(mock_ss):
    """Verify that diagnostics rendering doesn't raise NameError: ctx."""
    snapshot = WebRtcRenderSnapshot(
        context=MagicMock(),
        playing=True,
        signalling=True,
        processor=MagicMock(),
        processor_id=123,
        processor_generation=1,
        audio_frames_received=100,
        component_rendered=True
    )
    
    # Ensure all required state is present to reach diagnostic blocks
    mock_ss["voice_scoring_enabled"] = True
    mock_ss["quick_voice_mode"] = "full"
    mock_ss["voice_listening"] = True
    
    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper.st.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper._audio_callback_lock", MagicMock()):
        
        # This should not raise NameError for ctx
        try:
            vs._render_voice_scoring_settings(snapshot=snapshot)
        except NameError as e:
            pytest.fail(f"_render_voice_scoring_settings raised NameError: {e}")
        except Exception as e:
            # Other rendering errors are acceptable for this regression test
            if "name 'ctx' is not defined" in str(e):
                pytest.fail(f"_render_voice_scoring_settings raised NameError (wrapped): {e}")
            pass
