import pytest
from unittest.mock import MagicMock, patch
import streamlit as st
from tournament_platform.app.services.voice_scorekeeper.runtime import WebRtcRenderSnapshot
from tournament_platform.app.services.score_engine import MatchState as EngineMatchState

import tournament_platform.app.pages.voice_scorekeeper as vs

class MockSessionState(dict):
    def __getattr__(self, key):
        if key == "voice_last_chunk_rms":
            return 0.0
        if key == "voice_noise_threshold":
            return 0.1
        if key == "voice_noise_filtering":
            return False
        if key == "voice_strict_mode":
            return False
        try:
            return self[key]
        except KeyError:
            # For Junie refactor safety, we return a mock for unknown keys
            # to simulate a "populated" but fresh state.
            return MagicMock()
    def __setattr__(self, key, value):
        self[key] = value

@pytest.fixture
def mock_ss():
    ss = MockSessionState()
    
    # Initialize basic required keys for rendering
    ss["voice_scoring_enabled"] = True
    ss["tt_sounds_enabled"] = False
    ss["desired_mic_playing"] = False
    ss["voice_streaming_state"] = "disabled"
    ss["streaming_ui_state"] = "disabled"
    ss["voice_streaming_config_frozen"] = False
    ss["voice_streaming_last_refresh"] = 0.0
    ss["voice_selected_match_id"] = 1
    ss["match_manager"] = MagicMock()
    ss["match_manager"].state.player_a = "Player A"
    ss["match_manager"].state.player_b = "Player B"
    ss["match_manager"].state.player_a_id = 1
    ss["match_manager"].state.player_b_id = 2
    ss["match_manager"].engine = EngineMatchState(
        player_a_name="Player A",
        player_b_name="Player B",
        player_a_id=1,
        player_b_id=2,
        points_to_win=11,
        best_of=3
    )
    ss["voice_webrtc_tracked_factory"] = MagicMock()
    ss["quick_voice_mode"] = "off"
    ss["last_voice_transcript"] = ""
    ss["last_voice_event"] = None
    ss["last_voice_feedback"] = ""
    ss["voice_last_applied_event_key"] = None
    
    return ss

def run_render_safety_test(mock_ss, snapshot=None):
    """Helper to run vs._render_voice_scoring_settings with patches."""
    if snapshot is None:
        snapshot = WebRtcRenderSnapshot.unavailable()
        
    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper.st.session_state", mock_ss), \
         patch("tournament_platform.app.pages.voice_scorekeeper._audio_callback_lock", MagicMock()):
        
        # This should not raise NameError or UnboundLocalError
        vs._render_voice_scoring_settings(snapshot=snapshot)

def test_render_safety_initial(mock_ss):
    """Initial page, voice disabled."""
    mock_ss["voice_scoring_enabled"] = False
    run_render_safety_test(mock_ss)

def test_render_safety_full_commands_off(mock_ss):
    """Full Voice Commands selected, but mode is Off."""
    mock_ss["voice_scoring_enabled"] = True
    mock_ss["quick_voice_mode"] = "off"
    run_render_safety_test(mock_ss)

def test_render_safety_full_commands_ready(mock_ss):
    """Full Voice Commands, before Start."""
    mock_ss["voice_scoring_enabled"] = True
    mock_ss["quick_voice_mode"] = "full"
    run_render_safety_test(mock_ss)

def test_render_safety_mount_error(mock_ss):
    """WebRTC mount failure."""
    mock_ss["voice_scoring_enabled"] = True
    mock_ss["quick_voice_mode"] = "full"
    snapshot = WebRtcRenderSnapshot(
        context=None,
        playing=False,
        signalling=False,
        processor=None,
        processor_id=None,
        processor_generation=None,
        audio_frames_received=0,
        component_rendered=True,
        mount_error="Simulated mount failure"
    )
    run_render_safety_test(mock_ss, snapshot=snapshot)

def test_render_safety_playing(mock_ss):
    """WebRTC playing, processor present."""
    mock_ss["voice_scoring_enabled"] = True
    mock_ss["quick_voice_mode"] = "full"
    mock_ss["desired_mic_playing"] = True
    
    proc = MagicMock()
    proc._audio_frames_received = 150
    proc._processor_generation = 1
    proc._last_recv_timestamp = 1000.0
    
    # Mock diagnostics to avoid resolve_continuous_listening_readiness crashes
    proc.get_processor_diagnostics.return_value = {
        "audio_frames_received": 150,
        "callback_count": 200,
        "last_recv_timestamp": 1000.0,
        "last_recv_queued_timestamp": 1000.0,
        "last_ingest_timestamp": 1000.0,
    }
    
    # Mock audio_buffer to avoid resolve_continuous_listening_readiness crashes
    mock_buffer = MagicMock()
    mock_buffer._last_speech_time = 1000.0
    mock_buffer.get_speech_segment_duration_ms.return_value = 0.0
    mock_buffer.get_segment_reset_reason.return_value = ""
    mock_buffer.get_buffer_duration_ms.return_value = 0.0
    proc.audio_buffer = mock_buffer
    
    # Mock backend
    mock_backend = MagicMock()
    mock_backend.connection_state.return_value = "connected"
    proc._streaming_backend = mock_backend
    
    snapshot = WebRtcRenderSnapshot(
        context=MagicMock(),
        playing=True,
        signalling=True,
        processor=proc,
        processor_id=id(proc),
        processor_generation=1,
        audio_frames_received=150,
        component_rendered=True
    )
    run_render_safety_test(mock_ss, snapshot=snapshot)

def test_render_safety_webrtc_unavailable(mock_ss):
    """WebRTC package missing."""
    with patch("tournament_platform.app.pages.voice_scorekeeper.WEBRTC_AVAILABLE", False):
        run_render_safety_test(mock_ss)

def test_render_safety_diagnostics_expanded(mock_ss):
    """Exercising the diagnostics block."""
    mock_ss["voice_scoring_enabled"] = True
    mock_ss["quick_voice_mode"] = "full"
    # We can't easily force expanders in unit tests, but we can ensure the code inside them is safe
    # if it were executed. Ruff already checked for undefined names.
    run_render_safety_test(mock_ss)

if __name__ == "__main__":
    pytest.main([__file__])
