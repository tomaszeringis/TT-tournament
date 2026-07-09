"""
Tests for the voice speaker identification module (Phase 2).
"""

import pytest

from tournament_platform.app.services.voice_speaker import (
    SpeakerTagger,
    SpeakerProfile,
    DEFAULT_SPEAKERS,
)


class TestSpeakerTagger:
    """Tests for SpeakerTagger."""

    @pytest.fixture
    def tagger(self):
        return SpeakerTagger(mode="manual", allowed_speakers=DEFAULT_SPEAKERS)

    def test_manual_mode_set_speaker(self, tagger):
        tagger.set_current_speaker("Referee")
        assert tagger.get_current_speaker() == "Referee"

    def test_manual_mode_clear_speaker(self, tagger):
        tagger.set_current_speaker("Referee")
        tagger.set_current_speaker(None)
        assert tagger.get_current_speaker() is None

    def test_manual_mode_empty_string_clears(self, tagger):
        tagger.set_current_speaker("Referee")
        tagger.set_current_speaker("")
        assert tagger.get_current_speaker() is None

    def test_off_mode_ignores_speaker(self, tagger):
        tagger.mode = "off"
        tagger.set_current_speaker("Referee")
        assert tagger.get_current_speaker() is None

    def test_attach_label_sets_speaker(self, tagger):
        tagger.set_current_speaker("Referee")

        class FakeEvent:
            speaker_label = None

        event = FakeEvent()
        tagger.attach_label(event)
        assert event.speaker_label == "Referee"

    def test_attach_label_off_mode_sets_none(self, tagger):
        tagger.mode = "off"

        class FakeEvent:
            speaker_label = "Referee"

        event = FakeEvent()
        tagger.attach_label(event)
        assert event.speaker_label is None

    def test_attach_label_no_speaker_sets_none(self, tagger):
        class FakeEvent:
            speaker_label = "Referee"

        event = FakeEvent()
        tagger.attach_label(event)
        assert event.speaker_label is None

    def test_is_allowed_when_not_required(self, tagger):
        tagger.require_speaker = False
        assert tagger.is_allowed("Referee") is True
        assert tagger.is_allowed(None) is True
        assert tagger.is_allowed("Unknown") is True

    def test_is_allowed_when_required(self, tagger):
        tagger.require_speaker = True
        assert tagger.is_allowed("Referee") is True
        assert tagger.is_allowed(None) is False
        assert tagger.is_allowed("Unknown") is False

    def test_enroll_creates_profile(self, tagger):
        profile = tagger.enroll("Referee")
        assert profile.label == "Referee"
        assert profile.embedding is None
        assert len(tagger.list_profiles()) == 1

    def test_enroll_invalid_speaker_raises(self, tagger):
        with pytest.raises(ValueError):
            tagger.enroll("Invalid Speaker")

    def test_invalid_speaker_label_ignored(self, tagger):
        tagger.set_current_speaker("Invalid Speaker")
        assert tagger.get_current_speaker() is None


class TestSpeakerProfile:
    """Tests for SpeakerProfile."""

    def test_default_values(self):
        profile = SpeakerProfile(label="Referee")
        assert profile.label == "Referee"
        assert profile.embedding is None
        assert profile.enrolled_at > 0
