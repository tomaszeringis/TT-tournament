"""
Tests for standings service.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.standings_service import (
    get_standings,
    _parse_score,
    _apply_tie_breaks,
    DEFAULT_TIE_BREAK_ORDER,
)
from tournament_platform.models import Match, MatchStatus, Player, Tournament


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_parse_score_simple():
    assert _parse_score("11-9") == (11, 9)


def test_parse_score_none():
    assert _parse_score(None) == (0, 0)


def test_parse_score_invalid():
    assert _parse_score("not-a-score") == (0, 0)


def test_get_standings_empty_tournament(mock_db):
    tournament = Tournament(id=1, name="Test")
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = []
    standings = get_standings(mock_db, tournament_id=1)
    assert len(standings) == 0


def test_get_standings_with_completed_matches(mock_db):
    p1 = Player(id=1, name="Alice", rating=1200)
    p2 = Player(id=2, name="Bob", rating=1100)
    match = Match(
        id=1,
        tournament_id=1,
        player1_id=1,
        player2_id=2,
        player1="Alice",
        player2="Bob",
        winner_id=1,
        score="11-9",
        status=MatchStatus.completed,
    )
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.all.return_value = [p1, p2]
    standings = get_standings(mock_db, tournament_id=1)
    assert len(standings) == 2
    assert standings[0]["name"] == "Alice"
    assert standings[0]["wins"] == 1
    assert standings[1]["name"] == "Bob"
    assert standings[1]["losses"] == 1


def test_get_standings_tie_break_order(mock_db):
    p1 = Player(id=1, name="A", rating=1000)
    p2 = Player(id=2, name="B", rating=1200)
    match = Match(
        id=1,
        tournament_id=1,
        player1_id=1,
        player2_id=2,
        player1="A",
        player2="B",
        winner_id=1,
        score="11-9",
        status=MatchStatus.completed,
    )
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.all.return_value = [p1, p2]
    standings = get_standings(mock_db, tournament_id=1, tie_break_order=["wins", "rating"])
    assert len(standings) == 2
    assert standings[0]["name"] == "A"
