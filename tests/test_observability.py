"""
Tests for observability service.
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from tournament_platform.services.observability_service import ObservabilityService
from tournament_platform.services.health_check_service import (
    check_database_health,
    check_readiness,
    check_liveness,
    get_health_summary,
    HealthStatus,
)
from tournament_platform.models import Match, Tournament, Player, AuditLog, MatchStatus


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_observability_service_collects_match_metrics(mock_db):
    match = Match(id=1, tournament_id=1, status=MatchStatus.completed, call_status="not_called")
    mock_db.query.return_value.all.return_value = [match]

    service = ObservabilityService(mock_db)
    metrics = service.collect_match_metrics()

    assert metrics["total"] == 1
    assert metrics["completed"] == 1
    assert metrics["completion_rate"] == 100.0


def test_observability_service_collects_tournament_metrics(mock_db):
    tournament = MagicMock()
    tournament.matches = []
    mock_db.query.return_value.all.return_value = [tournament]

    service = ObservabilityService(mock_db)
    metrics = service.collect_tournament_metrics()

    assert metrics["total"] == 1
    assert metrics["without_matches"] == 1


def test_health_check_database_healthy(mock_db):
    mock_db.query.return_value.limit.return_value.first.return_value = MagicMock()

    result = check_database_health(mock_db)
    assert result["status"] == HealthStatus.HEALTHY
    assert "response_time_seconds" in result


def test_health_check_database_unhealthy(mock_db):
    mock_db.query.return_value.limit.return_value.first.side_effect = Exception("DB error")

    result = check_database_health(mock_db)
    assert result["status"] == HealthStatus.UNHEALTHY
    assert "error" in result["details"].lower() or "DB error" in result["details"]


def test_health_check_liveness():
    result = check_liveness(None)
    assert result["status"] == HealthStatus.HEALTHY
    assert "timestamp" in result


def test_health_summary_returns_all_checks(mock_db):
    mock_db.query.return_value.limit.return_value.first.return_value = MagicMock()

    summary = get_health_summary(mock_db)
    assert "readiness" in summary
    assert "liveness" in summary
    assert "overall_status" in summary
