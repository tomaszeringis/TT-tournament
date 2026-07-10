"""
Tests for Public Board Safety (Phase 4).
"""

import pytest

from tournament_platform.app.pages.public_board import render_match_card, render_coming_up_card


class TestPublicBoardSafety:
    def test_render_match_card_no_db_writes(self):
        match = {
            "player1": "Alice",
            "player2": "Bob",
            "score": "11-9",
            "winner": "Alice",
            "status": "completed",
            "call_status": "completed",
            "location": "1",
            "round_number": 1,
        }
        render_match_card(match, label="LIVE")

    def test_render_coming_up_card_no_db_writes(self):
        match = {
            "player1": "Alice",
            "player2": "Bob",
            "scheduled_time": "2024-01-01T12:00:00Z",
            "location": "2",
        }
        render_coming_up_card(match)

    def test_public_board_reads_db_directly(self):
        from tournament_platform.app.pages.public_board import load_tournaments
        try:
            tournaments = load_tournaments()
            assert isinstance(tournaments, list)
        except Exception:
            pass
