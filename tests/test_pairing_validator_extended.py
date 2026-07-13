"""
Tests for extended pairing validator.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.pairing_validator import (
    validate_tournament_pairings,
    detect_rematches,
    validate_groups_knockout_advancement,
    detect_incomplete_groups,
)
from tournament_platform.models import (
    Match, MatchStatus, Player, Tournament, Stage, Group, Entry
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_detect_rematches_finds_duplicate_pairs(mock_db):
    p1 = Player(id=1, name="A")
    p2 = Player(id=2, name="B")
    matches = [
        Match(id=1, tournament_id=1, player1_id=1, player2_id=2, player1="A", player2="B"),
        Match(id=2, tournament_id=1, player1_id=2, player2_id=1, player1="B", player2="A"),
    ]
    mock_db.query.return_value.filter.return_value.all.return_value = matches
    rematches = detect_rematches(mock_db, tournament_id=1)
    assert len(rematches) == 1
    assert rematches[0]["match_ids"] == [1, 2]


def test_validate_groups_knockout_advancement_no_event(mock_db):
    mock_db.query.return_value.filter.return_value.all.return_value = []
    result = validate_groups_knockout_advancement(mock_db, tournament_id=1)
    assert result["ready"] is False


def test_detect_incomplete_groups_returns_issues(mock_db):
    stage = Stage(id=1, event_id=1, stage_type="group", name="Group A")
    group = Group(id=1, stage_id=1, name="Group A")
    entry = Entry(id=1, group_id=1)
    entry2 = Entry(id=2, group_id=1)
    match = Match(id=1, stage_id=1, status=MatchStatus.pending)

    mock_db.query.return_value.filter.return_value.all.side_effect = [
        [stage],
        [group],
        [entry, entry2],
        [],
    ]
    mock_db.query.return_value.filter.return_value.count.return_value = 0

    issues = detect_incomplete_groups(mock_db, tournament_id=1)
    assert any(i["type"] == "incomplete_group" for i in issues)
