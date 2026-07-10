"""
Tests for voice VAD module (Phase 3).
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from tournament_platform.app.services.voice.vad import (
    AmplitudeVAD,
    WebRTCVAD,
    SileroVAD,
    create_vad,
)


class TestAmplitudeVAD:
    def test_speech_above_threshold(self):
        vad = AmplitudeVAD(threshold=0.01)
        frame = (b"\x7f\x7f" * 100)
        assert vad.is_speech(frame, 16000) is True

    def test_silence_below_threshold(self):
        vad = AmplitudeVAD(threshold=0.5)
        frame = b"\x00\x00" * 100
        assert vad.is_speech(frame, 16000) is False

    def test_empty_frame(self):
        vad = AmplitudeVAD()
        assert vad.is_speech(b"", 16000) is False

    def test_name(self):
        vad = AmplitudeVAD()
        assert vad.name == "amplitude"


class TestWebRTCVAD:
    def test_unavailable_fallback(self):
        with patch.dict(sys.modules, {"webrtcvad": None}):
            vad = WebRTCVAD()
            assert vad.is_speech(b"", 16000) is False
            assert "webrtcvad" in (vad._load_error or "").lower()

    def test_is_speech_calls_vad(self):
        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = True
        with patch.dict(sys.modules, {"webrtcvad": MagicMock(Vad=MagicMock(return_value=mock_vad))}):
            vad = WebRTCVAD()
            frame = b"\x00\x00" * 480
            assert vad.is_speech(frame, 16000) is True
            mock_vad.is_speech.assert_called_once_with(frame, 16000)

    def test_invalid_sample_rate_returns_false(self):
        mock_vad = MagicMock()
        with patch.dict(sys.modules, {"webrtcvad": MagicMock(Vad=MagicMock(return_value=mock_vad))}):
            vad = WebRTCVAD()
            assert vad.is_speech(b"\x00\x00" * 100, 11025) is False

    def test_name(self):
        mock_vad = MagicMock()
        with patch.dict(sys.modules, {"webrtcvad": MagicMock(Vad=MagicMock(return_value=mock_vad))}):
            vad = WebRTCVAD()
            assert vad.name == "webrtcvad"


class TestSileroVAD:
    def test_unavailable_fallback(self):
        with patch.dict(sys.modules, {"silero_vad": None}):
            vad = SileroVAD()
            assert vad.is_speech(b"", 16000) is False

    def test_is_speech_calls_model(self):
        mock_timestamps = [{"start": 0, "end": 100}]
        mock_model = MagicMock()
        with patch.dict(sys.modules, {
            "silero_vad": MagicMock(load_silero_vad=MagicMock(return_value=mock_model), get_speech_timestamps=MagicMock(return_value=mock_timestamps)),
            "torch": MagicMock(),
        }):
            vad = SileroVAD()
            frame = b"\x00\x00" * 480
            assert vad.is_speech(frame, 16000) is True

    def test_name(self):
        with patch.dict(sys.modules, {"silero_vad": None}):
            vad = SileroVAD()
            assert vad.name == "silero"


class TestCreateVad:
    def test_prefer_amplitude(self):
        vad = create_vad(prefer="amplitude")
        assert isinstance(vad, AmplitudeVAD)

    def test_prefer_webrtcvad_available(self):
        mock_vad = MagicMock()
        with patch.dict(sys.modules, {"webrtcvad": MagicMock(Vad=MagicMock(return_value=mock_vad))}):
            vad = create_vad(prefer="webrtcvad")
            assert isinstance(vad, WebRTCVAD)

    def test_prefer_webrtcvad_falls_back(self):
        with patch.dict(sys.modules, {"webrtcvad": None}):
            vad = create_vad(prefer="webrtcvad")
            assert isinstance(vad, AmplitudeVAD)

    def test_prefer_silero_falls_back_to_amplitude(self):
        mock_vad = MagicMock()
        with patch.dict(sys.modules, {"silero_vad": None, "webrtcvad": MagicMock(Vad=MagicMock(return_value=mock_vad))}):
            vad = create_vad(prefer="silero")
            assert isinstance(vad, AmplitudeVAD)

    def test_auto_select_amplitude_vad(self):
        vad = create_vad()
        assert isinstance(vad, AmplitudeVAD)

    def test_auto_select_amplitude_when_none_available(self):
        with patch.dict(sys.modules, {"webrtcvad": None, "silero_vad": None}):
            vad = create_vad()
            assert isinstance(vad, AmplitudeVAD)
