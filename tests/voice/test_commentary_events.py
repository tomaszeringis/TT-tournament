"""
Tests for CommentaryEvent and CommentaryEventType.
"""

import pytest

from tournament_platform.app.services.commentary.events import (
    CommentaryEvent,
    CommentaryEventType,
)


class TestCommentaryEventType:
    def test_has_twelve_types(self):
        assert len(list(CommentaryEventType)) == 12

    def test_point_won(self):
        assert CommentaryEventType.POINT_WON == "point_won"

    def test_serve_change(self):
        assert CommentaryEventType.SERVE_CHANGE == "serve_change"

    def test_deuce(self):
        assert CommentaryEventType.DEUCE == "deuce"

    def test_advantage(self):
        assert CommentaryEventType.ADVANTAGE == "advantage"

    def test_game_point(self):
        assert CommentaryEventType.GAME_POINT == "game_point"

    def test_match_point(self):
        assert CommentaryEventType.MATCH_POINT == "match_point"

    def test_game_won(self):
        assert CommentaryEventType.GAME_WON == "game_won"

    def test_match_won(self):
        assert CommentaryEventType.MATCH_WON == "match_won"

    def test_undo(self):
        assert CommentaryEventType.UNDO == "undo"

    def test_reset(self):
        assert CommentaryEventType.RESET == "reset"

    def test_result_submitted(self):
        assert CommentaryEventType.RESULT_SUBMITTED == "result_submitted"

    def test_voice_command_rejected(self):
        assert CommentaryEventType.VOICE_COMMAND_REJECTED == "voice_command_rejected"


class TestCommentaryEvent:
    def test_compute_event_id_deterministic(self):
        eid1 = CommentaryEvent.compute_event_id(
            "point_won", match_id=1, score_before="0-0", score_after="1-0", game_number=1, server="A"
        )
        eid2 = CommentaryEvent.compute_event_id(
            "point_won", match_id=1, score_before="0-0", score_after="1-0", game_number=1, server="A"
        )
        assert eid1 == eid2
        assert len(eid1) == 16

    def test_compute_event_id_unique_per_input(self):
        eid1 = CommentaryEvent.compute_event_id("point_won", match_id=1, score_before="0-0", score_after="1-0", game_number=1, server="A")
        eid2 = CommentaryEvent.compute_event_id("point_won", match_id=2, score_before="0-0", score_after="1-0", game_number=1, server="A")
        assert eid1 != eid2

    def test_defaults(self):
        ev = CommentaryEvent(event_type=CommentaryEventType.POINT_WON, event_id="abc123")
        assert ev.priority == 2
        assert ev.importance == "normal"
        assert ev.source == "unknown"
        assert ev.match_id is None
        assert ev.game_number == 1
        assert ev.player is None
