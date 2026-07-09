"""
Tests for the voice TTS confirmation adapter (Phase 4).
"""

import pytest

from tournament_platform.app.services.voice_tts import TTSConfirmationAdapter, TTSMode


class TestTTSConfirmationAdapter:
    """Tests for TTSConfirmationAdapter."""

    @pytest.fixture
    def adapter(self):
        return TTSConfirmationAdapter(enabled=True, mode=TTSMode.VISUAL_ONLY.value)

    def test_visual_only_never_speaks(self, adapter):
        assert adapter.should_speak("increment") is False
        assert adapter.should_speak("undo") is False
        assert adapter.should_speak("game_won") is False

    def test_off_mode_never_speaks(self, adapter):
        adapter.mode = TTSMode.OFF
        assert adapter.should_speak("increment") is False

    def test_audio_every_score_speaks_for_increment(self, adapter):
        adapter.mode = TTSMode.AUDIO_EVERY_SCORE
        assert adapter.should_speak("increment") is True
        assert adapter.should_speak("undo") is True
        assert adapter.should_speak("set_score") is True

    def test_audio_every_score_skips_unknown(self, adapter):
        adapter.mode = TTSMode.AUDIO_EVERY_SCORE
        assert adapter.should_speak("unknown") is False

    def test_audio_after_game_speaks_only_for_game_won(self, adapter):
        adapter.mode = TTSMode.AUDIO_AFTER_GAME
        assert adapter.should_speak("game_won") is True
        assert adapter.should_speak("match_won") is True
        assert adapter.should_speak("increment") is False

    def test_audio_on_uncertainty_speaks_on_low_confidence(self, adapter):
        adapter.mode = TTSMode.AUDIO_ON_UNCERTAINTY
        assert adapter.should_speak("increment", confidence=0.5) is True
        assert adapter.should_speak("increment", confidence=0.9) is False

    def test_audio_on_uncertainty_speaks_on_requires_confirmation(self, adapter):
        adapter.mode = TTSMode.AUDIO_ON_UNCERTAINTY
        assert adapter.should_speak("increment", confidence=0.9, requires_confirmation=True) is True

    def test_disabled_adapter_never_speaks(self, adapter):
        adapter.enabled = False
        adapter.mode = TTSMode.AUDIO_EVERY_SCORE
        assert adapter.should_speak("increment") is False

    def test_speak_noop_when_disabled(self, adapter):
        adapter.enabled = False
        adapter.mode = TTSMode.AUDIO_EVERY_SCORE
        # Should not raise; just no-op
        adapter.speak("test")

    def test_speak_noop_when_visual_only(self, adapter):
        adapter.mode = TTSMode.VISUAL_ONLY
        adapter.speak("test")  # should not raise

    def test_queue_and_flush(self, adapter):
        adapter.enabled = True
        adapter.mode = TTSMode.AUDIO_EVERY_SCORE
        adapter.queue("hello")
        adapter.queue("world")
        assert len(adapter._speak_queue) == 2
        adapter.flush_queue()
        assert len(adapter._speak_queue) == 0
