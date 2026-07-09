"""
Tests for ASR backend abstraction layer, factory, and fallback logic.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.app.services.asr_backends.faster_whisper_backend import FasterWhisperBackend
from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_vocab import VoiceVocabulary


class TestFasterWhisperBackend:
    """Tests for the faster-whisper backend wrapper."""

    def test_backend_name(self):
        backend = FasterWhisperBackend()
        assert backend.backend_name == "faster_whisper"

    def test_transcribe_pcm_delegates_to_local_asr(self):
        backend = FasterWhisperBackend()
        mock_asr = MagicMock()
        mock_asr.transcribe_chunk.return_value = "hello world"
        backend._asr = mock_asr

        result = backend.transcribe_pcm(b"\x00\x00")
        assert result == "hello world"
        mock_asr.transcribe_chunk.assert_called_once_with(b"\x00\x00")

    def test_get_status_returns_backend_status(self):
        backend = FasterWhisperBackend()
        mock_asr = MagicMock()
        mock_asr.get_status.return_value = {
            "available": True,
            "model_size": "base.en",
            "device": "cpu",
            "compute_type": "int8",
        }
        mock_asr.get_setup_instructions.return_value = "instructions"
        backend._asr = mock_asr

        status = backend.get_status()
        assert isinstance(status, BackendStatus)
        assert status.backend_name == "faster_whisper"
        assert status.available is True
        assert status.setup_instructions == "instructions"

    def test_is_available_returns_false_on_exception(self):
        backend = FasterWhisperBackend()
        with patch.object(backend, "_get_asr", side_effect=Exception("boom")):
            assert backend.is_available() is False


class TestASRBackendFactory:
    """Tests for the ASR backend factory."""

    def test_default_backend_is_faster_whisper(self):
        with patch.dict("os.environ", {}, clear=True):
            backend = ASRBackendFactory.create()
            assert backend.backend_name == "faster_whisper"

    def test_explicit_backend_faster_whisper(self):
        with patch.dict("os.environ", {"VOICE_ASR_BACKEND": "faster_whisper"}, clear=True):
            backend = ASRBackendFactory.create()
            assert backend.backend_name == "faster_whisper"

    def test_unknown_backend_falls_back_to_faster_whisper(self):
        with patch.dict("os.environ", {"VOICE_ASR_BACKEND": "unknown_backend"}, clear=True):
            backend = ASRBackendFactory.create()
            assert backend.backend_name == "faster_whisper"

    def test_fallback_backend_used_when_primary_unavailable(self):
        with patch.dict(
            "os.environ",
            {
                "VOICE_ASR_BACKEND": "unknown_backend",
                "VOICE_ASR_FALLBACK_BACKEND": "faster_whisper",
            },
            clear=True,
        ):
            backend = ASRBackendFactory.create()
            assert backend.backend_name == "faster_whisper"

    def test_speechbrain_backend_not_available_without_dependency(self):
        with patch.dict("os.environ", {"VOICE_ASR_BACKEND": "speechbrain"}, clear=True):
            backend = ASRBackendFactory.create()
            assert backend.backend_name == "faster_whisper"

    def test_backend_status_returns_status(self):
        with patch.dict("os.environ", {}, clear=True):
            status = ASRBackendFactory.backend_status()
            assert isinstance(status, BackendStatus)
            assert "backend_name" in status.__dict__

    def test_backend_status_on_error(self):
        with patch(
            "tournament_platform.app.services.asr_backends.factory.FasterWhisperBackend",
            side_effect=Exception("fail"),
        ):
            status = ASRBackendFactory.backend_status()
            assert isinstance(status, BackendStatus)
            assert status.backend_name in ("unknown", "faster_whisper")
            assert status.available is False

    def test_backend_names_normalized(self):
        with patch.dict("os.environ", {"VOICE_ASR_BACKEND": "Faster-Whisper"}, clear=True):
            backend = ASRBackendFactory.create()
            assert backend.backend_name == "faster_whisper"
