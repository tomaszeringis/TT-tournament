"""
Tests for match event service.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.match_event_service import (
    record_match_event,
    get_match_events,
    generate_match_summary,
)
from tournament_platform.models import Match, MatchStatus, Player


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_record_match_event_returns_event_dict(mock_db):
    event = record_match_event(mock_db, match_id=1, event_type="score_update", payload={"score": "11-9"})
    assert event["match_id"] == 1
    assert event["event_type"] == "score_update"
    assert event["payload"]["score"] == "11-9"


def test_generate_match_summary_returns_error_for_missing_match(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    result = generate_match_summary(mock_db, match_id=1)
    assert "error" in result
