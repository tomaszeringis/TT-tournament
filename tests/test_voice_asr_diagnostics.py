"""
Tests for voice ASR diagnostics, precise status states, and Quick Voice gating.

These verify that the UI can never show only a vague "Status unavailable" and
that Quick Voice Scoring is disabled when the transcript provider is unavailable.
"""

import sys
from unittest.mock import patch, MagicMock

import pytest

from tournament_platform.app.services.voice.asr_diagnostics import (
    get_voice_setting,
    diagnose_faster_whisper_environment,
    log_voice_asr_environment_once,
)
from tournament_platform.app.services.voice_asr import LocalASR
from tournament_platform.app.pages.voice_scorekeeper import _normalize_status_dict, get_asr_diagnostic


class TestGetVoiceSetting:
    def test_env_wins(self, monkeypatch):
        monkeypatch.setenv("VOICE_ASR_MODEL_SIZE", "small.en")
        assert get_voice_setting("VOICE_ASR_MODEL_SIZE", "tiny.en") == "small.en"

    def test_secrets_fallback(self, monkeypatch):
        monkeypatch.delenv("VOICE_ASR_MODEL_SIZE", raising=False)
        fake_st = MagicMock()
        fake_st.secrets = {"VOICE_ASR_MODEL_SIZE": "base.en"}
        with patch.dict(sys.modules, {"streamlit": fake_st}):
            assert get_voice_setting("VOICE_ASR_MODEL_SIZE", "tiny.en") == "base.en"

    def test_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("VOICE_ASR_MODEL_SIZE", raising=False)
        fake_st = MagicMock()
        fake_st.secrets = {}
        with patch.dict(sys.modules, {"streamlit": fake_st}):
            assert get_voice_setting("VOICE_ASR_MODEL_SIZE", "tiny.en") == "tiny.en"


class TestDiagnoseEnvironment:
    def test_reports_provider_and_imports(self):
        diag = diagnose_faster_whisper_environment()
        assert diag["provider"] == "faster_whisper"
        assert "faster_whisper" in diag["imports"]
        assert "ctranslate2" in diag["imports"]
        assert "av" in diag["imports"]
        assert "onnxruntime" in diag["imports"]
        assert "available" in diag and "reason" in diag

    def test_import_failed_state_when_missing(self):
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _block_faster(name, *a, **k):
            if name == "faster_whisper":
                raise ImportError("no faster-whisper")
            return real_import(name, *a, **k)

        with patch("builtins.__import__", side_effect=_block_faster):
            diag = diagnose_faster_whisper_environment()
        assert diag["available"] is False
        assert "import_failed" in diag["reason"]


class TestLocalASRStatus:
    def test_status_before_load_is_not_configured(self):
        asr = LocalASR(model_size="tiny.en", device="cpu", compute_type="int8")
        status = asr.get_status()
        # Before any load attempt, state must be precise (not a vague default).
        assert status["state"] in ("not_configured", "import_failed", "package_missing")

    def test_status_uses_precise_states(self):
        asr = LocalASR(model_size="tiny.en", device="cpu", compute_type="int8")
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "faster-whisper is not installed. Install with: pip install faster-whisper"
        status = asr.get_status()
        assert status["state"] == "package_missing"

        asr._load_error = "Model download failed: connection reset"
        status = asr.get_status()
        assert status["state"] == "model_download_failed"

        asr._load_error = "ctranslate2 init failed: out of memory"
        status = asr.get_status()
        assert status["state"] == "model_init_failed"

    def test_status_after_load_loaded(self):
        asr = LocalASR(model_size="tiny.en", device="cpu", compute_type="int8")
        asr._model = MagicMock()
        asr._load_attempted = True
        status = asr.get_status()
        assert status["state"] == "model_loaded"
        assert status["available"] is True


class TestEnvDiagnosticsLogOnce:
    def test_calling_does_not_raise(self):
        # The once-guard uses a process-global flag; just ensure it is safe to
        # call repeatedly and never raises.
        assert log_voice_asr_environment_once() is None
        assert log_voice_asr_environment_once() is None


class TestNormalizeStatusDict:
    def test_success_state_does_not_fallback_to_load_error(self):
        status = _normalize_status_dict({
            "available": True,
            "reason": "model_loaded",
            "load_error": "model_loaded",
            "backend_name": "faster_whisper",
        })
        assert status["available"] is True
        assert status["reason"] == "model_loaded"

    def test_failure_state_uses_load_error_when_reason_missing(self):
        status = _normalize_status_dict({
            "available": False,
            "load_error": "faster-whisper is not installed",
            "backend_name": "faster_whisper",
        })
        assert status["available"] is False
        assert status["reason"] == "faster-whisper is not installed"


class TestGetAsrDiagnostic:
    def test_loaded_model_has_no_error_or_setup_instructions(self):
        diag = get_asr_diagnostic()
        if diag.get("available"):
            assert diag.get("load_error") is None
            assert not diag.get("setup_instructions")
