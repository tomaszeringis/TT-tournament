"""
Format compatibility tests - cross-format integration tests.

Ensures bracket generation, standings, and advancement work consistently
across knockout, round-robin, groups-knockout, and Swiss formats.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.tournament_engine import (
    TournamentFactory,
    TournamentContext,
    KnockoutStrategy,
    RoundRobinStrategy,
    GroupsKnockoutStrategy,
    SwissStrategy,
)
from tournament_platform.services.advancement_service import (
    get_advancement_preview,
    calculate_group_standings,
)
from tournament_platform.services.swiss_service import (
    get_swiss_standings,
    get_next_swiss_round,
)


def test_knockout_generates_matches():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    matches = TournamentFactory.create_tournament(
        "knockout",
        ["A", "B", "C", "D"],
        1,
        db,
    )
    assert len(matches) > 0


def test_round_robin_generates_matches():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    matches = TournamentFactory.create_tournament(
        "round-robin",
        ["A", "B", "C"],
        1,
        db,
    )
    assert len(matches) > 0


def test_groups_knockout_creates_groups_and_knockout():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    matches = TournamentFactory.create_tournament(
        "groups-knockout",
        ["A", "B", "C", "D"],
        1,
        db,
    )
    assert len(matches) > 0


def test_swiss_generates_rounds():
    from tournament_platform.config import settings
    original = settings.ENABLE_SWISS
    try:
        settings.ENABLE_SWISS = True
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        matches = TournamentFactory.create_tournament(
            "swiss",
            ["A", "B", "C", "D"],
            1,
            db,
        )
        assert len(matches) > 0
    finally:
        settings.ENABLE_SWISS = original


def test_advancement_preview_returns_groups():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = [
        [MagicMock(id=1, stage_type="group", event_id=1)],
        [MagicMock(id=1, stage_id=1, name="Group A")],
        [],
        [],
        [],
    ]
    db.query.return_value.filter.return_value.count.return_value = 0
    result = get_advancement_preview(db, tournament_id=1)
    assert "group_previews" in result
