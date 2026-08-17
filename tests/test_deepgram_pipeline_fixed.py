import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor
from tournament_platform.app.services.voice_audio import SAMPLE_FORMAT_FLOAT32
from tournament_platform.app.services.asr_backends.calibration_policy import ASRCapabilities, AudioDeliveryPolicy

class MockDeepgramBackend:
    backend_name = "deepgram"
    def __init__(self):
        self._enqueued_pcm = []
        self._generation = 1
        self._session_id = "dg-123"
        self._streaming_active = True
        
    def capabilities(self):
        return ASRCapabilities(supports_streaming=True)
        
    def delivery_policy(self):
        return AudioDeliveryPolicy(mode="continuous")
        
    def start_session(self, **kwargs):
        pass

    def is_available(self):
        return True
        
    def connection_state(self):
        return "connected"
        
    def health_status(self):
        return "connected"
        
    def get_connection_state(self):
        return "connected"
        
    def enqueue_audio(self, pcm_bytes):
        self._enqueued_pcm.append(pcm_bytes)
        return True
        
    def metrics(self):
        from tournament_platform.app.services.asr_backends.base import DeepgramBackendMetrics
        m = DeepgramBackendMetrics(
            audio_send_attempts=len(self._enqueued_pcm),
            audio_send_success=len(self._enqueued_pcm)
        )
        return m

def test_deepgram_finalization_speech_final():
    """Verify that speech_final=True triggers immediate emission."""
    from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend
    backend = DeepgramASRBackend(api_key="key")
    backend._session_id = "sess-1"
    
    # Mock message
    msg = {
        "type": "Results",
        "is_final": True,
        "speech_final": True,
        "channel": {
            "alternatives": [{"transcript": "point red", "confidence": 0.9}]
        }
    }
    
    backend._handle_message(msg)
    
    transcripts = backend.get_finalized_transcripts()
    assert len(transcripts) == 1
    assert transcripts[0].transcript == "point red"
    assert transcripts[0].finalization_reason == "speech_final"

def test_deepgram_finalization_utterance_end():
    """Verify that UtteranceEnd triggers emission of accumulated segments."""
    from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend
    backend = DeepgramASRBackend(api_key="key")
    backend._session_id = "sess-1"
    
    # Send a final segment without speech_final
    msg1 = {
        "type": "Results",
        "is_final": True,
        "speech_final": False,
        "channel": {
            "alternatives": [{"transcript": "point", "confidence": 0.9}]
        }
    }
    backend._handle_message(msg1)
    assert len(backend.get_finalized_transcripts()) == 0
    
    # Send another final segment
    msg2 = {
        "type": "Results",
        "is_final": True,
        "speech_final": False,
        "channel": {
            "alternatives": [{"transcript": "red", "confidence": 0.9}]
        }
    }
    backend._handle_message(msg2)
    
    # Send UtteranceEnd
    msg3 = {"type": "UtteranceEnd"}
    backend._handle_message(msg3)
    
    transcripts = backend.get_finalized_transcripts()
    assert len(transcripts) == 1
    assert transcripts[0].transcript == "point red"
    assert transcripts[0].finalization_reason == "utterance_end"

def test_deepgram_finalization_timeout_fallback():
    """Verify that inactivity triggers fallback seal."""
    from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend
    import time
    
    backend = DeepgramASRBackend(api_key="key", finalize_timeout_ms=50)
    backend._session_id = "sess-1"
    
    # Send a final segment
    msg = {
        "type": "Results",
        "is_final": True,
        "speech_final": False,
        "channel": {
            "alternatives": [{"transcript": "taškas kairė", "confidence": 0.9}]
        }
    }
    backend._handle_message(msg)
    assert len(backend.get_finalized_transcripts()) == 0
    
    # Wait for fallback (timeout + 300ms, but we test accumulator directly or backend)
    # The backend keepalive loop calls fallback every 0.5s. 
    # Here we can call the check manually to simulate the loop.
    time.sleep(0.5)
    
    # Trigger fallback seal manually or via another message/loop simulation
    res = backend._utterance_accumulator.check_fallback_seal(fallback_ms=100)
    if res:
        text, conf = res
        backend._emit_finalized(text, "finalize_timeout", confidence=conf)
        
    transcripts = backend.get_finalized_transcripts()
    assert len(transcripts) == 1
    assert transcripts[0].transcript == "taškas kairė"
    assert transcripts[0].finalization_reason == "finalize_timeout"

def test_deepgram_duplicate_signal_prevention():
    """Verify that speech_final + UtteranceEnd doesn't duplicate emission."""
    from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend
    backend = DeepgramASRBackend(api_key="key")
    backend._session_id = "sess-1"
    
    msg = {
        "type": "Results",
        "is_final": True,
        "speech_final": True,
        "channel": {
            "alternatives": [{"transcript": "point red", "confidence": 0.9}]
        }
    }
    backend._handle_message(msg)
    
    # Immediate UtteranceEnd for same speech
    backend._handle_message({"type": "UtteranceEnd"})
    
    transcripts = backend.get_finalized_transcripts()
    assert len(transcripts) == 1

def test_deepgram_vad_bypass_regression():
    """Verify that audio is sent to Deepgram even if VAD is false."""
    backend = MockDeepgramBackend()
    processor = VoiceAudioProcessor(
        noise_gate_rms=0.5, # High threshold
        sample_format=SAMPLE_FORMAT_FLOAT32
    )
    
    # Attach backend
    with patch.object(processor, "_get_asr", return_value=backend):
        processor.set_streaming_backend(
            backend, 
            language="lt",
            voice_session_id="sess-1",
            match_id=1
        )
        
    # Simulate a silent frame (RMS will be below 0.5)
    silent_frame = np.zeros(480, dtype=np.float32) # 10ms at 48kHz
    mock_frame = MagicMock()
    mock_frame.to_ndarray.return_value = silent_frame
    mock_frame.sample_rate = 48000
    mock_frame.channels = 1
    mock_frame.format.name = "flt"
    mock_frame.pts = 0.0
    
    # Process the frame
    packet = processor._copy_audio_packet(mock_frame)
    processor._ingest_packet(packet)
    
    # Verify that VAD was false but audio was enqueued
    stats = processor.get_streaming_transport_stats()
    assert stats["streaming_frames_received"] == 1
    assert stats["audio_enqueued"] == 1
    assert len(backend._enqueued_pcm) == 1
    assert processor._above_threshold is False
    assert processor._vad_decision is False

def test_deepgram_pipeline_counters():
    """Verify that all pipeline counters increase as expected."""
    backend = MockDeepgramBackend()
    processor = VoiceAudioProcessor(sample_format=SAMPLE_FORMAT_FLOAT32)
    
    with patch.object(processor, "_get_asr", return_value=backend):
        processor.set_streaming_backend(
            backend, 
            language="lt",
            voice_session_id="sess-1",
            match_id=1
        )
        
    for i in range(5):
        frame = np.random.uniform(-0.1, 0.1, 480).astype(np.float32)
        mock_frame = MagicMock()
        mock_frame.to_ndarray.return_value = frame
        mock_frame.sample_rate = 48000
        mock_frame.channels = 1
        mock_frame.format.name = "flt"
        mock_frame.pts = i * 0.01
        
        packet = processor._copy_audio_packet(mock_frame)
        processor._ingest_packet(packet)
        
    stats = processor.get_streaming_transport_stats()
    assert stats["streaming_frames_received"] == 5
    assert stats["streaming_frames_converted"] == 5
    assert stats["audio_enqueued"] == 5
    assert stats["audio_send_attempts"] == 5
    assert stats["audio_send_success"] == 5
