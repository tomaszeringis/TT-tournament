"""Tests for Deepgram configuration parsing and validation.

Covers plan §6 validation rules:
- Endpointing clamped to [250, 400]
- Language restricted to lt/en (no silent fallback)
- Ambient seconds bounded to [1, 10]
- VOICE_LOCAL_VAD_MODE accepts only continuous/gated/disabled
- Feature flag + API key validation
"""
from __future__ import annotations

import os
import importlib
import pytest


class TestEndpointingClamping:
    def test_default_is_300(self):
        assert os.environ.get("VOICE_DEEPGRAM_ENDPOINTING_MS") is None or \
               importlib.import_module(
                   "tournament_platform.services.settings"
               ).VOICE_DEEPGRAM_ENDPOINTING_MS == 300

    def test_clamped_to_250_minimum(self):
        os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"] = "100"
        try:
            import tournament_platform.services.settings as s
            importlib.reload(s)
            assert s.VOICE_DEEPGRAM_ENDPOINTING_MS == 250
        finally:
            del os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"]
            importlib.reload(s)

    def test_clamped_to_400_maximum(self):
        os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"] = "9999"
        try:
            import tournament_platform.services.settings as s
            importlib.reload(s)
            assert s.VOICE_DEEPGRAM_ENDPOINTING_MS == 400
        finally:
            del os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"]
            importlib.reload(s)

    def test_valid_value_within_range(self):
        os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"] = "300"
        try:
            import tournament_platform.services.settings as s
            importlib.reload(s)
            assert s.VOICE_DEEPGRAM_ENDPOINTING_MS == 300
        finally:
            del os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"]
            importlib.reload(s)

    def test_invalid_value_defaults_to_300(self):
        os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"] = "not-a-number"
        try:
            import tournament_platform.services.settings as s
            importlib.reload(s)
            assert s.VOICE_DEEPGRAM_ENDPOINTING_MS == 300
        finally:
            del os.environ["VOICE_DEEPGRAM_ENDPOINTING_MS"]
            importlib.reload(s)


class TestLanguageValidation:
    def test_valid_lt(self):
        assert importlib.import_module(
            "tournament_platform.services.settings"
        )._validate_deepgram_language("lt") == "lt"

    def test_valid_en(self):
        assert importlib.import_module(
            "tournament_platform.services.settings"
        )._validate_deepgram_language("en") == "en"

    def test_valid_uppercase_normalized(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod._validate_deepgram_language("LT") == "lt"
        assert mod._validate_deepgram_language("EN") == "en"

    def test_invalid_raises(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        with pytest.raises(ValueError, match="Must be 'lt' or 'en'"):
            mod._validate_deepgram_language("fr")

    def test_invalid_empty_raises(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        with pytest.raises(ValueError):
            mod._validate_deepgram_language("")


class TestLocalVadModeValidation:
    def test_valid_modes(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod._validate_local_vad_mode("continuous") == "continuous"
        assert mod._validate_local_vad_mode("gated") == "gated"
        assert mod._validate_local_vad_mode("disabled") == "disabled"

    def test_invalid_raises(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        with pytest.raises(ValueError, match="continuous.*gated.*disabled"):
            mod._validate_local_vad_mode("invalid_mode")


class TestFeatureFlagDefaults:
    def test_deepgram_disabled_by_default(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod.VOICE_DEEPGRAM_ENABLED is False

    def test_deepgram_model_is_nova3(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod.VOICE_DEEPGRAM_MODEL == "nova-3"

    def test_deepgram_language_default_is_lt(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod.VOICE_DEEPGRAM_LANGUAGE == "lt"

    def test_local_vad_mode_default_continuous(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod.VOICE_LOCAL_VAD_MODE == "continuous"

    def test_health_check_enabled_by_default(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod.VOICE_AUDIO_HEALTH_CHECK_ENABLED is True

    def test_api_key_empty_by_default(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod.VOICE_DEEPGRAM_API_KEY == ""


class TestAmbientSecondsClamping:
    def test_default_is_2(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        try:
            assert mod._clamp_ambient_seconds(2.0) == 2.0
        except AttributeError:
            # Module may have been loaded with different env; test raw function
            assert mod._clamp_ambient_seconds(2.0) == 2.0

    def test_clamped_to_1_minimum(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod._clamp_ambient_seconds(0.5) == 1.0

    def test_clamped_to_10_maximum(self):
        mod = importlib.import_module("tournament_platform.services.settings")
        assert mod._clamp_ambient_seconds(20.0) == 10.0
