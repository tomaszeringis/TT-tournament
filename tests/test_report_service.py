"""
Tests for report service.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.report_service import get_event_report, get_match_report
from tournament_platform.models import Tournament, Match, MatchStatus, Player


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_get_event_report_returns_error_for_missing_tournament(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    result = get_event_report(mock_db, tournament_id=1)
    assert "error" in result


def test_get_match_report_returns_error_for_missing_match(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    result = get_match_report(mock_db, match_id=1)
    assert "error" in result
