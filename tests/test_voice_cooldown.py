"""
Tests for voice event duplicate-command cooldown.

The cooldown logic lives in ``tournament_platform.app.pages.voice_scorekeeper``
(``_process_voice_events``). These tests verify the cooldown key comparison
and time-window math in isolation so we can catch regressions without
bootstrapping the full Streamlit runtime.
"""

import time

from tournament_platform.app.services.voice_parser import VoiceParser


COOLDOWN_MS = 1200.0


def _event_key(event):
    return (event.type, event.player, event.score_a, event.score_b)


def _is_duplicate(event, last_key, last_ts):
    return _event_key(event) == last_key and (time.time() - last_ts) * 1000.0 < COOLDOWN_MS


class TestVoiceCooldown:
    """Duplicate-command suppression for continuous listening."""

    def setup_method(self):
        self.parser = VoiceParser()

    def test_same_set_score_within_cooldown_is_duplicate(self):
        event = self.parser.parse("five four")
        last_key = _event_key(event)
        last_ts = time.time()
        assert _is_duplicate(event, last_key, last_ts) is True

    def test_same_set_score_after_cooldown_is_not_duplicate(self):
        event = self.parser.parse("five four")
        last_key = _event_key(event)
        last_ts = time.time() - 2.0
        assert _is_duplicate(event, last_key, last_ts) is False

    def test_different_set_score_is_not_duplicate(self):
        event1 = self.parser.parse("five four")
        event2 = self.parser.parse("six four")
        last_key = _event_key(event1)
        last_ts = time.time()
        assert _is_duplicate(event2, last_key, last_ts) is False

    def test_same_increment_within_cooldown_is_duplicate(self):
        event = self.parser.parse("point player one")
        last_key = _event_key(event)
        last_ts = time.time()
        assert _is_duplicate(event, last_key, last_ts) is True

    def test_increment_a_then_b_is_not_duplicate(self):
        event_a = self.parser.parse("point player one")
        event_b = self.parser.parse("point player two")
        last_key = _event_key(event_a)
        last_ts = time.time()
        assert _is_duplicate(event_b, last_key, last_ts) is False

    def test_undo_then_undo_after_cooldown(self):
        undo1 = self.parser.parse("undo")
        last_key = _event_key(undo1)
        last_ts = time.time()
        assert _is_duplicate(undo1, last_key, last_ts) is True

        undo2 = self.parser.parse("undo")
        last_ts = time.time() - 2.0
        assert _is_duplicate(undo2, last_key, last_ts) is False

    def test_color_alias_cooldown(self):
        blue = self.parser.parse("blue")
        red = self.parser.parse("red")
        last_key = _event_key(blue)
        last_ts = time.time()
        assert _is_duplicate(blue, last_key, last_ts) is True
        assert _is_duplicate(red, last_key, last_ts) is False

    def test_set_score_different_values_same_player(self):
        event1 = self.parser.parse("ten eight")
        event2 = self.parser.parse("eleven nine")
        last_key = _event_key(event1)
        last_ts = time.time()
        assert _is_duplicate(event2, last_key, last_ts) is False
