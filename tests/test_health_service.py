"""
Tests for Tournament Health Service.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from tournament_platform.services.health_service import (
    get_tournament_health,
    get_health_summary,
    get_health_thresholds,
    DEFAULT_STALE_ACTIVE_MINUTES,
    DEFAULT_STALE_CALLED_MINUTES,
)
from tournament_platform.models import Match, MatchStatus, VenueTable, Tournament


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    return db


@pytest.fixture
def sample_tournament():
    """Create a sample tournament."""
    return Tournament(id=1, name="Test Tournament")


@pytest.fixture
def sample_tables():
    """Create sample venue tables."""
    return [
        VenueTable(id=1, name="Table 1", is_active=True),
        VenueTable(id=2, name="Table 2", is_active=True),
        VenueTable(id=3, name="Table 3", is_active=False),
    ]


# ============================================================================
# Threshold Tests
# ============================================================================

def test_get_health_thresholds_returns_defaults():
    """Test that get_health_thresholds returns sensible defaults."""
    thresholds = get_health_thresholds()
    
    assert "stale_active_minutes" in thresholds
    assert "stale_called_minutes" in thresholds
    assert "delayed_threshold_minutes" in thresholds
    
    assert thresholds["stale_active_minutes"] == DEFAULT_STALE_ACTIVE_MINUTES
    assert thresholds["stale_called_minutes"] == DEFAULT_STALE_CALLED_MINUTES


# ============================================================================
# Health Computation Tests
# ============================================================================

def test_get_tournament_health_empty_tournament(mock_db, sample_tournament):
    """Test health for tournament with no matches."""
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    assert result["tournament_id"] == 1
    assert result["tournament_name"] == "Test Tournament"
    assert result["match_counts"]["active"] == 0
    assert result["match_counts"]["called"] == 0
    assert result["match_counts"]["delayed"] == 0
    assert result["match_counts"]["completed"] == 0
    assert result["issues"] == []


def test_get_tournament_health_detects_missing_table(mock_db, sample_tournament):
    """Test that matches without tables are flagged."""
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="active",
        location=None,
        scheduled_time=datetime.now(timezone.utc),  # Add scheduled time to avoid that issue
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    # Should have missing_table issue (and no missing_scheduled_time since we set it)
    missing_table_issues = [i for i in result["issues"] if i["issue_type"] == "missing_table"]
    assert len(missing_table_issues) == 1
    assert missing_table_issues[0]["match_id"] == 1


def test_get_tournament_health_detects_missing_scheduled_time(mock_db, sample_tournament):
    """Test that matches without scheduled time are flagged."""
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="active",
        location="Table 1",
        scheduled_time=None,
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    missing_time_issues = [i for i in result["issues"] if i["issue_type"] == "missing_scheduled_time"]
    assert len(missing_time_issues) == 1


def test_get_tournament_health_detects_stale_active_match(mock_db, sample_tournament):
    """Test that active matches older than threshold are flagged as stale."""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=DEFAULT_STALE_ACTIVE_MINUTES + 10)
    
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="active",
        location="Table 1",
        started_at=old_time,
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    stale_issues = [i for i in result["issues"] if i["issue_type"] == "stale_active"]
    assert len(stale_issues) == 1
    assert stale_issues[0]["severity"] == "error"


def test_get_tournament_health_detects_stale_called_match(mock_db, sample_tournament):
    """Test that called matches older than threshold are flagged as stale."""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=DEFAULT_STALE_CALLED_MINUTES + 10)
    
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="called",
        location="Table 1",
        called_at=old_time,
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    stale_issues = [i for i in result["issues"] if i["issue_type"] == "stale_called"]
    assert len(stale_issues) == 1
    assert stale_issues[0]["severity"] == "warning"


def test_get_tournament_health_detects_completed_without_score(mock_db, sample_tournament):
    """Test that completed matches without score are flagged."""
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="completed",
        status=MatchStatus.completed,
        score=None,
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    score_issues = [i for i in result["issues"] if i["issue_type"] == "completed_without_score"]
    assert len(score_issues) == 1
    assert score_issues[0]["severity"] == "error"


def test_get_tournament_health_detects_completed_without_winner(mock_db, sample_tournament):
    """Test that completed matches without winner are flagged."""
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="completed",
        status=MatchStatus.completed,
        score="3-1",
        winner=None,
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    winner_issues = [i for i in result["issues"] if i["issue_type"] == "completed_without_winner"]
    assert len(winner_issues) == 1
    assert winner_issues[0]["severity"] == "error"


def test_get_tournament_health_detects_table_conflict(mock_db, sample_tournament):
    """Test that conflicting table assignments are detected."""
    match1 = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="active",
        location="Table 1",
    )
    match2 = Match(
        id=2,
        player1="Player C",
        player2="Player D",
        call_status="active",
        location="Table 1",
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match1, match2]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    conflict_issues = [i for i in result["issues"] if i["issue_type"] == "table_conflict"]
    assert len(conflict_issues) == 2  # Each match reports the other as conflict


def test_get_tournament_health_table_utilization(mock_db, sample_tournament, sample_tables):
    """Test table utilization calculation."""
    match = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="active",
        location="Table 1",
    )
    
    # Mock tables query
    mock_db.query.return_value.all.return_value = sample_tables
    
    # Mock matches query
    mock_db.query.return_value.filter.return_value.all.return_value = [match]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_tournament_health(mock_db, tournament_id=1)
    
    assert result["table_utilization"]["active_tables"] == 2
    assert result["table_utilization"]["total_tables"] == 3
    assert result["table_utilization"]["busy_tables"] == 1


# ============================================================================
# Health Summary Tests
# ============================================================================

def test_get_health_summary_aggregates_issues(mock_db, sample_tournament):
    """Test that health summary correctly aggregates issue counts."""
    match1 = Match(
        id=1,
        player1="Player A",
        player2="Player B",
        call_status="active",
        location=None,
        scheduled_time=datetime.now(timezone.utc),  # Add scheduled time to avoid that issue
    )
    match2 = Match(
        id=2,
        player1="Player C",
        player2="Player D",
        call_status="active",
        location=None,
        scheduled_time=datetime.now(timezone.utc),  # Add scheduled time to avoid that issue
    )
    
    mock_db.query.return_value.filter.return_value.all.return_value = [match1, match2]
    mock_db.query.return_value.filter.return_value.first.return_value = sample_tournament
    
    result = get_health_summary(mock_db, tournament_id=1)
    
    assert result["issue_count"] == 2
    assert result["issue_counts"]["missing_table"] == 2