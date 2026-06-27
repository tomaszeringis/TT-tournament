"""Tests for tournament_platform.services.settings."""

import importlib
import os


def test_settings_import():
    """The settings module must be importable."""
    mod = importlib.import_module("tournament_platform.services.settings")
    assert hasattr(mod, "API_BASE_URL")
    assert hasattr(mod, "OLLAMA_MODEL")
    assert hasattr(mod, "ENABLE_VOICE_ENTRY")
    assert hasattr(mod, "ENABLE_RULES_ASSISTANT")
    assert hasattr(mod, "ENABLE_RANKING_INTELLIGENCE")
    assert hasattr(mod, "ENABLE_SPOKEN_CONFIRMATION")
    assert hasattr(mod, "KEEP_AUDIO_FILES")
    assert hasattr(mod, "SPEECH_MODEL_SIZE")


def test_defaults():
    """Defaults should preserve current behavior."""
    mod = importlib.import_module("tournament_platform.services.settings")
    assert mod.API_BASE_URL == "http://localhost:8000"
    assert mod.OLLAMA_MODEL == "llama3:latest"
    assert mod.ENABLE_VOICE_ENTRY is True
    assert mod.ENABLE_RULES_ASSISTANT is True
    assert mod.ENABLE_RANKING_INTELLIGENCE is True
    assert mod.ENABLE_SPOKEN_CONFIRMATION is False
    assert mod.KEEP_AUDIO_FILES is False
    assert mod.SPEECH_MODEL_SIZE == "base"


def test_env_override(monkeypatch):
    """Environment variables should override defaults."""
    monkeypatch.setenv("API_BASE_URL", "http://example.com:9000")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:latest")
    monkeypatch.setenv("ENABLE_VOICE_ENTRY", "false")
    monkeypatch.setenv("SPEECH_MODEL_SIZE", "small")

    mod = importlib.import_module("tournament_platform.services.settings")
    # Re-import to pick up env changes (module-level constants are cached)
    importlib.reload(mod)

    assert mod.API_BASE_URL == "http://example.com:9000"
    assert mod.OLLAMA_MODEL == "llama3.1:latest"
    assert mod.ENABLE_VOICE_ENTRY is False
    assert mod.SPEECH_MODEL_SIZE == "small"
