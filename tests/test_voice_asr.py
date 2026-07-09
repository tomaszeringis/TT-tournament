"""
Tests for LocalASR graceful degradation and status reporting.
"""

import pytest
from unittest.mock import patch, MagicMock

from tournament_platform.app.services.voice_asr import LocalASR, LocalASRError, _ASR_MODEL_CACHE


class TestLocalASRStatus:
    """Tests for LocalASR status and setup instructions."""

    def test_get_status_before_load(self):
        asr = LocalASR()
        status = asr.get_status()
        assert "available" in status
        assert status["model_size"] == "base.en"
        assert status["device"] == "cpu"
        assert status["compute_type"] == "int8"

    def test_get_setup_instructions_missing_faster_whisper(self):
        asr = LocalASR()
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "faster-whisper is not installed. Install it with: pip install faster-whisper"
        instructions = asr.get_setup_instructions()
        assert "faster-whisper" in instructions.lower()
        assert "pip install" in instructions

    def test_get_setup_instructions_other_error(self):
        asr = LocalASR()
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "Some other error"
        instructions = asr.get_setup_instructions()
        assert "ASR Error" in instructions
        assert "Some other error" in instructions

    def test_get_setup_instructions_default(self):
        asr = LocalASR()
        instructions = asr.get_setup_instructions()
        assert "faster-whisper" in instructions.lower()
        assert "VOICE_ASR_MODEL_SIZE" in instructions

    def test_is_available_returns_false_on_missing_dependency(self):
        asr = LocalASR()
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "faster-whisper is not installed"
        assert asr.is_available() is False

    def test_transcribe_returns_empty_on_missing_dependency(self):
        asr = LocalASR()
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "faster-whisper is not installed"
        result = asr.transcribe_chunk(b"\x00\x00" * 1000)
        assert result == ""

    def test_transcribe_returns_empty_on_empty_input(self):
        asr = LocalASR()
        result = asr.transcribe_chunk(b"")
        assert result == ""

    def test_environment_variable_overrides(self):
        with patch("tournament_platform.app.services.voice_asr.VOICE_ASR_MODEL_SIZE", "small.en"), \
             patch("tournament_platform.app.services.voice_asr.VOICE_ASR_DEVICE", "cuda"), \
             patch("tournament_platform.app.services.voice_asr.VOICE_ASR_COMPUTE_TYPE", "float16"):
            asr = LocalASR()
            assert asr.model_size == "small.en"
            assert asr.device == "cuda"
            assert asr.compute_type == "float16"

    def test_default_environment_values(self):
        with patch("tournament_platform.app.services.voice_asr.VOICE_ASR_MODEL_SIZE", "base.en"), \
             patch("tournament_platform.app.services.voice_asr.VOICE_ASR_DEVICE", "cpu"), \
             patch("tournament_platform.app.services.voice_asr.VOICE_ASR_COMPUTE_TYPE", "int8"):
            asr = LocalASR()
            assert asr.model_size == "base.en"
            assert asr.device == "cpu"
            assert asr.compute_type == "int8"


class TestLocalASRModelCache:
    """Tests for the module-level model cache."""

    def test_cache_is_dict(self):
        assert isinstance(_ASR_MODEL_CACHE, dict)

    def test_cache_shared_across_instances(self):
        # Clear cache for clean test
        _ASR_MODEL_CACHE.clear()
        try:
            asr1 = LocalASR(model_size="base.en", device="cpu", compute_type="int8")
            asr2 = LocalASR(model_size="base.en", device="cpu", compute_type="int8")
            # Trigger model loading on first instance
            mock_model = MagicMock()
            with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=mock_model))}):
                asr1._load_model()
            # Second instance should reuse the cached model
            with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=mock_model))}):
                asr2._load_model()
            # Both should share the same cache key
            key = ("base.en", "cpu", "int8")
            assert key in _ASR_MODEL_CACHE
            assert _ASR_MODEL_CACHE[key] is mock_model
        finally:
            _ASR_MODEL_CACHE.clear()

    def test_different_configs_different_cache_keys(self):
        _ASR_MODEL_CACHE.clear()
        try:
            asr1 = LocalASR(model_size="base.en", device="cpu", compute_type="int8")
            asr2 = LocalASR(model_size="small.en", device="cpu", compute_type="int8")
            key1 = ("base.en", "cpu", "int8")
            key2 = ("small.en", "cpu", "int8")
            assert key1 != key2
        finally:
            _ASR_MODEL_CACHE.clear()

    def test_load_model_uses_cache(self):
        """Verify that _load_model stores model in cache."""
        _ASR_MODEL_CACHE.clear()
        try:
            asr = LocalASR(model_size="base.en", device="cpu", compute_type="int8")
            # Mock the WhisperModel import to avoid actual loading
            mock_model = MagicMock()
            with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=mock_model))}):
                asr._load_model()
            key = ("base.en", "cpu", "int8")
            assert key in _ASR_MODEL_CACHE
            assert _ASR_MODEL_CACHE[key] is mock_model
        finally:
            _ASR_MODEL_CACHE.clear()
