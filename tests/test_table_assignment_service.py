"""
Tests for table assignment service.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.table_assignment_service import recommend_table
from tournament_platform.models import Match, VenueTable


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_recommend_table_returns_none_for_missing_match(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    result = recommend_table(mock_db, match_id=1)
    assert result["recommended_table"] is None
    assert result["reason"] == "Match not found"


def test_recommend_table_prefers_inactive_table(mock_db):
    match = Match(id=1, tournament_id=1)
    table1 = VenueTable(id=1, name="Table 1", is_active=0)
    table2 = VenueTable(id=2, name="Table 2", is_active=1)
    mock_db.query.return_value.filter.return_value.first.return_value = match
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.order_by.return_value.all.return_value = [table1, table2]
    result = recommend_table(mock_db, match_id=1, tournament_id=1)
    assert result["recommended_table"] == "Table 1"
    assert result["reason"] == "Inactive table available"
