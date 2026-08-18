import pytest
import dataclasses
from unittest.mock import MagicMock, patch
from tournament_platform.app.services.voice_scorekeeper.runtime import WebRtcRenderSnapshot
from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
    resolve_calibration_processor_readiness
)
from tournament_platform.app.services.voice_scorekeeper.events import (
    VoiceTranscriptEvent, VoiceTranscriptSource, CalibrationCaptureContext, CalibrationCaptureKind
)
from tournament_platform.app.services.voice_scorekeeper.event_drain import (
    _process_voice_events, clear_calibration_processed_ids
)
from tournament_platform.app.services.voice_calibration.service import VoiceCalibrationService

@pytest.fixture(autouse=True)
def clean_up_calibration_cache():
    clear_calibration_processed_ids()
    yield

def test_calibration_readiness_no_asr_required():
    """Test that calibration readiness does NOT require ASR to be ready."""
    processor = MagicMock()
    processor._asr_ready = False
    processor._processor_generation = 1
    processor.api_version = 1
    processor._implementation_version = 1
    processor.get_processor_diagnostics.return_value = {
        "audio_frames_received": 100,
        "last_ingest_timestamp": 1000.0
    }
    
    # Mock VOICE_RUNTIME_IMPLEMENTATION_VERSION and VOICE_AUDIO_PROCESSOR_API_VERSION
    # as they are imported inside the function
    with patch("tournament_platform.app.components.voice_scorekeeper.voice_calibration.VOICE_AUDIO_PROCESSOR_API_VERSION", 1, create=True), \
         patch("tournament_platform.app.components.voice_scorekeeper.voice_calibration.VOICE_RUNTIME_IMPLEMENTATION_VERSION", 1, create=True):
        
        resolution = resolve_calibration_processor_readiness(
            webrtc_playing=True,
            processor=processor,
            expected_api_version=1,
            expected_implementation_version=1,
            current_time=1000.5
        )
    
    assert resolution.ready is True
    assert resolution.status == "READY"

class MockSessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
    def __setattr__(self, key, value):
        self[key] = value

def test_calibration_event_diversion():
    """Test that calibration-tagged events are diverted from scoring."""
    calibration_service = MagicMock(spec=VoiceCalibrationService)
    # Ensure it doesn't fail on has_attr checks if we use them
    calibration_service.consume_trials.return_value = MagicMock()
    
    processor = MagicMock()
    
    cal_ctx = CalibrationCaptureContext(
        calibration_session_id="session_1",
        calibration_trial_id="trial_1",
        capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        expected_command_id="SCORE_POINT_LEFT",
        expected_phrase="point left"
    )
    
    # Event with calibration context
    cal_event = VoiceTranscriptEvent(
        transcript="point left",
        raw_transcript="point left",
        event_id="evt_1",
        source=VoiceTranscriptSource.CONTINUOUS,
        calibration_context=cal_ctx
    )
    
    processor.get_events.return_value = []
    processor.drain_streaming_events.return_value = []
    
    # Mock st.session_state and other dependencies
    mock_ss = MockSessionState({
        "match_manager": MagicMock(),
        "voice_calibration_session": MagicMock(),
        "voice_scoring_enabled": True,
        "voice_continuous_session_id": "session_1",
        "voice_continuous_session_start": 0.0,
        "last_applied_voice_event_ids": [],
        "voice_listening": True,
        "voice_events_enabled": True
    })
    
    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.services.voice_scorekeeper.event_drain._process_voice_transcript") as mock_process:
        
        processor.get_events.return_value = [cal_event]
        
        from tournament_platform.app.services.voice_scorekeeper.events import VoiceDrainResult
        snapshot = WebRtcRenderSnapshot(
            context=MagicMock(), playing=True, signalling=True, 
            processor=processor, processor_id=id(processor), processor_generation=1,
            audio_frames_received=100
        )
        
        result = _process_voice_events(
            calibration_service=calibration_service,
            snapshot=snapshot
        )
        
        # Verify it was NOT sent to the live scoring parser
        assert mock_process.call_count == 0
        
        # Verify it WAS evaluated as calibration event
        assert result.calibration_events_evaluated == 1
        assert len(result.calibration_trial_results) == 1
        
        # Verify it WAS consumed by calibration service
        assert calibration_service.consume_trials.called

def test_calibration_suppresses_manual_mode_scoring():
    """Test that even in manual mode, calibration context suppresses scoring."""
    calibration_service = MagicMock(spec=VoiceCalibrationService)
    processor = MagicMock()
    
    cal_ctx = CalibrationCaptureContext(
        calibration_session_id="session_1",
        calibration_trial_id="trial_1",
        capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        expected_command_id="SCORE_POINT_LEFT",
        expected_phrase="point left"
    )
    
    # Event with calibration context
    cal_event = VoiceTranscriptEvent(
        transcript="point left",
        raw_transcript="point left",
        event_id="evt_1",
        source=VoiceTranscriptSource.CONTINUOUS,
        calibration_context=cal_ctx
    )
    
    mock_ss = MockSessionState({
        "match_manager": MagicMock(),
        "voice_calibration_session": MagicMock(),
        "voice_scoring_enabled": True,
        "voice_listening": True,
        "voice_events_enabled": True,
        "voice_continuous_session_id": "session_1",
        "voice_continuous_session_start": 0.0,
        "last_applied_voice_event_ids": []
    })
    with patch("streamlit.session_state", mock_ss), \
         patch("tournament_platform.app.services.voice_scorekeeper.event_drain._process_voice_transcript") as mock_process:
        
        processor.get_events.return_value = [cal_event]
        processor.drain_streaming_events.return_value = []
        
        snapshot = WebRtcRenderSnapshot(
            context=MagicMock(), playing=True, signalling=True, 
            processor=processor, processor_id=id(processor), processor_generation=1,
            audio_frames_received=100
        )
        
        _process_voice_events(
            calibration_service=calibration_service,
            snapshot=snapshot
        )
        
        # Still not processed as score
        assert mock_process.call_count == 0
