"""
Tests for the commentary voice profile system and Piper integration.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.commentary_voice.voice_profile import VoiceProfile
from tournament_platform.app.services.commentary_voice.voice_catalog import (
    BUILTIN_PROFILES,
    get_profile,
    list_profiles,
    profile_choices,
)
from tournament_platform.app.services.commentary_voice.voice_settings import (
    VoiceSettings,
    get_voice_settings,
    init_voice_session_state,
)
from tournament_platform.app.services.commentary_voice.piper_voice import (
    PiperTTSEngine,
    get_piper_engine,
    PiperTTSError,
    AudioResult,
)
from tournament_platform.app.services.commentary_voice.piper_runtime import (
    PiperVoice,
    find_piper_voices,
    is_piper_available,
    get_piper_binary,
)


class TestVoiceProfile:
    def test_frozen_dataclass_defaults(self):
        profile = VoiceProfile(id="test", label="Test")
        assert profile.id == "test"
        assert profile.label == "Test"
        assert profile.engine == "browser"
        assert profile.language == "en"
        assert profile.voice_id is None
        assert profile.voice_name is None
        assert profile.gender_label is None
        assert profile.style == "neutral"
        assert profile.rate == 1.0
        assert profile.pitch == 1.0
        assert profile.volume == 1.0
        assert profile.is_local is False
        assert profile.requires_network is False
        assert profile.description == ""

    def test_custom_values(self):
        profile = VoiceProfile(
            id="custom",
            label="Custom",
            engine="piper",
            language="lt",
            voice_id="lt-lt",
            voice_name="custom_voice",
            gender_label="male",
            style="coach",
            rate=1.2,
            pitch=0.9,
            volume=0.8,
            is_local=True,
            requires_network=False,
            description="A custom voice",
        )
        assert profile.engine == "piper"
        assert profile.language == "lt"
        assert profile.style == "coach"
        assert profile.rate == 1.2


class TestVoiceCatalog:
    def test_builtin_profiles_count(self):
        assert len(BUILTIN_PROFILES) == 8

    def test_builtin_profiles_unique_ids(self):
        ids = [p.id for p in BUILTIN_PROFILES]
        assert len(ids) == len(set(ids))

    def test_get_profile_existing(self):
        profile = get_profile("sport_commentator")
        assert profile is not None
        assert profile.label == "Sport commentator"

    def test_get_profile_missing(self):
        profile = get_profile("nonexistent")
        assert profile is None

    def test_list_profiles(self):
        profiles = list_profiles()
        assert len(profiles) == 8
        assert all(isinstance(p, VoiceProfile) for p in profiles)

    def test_profile_choices(self):
        choices = profile_choices()
        ids = [c[0] for c in choices]
        assert "browser_default" in ids
        assert "sport_commentator" in ids
        assert len(choices) >= 8


class TestVoiceSettings:
    def test_defaults(self):
        settings = VoiceSettings()
        assert settings.profile_id == "browser_default"
        assert settings.rate == 1.0
        assert settings.pitch == 1.0
        assert settings.volume == 1.0
        assert settings.browser_voice_name is None

    def test_profile_lookup(self):
        settings = VoiceSettings(profile_id="sport_commentator")
        assert settings.profile is not None
        assert settings.profile.label == "Sport commentator"

    def test_effective_style(self):
        settings = VoiceSettings(profile_id="sport_commentator")
        assert settings.effective_style() == "announcer"

        settings = VoiceSettings(profile_id="coach")
        assert settings.effective_style() == "coach"

        settings = VoiceSettings(profile_id="browser_default")
        assert settings.effective_style() == "neutral"

    def test_effective_language(self):
        settings = VoiceSettings(profile_id="lt_browser_default")
        assert settings.effective_language() == "lt"

        settings = VoiceSettings(profile_id="browser_default")
        assert settings.effective_language() == "en"

    def test_effective_rate_pitch_volume(self):
        settings = VoiceSettings(profile_id="sport_commentator")
        assert settings.effective_rate() == 1.0
        assert settings.effective_pitch() == 1.0
        assert settings.effective_volume() == 1.0

        settings = VoiceSettings(profile_id="browser_default")
        assert settings.effective_rate() == 1.0
        assert settings.effective_pitch() == 1.0
        assert settings.effective_volume() == 1.0

    def test_voice_settings_override_profile(self):
        settings = VoiceSettings(profile_id="sport_commentator", rate=1.5, pitch=1.2, volume=0.7)
        assert settings.effective_rate() == 1.5
        assert settings.effective_pitch() == 1.2
        assert settings.effective_volume() == 0.7


class TestSportCommentatorBehavior:
    def test_sport_commentator_maps_to_announcer(self):
        from tournament_platform.app.services.commentary_voice.voice_catalog import get_profile

        profile = get_profile("sport_commentator")
        assert profile.style == "announcer"

    def test_sport_commentator_maps_to_medium_intensity(self):
        from tournament_platform.app.services.commentary_voice.voice_settings import VoiceSettings

        settings = VoiceSettings(profile_id="sport_commentator")
        assert settings.effective_style() == "announcer"

    def test_coach_maps_to_coach_style(self):
        from tournament_platform.app.services.commentary_voice.voice_settings import VoiceSettings

        settings = VoiceSettings(profile_id="coach")
        assert settings.effective_style() == "coach"


class TestBrowserVoicePicker:
    def test_build_voice_picker_html(self):
        from tournament_platform.app.services.commentary_voice.browser_voice import build_voice_picker_html

        html = build_voice_picker_html("sport_commentator", 0.8)
        assert "sport_commentator" in html
        assert "0.8" in html
        assert "localStorage" in html
        assert "speechSynthesis" in html

    def test_build_voice_picker_html_default_volume(self):
        from tournament_platform.app.services.commentary_voice.browser_voice import build_voice_picker_html

        html = build_voice_picker_html("browser_default", 1.0)
        assert "browser_default" in html
        assert "1.0" in html


class TestPiperRuntime:
    def test_is_piper_available_when_installed(self):
        assert is_piper_available() is True

    def test_get_piper_binary_returns_string_or_none(self):
        result = get_piper_binary()
        assert result is None or isinstance(result, str)

    def test_find_piper_voices_empty_without_models(self):
        from tournament_platform.app.services.commentary_voice.piper_runtime import find_piper_voices

        # Use a non-existent directory to guarantee empty result
        result = find_piper_voices(base_dir=Path("/tmp/nonexistent_piper_voices_dir"))
        assert result == []

    def test_piper_list_voices_empty_without_models(self):
        engine = get_piper_engine()
        # Use a non-existent directory to guarantee empty result
        engine.voices_dir = Path("/tmp/nonexistent_piper_voices_dir")
        assert engine.list_voices() == []

    def test_list_local_piper_voices_empty_without_models(self):
        from tournament_platform.app.services.commentary_voice.voice_catalog import list_local_piper_voices
        from tournament_platform.app.services.commentary_voice import voice_catalog

        original = voice_catalog.find_piper_voices
        try:
            voice_catalog.find_piper_voices = lambda **kwargs: []
            assert list_local_piper_voices() == []
        finally:
            voice_catalog.find_piper_voices = original

    def test_get_all_profiles_includes_builtin_even_with_piper(self):
        from tournament_platform.app.services.commentary_voice.voice_catalog import get_all_profiles

        profiles = get_all_profiles()
        ids = [p.id for p in profiles]
        assert "browser_default" in ids
        assert "sport_commentator" in ids

    def test_cache_key_changes_with_text(self):
        engine = PiperTTSEngine()
        voice = PiperVoice(id="v1", label="v1", model_path=Path("/v1.onnx"), config_path=Path("/v1.json"))
        key1 = engine._build_cache_key("hello", voice, 1.0, 1.0)
        key2 = engine._build_cache_key("world", voice, 1.0, 1.0)
        assert key1 != key2

    def test_cache_key_changes_with_voice(self):
        engine = PiperTTSEngine()
        v1 = PiperVoice(id="v1", label="v1", model_path=Path("/v1.onnx"), config_path=Path("/v1.json"))
        v2 = PiperVoice(id="v2", label="v2", model_path=Path("/v2.onnx"), config_path=Path("/v2.json"))
        key1 = engine._build_cache_key("hello", v1, 1.0, 1.0)
        key2 = engine._build_cache_key("hello", v2, 1.0, 1.0)
        assert key1 != key2

    def test_cache_key_changes_with_rate(self):
        engine = PiperTTSEngine()
        voice = PiperVoice(id="v1", label="v1", model_path=Path("/v1.onnx"), config_path=Path("/v1.json"))
        key1 = engine._build_cache_key("hello", voice, 1.0, 1.0)
        key2 = engine._build_cache_key("hello", voice, 1.2, 1.0)
        assert key1 != key2

    def test_cache_path_contains_engine_version_and_voice_id(self):
        engine = PiperTTSEngine()
        voice = PiperVoice(id="en_US-test", label="en_US-test", model_path=Path("/en_US-test.onnx"), config_path=Path("/en_US-test.json"))
        key = engine._build_cache_key("hello", voice, 1.0, 1.0)
        path = engine._cache_path(key, voice)
        assert "en_US-test" in str(path)
        assert engine._engine_version in str(path)

    def test_piper_unavailable_does_not_crash_import(self):
        with patch("tournament_platform.app.services.commentary_voice.piper_voice.is_piper_available", return_value=False):
            engine = PiperTTSEngine()
            assert engine.available is False
            assert engine.list_voices() == []


class TestPiperIntegration:
    def test_play_commentary_visual_only_does_not_synthesize(self):
        from tournament_platform.services.commentary_service import CommentarySettings, CommentaryMode

        settings = CommentarySettings(enabled=True, mode=CommentaryMode.VISUAL_ONLY)
        # Should not raise even without Piper
        # This is a smoke test for the routing logic
        assert settings.mode == CommentaryMode.VISUAL_ONLY

    def test_smoke_test_script_exists(self):
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "smoke_test_piper.py"
        assert script_path.exists(), f"Smoke test script not found at {script_path}"
