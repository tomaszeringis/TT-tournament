"""
Integration tests for observability and performance features.
"""

import pytest
from unittest.mock import MagicMock
import time

from tournament_platform.services.observability_service import (
    ObservabilityService,
    LatencyTracker,
    get_latency_tracker,
)
from tournament_platform.services.materialized_read_models import MaterializedReadModels
from tournament_platform.models import Match, Tournament, Player, MatchStatus


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_latency_tracker_records_and_computes_p95():
    tracker = get_latency_tracker()
    tracker._latencies.clear()

    for i in range(100):
        tracker.record("test_op", float(i))

    p95 = tracker.get_p95("test_op")
    assert p95 is not None
    assert p95 >= 95.0


def test_observability_service_records_query_latency(mock_db):
    match = Match(id=1, tournament_id=1, status=MatchStatus.completed, call_status="not_called")
    mock_db.query.return_value.all.return_value = [match]

    service = ObservabilityService(mock_db)
    service.collect_match_metrics()

    tracker = get_latency_tracker()
    stats = tracker.get_stats("db.query.matches")
    assert stats["count"] >= 1
    assert stats["p95_ms"] is not None


def test_materialized_read_models_caches_results(mock_db):
    tournament = MagicMock()
    tournament.id = 1
    tournament.name = "Test"
    tournament.tournament_type = MagicMock(value="knockout")
    tournament.matches = []
    tournament.created_at = None

    mock_db.query.return_value.order_by.return_value.all.return_value = [tournament]
    mock_db.query.return_value.count.return_value = 0

    read_models = MaterializedReadModels(mock_db)
    result1 = read_models.get_tournament_list()
    result2 = read_models.get_tournament_list()

    assert result1 == result2
    assert len(result1) == 1


def test_materialized_read_models_invalidates_cache(mock_db):
    tournament = MagicMock()
    tournament.id = 1
    tournament.name = "Test"
    tournament.tournament_type = MagicMock(value="knockout")
    tournament.matches = []
    tournament.created_at = None

    mock_db.query.return_value.order_by.return_value.all.return_value = [tournament]
    mock_db.query.return_value.count.return_value = 0

    read_models = MaterializedReadModels(mock_db)
    result1 = read_models.get_tournament_list()

    mock_db.query.return_value.order_by.return_value.all.return_value = [tournament, MagicMock()]
    read_models.invalidate("tournament_list")
    result2 = read_models.get_tournament_list()

    assert len(result2) == 2


def test_materialized_read_models_dashboard_summary(mock_db):
    match = MagicMock()
    match.status = MatchStatus.completed
    match.call_status = "not_called"
    mock_db.query.return_value.filter.return_value.count.return_value = 10
    mock_db.query.return_value.filter.return_value.all.return_value = [match]

    read_models = MaterializedReadModels(mock_db)
    summary = read_models.get_dashboard_summary(tournament_id=1)

    assert "total_players" in summary
    assert "total_matches" in summary
    assert "cached_at" in summary
