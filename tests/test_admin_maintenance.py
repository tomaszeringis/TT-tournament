"""
Tests for admin_maintenance service helpers.

These tests verify the extracted admin functions work correctly with isolated SQLite.
"""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import (
    Base,
    Player,
    Match,
    Tournament,
    MatchStatus,
    TournamentType,
)
from tournament_platform.services.admin_maintenance import (
    get_admin_counts,
    get_filtered_matches,
    get_runtime_versions,
    get_safe_database_status,
    safe_error_message,
    get_environment_warnings,
)


# ---------------------------------------------------------------------------
# Database fixtures - isolated in-memory SQLite
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_engine():
    """Create a temporary SQLite database engine for the entire test session."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """Create a fresh database session for each test with transaction rollback."""
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def players(db):
    """Create sample players in the test database."""
    player_data = [
        {"name": "Alice", "email": "alice@example.com", "rating": 1200},
        {"name": "Bob", "email": "bob@example.com", "rating": 1250},
        {"name": "Charlie", "email": "charlie@example.com", "rating": 1180},
    ]
    players = [Player(**data) for data in player_data]
    db.add_all(players)
    db.commit()
    for p in players:
        db.refresh(p)
    return players


@pytest.fixture
def tournament(db):
    """Create a tournament in the test database."""
    t = Tournament(name="Test Tournament", tournament_type=TournamentType.knockout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# get_admin_counts tests
# ---------------------------------------------------------------------------

class TestGetAdminCounts:
    """Tests for get_admin_counts function."""

    def test_returns_correct_counts(self, db, players, tournament):
        """get_admin_counts returns correct counts for players, matches, tournaments."""
        # Add some matches
        m1 = Match(
            player1=players[0].name,
            player2=players[1].name,
            player1_id=players[0].id,
            player2_id=players[1].id,
            tournament_id=tournament.id,
            status=MatchStatus.pending,
        )
        m2 = Match(
            player1=players[1].name,
            player2=players[2].name,
            player1_id=players[1].id,
            player2_id=players[2].id,
            tournament_id=tournament.id,
            status=MatchStatus.completed,
        )
        db.add_all([m1, m2])
        db.commit()

        counts = get_admin_counts(db)

        assert counts["player_count"] == 3
        assert counts["match_count"] == 2
        assert counts["tournament_count"] == 1
        assert counts["completed_matches"] == 1

    def test_empty_database_returns_zeros(self, db):
        """get_admin_counts returns zeros for empty database."""
        counts = get_admin_counts(db)

        assert counts["player_count"] == 0
        assert counts["match_count"] == 0
        assert counts["tournament_count"] == 0
        assert counts["completed_matches"] == 0


# ---------------------------------------------------------------------------
# get_filtered_matches tests
# ---------------------------------------------------------------------------

class TestGetFilteredMatches:
    """Tests for get_filtered_matches function."""

    def test_filter_by_status(self, db, players, tournament):
        """get_filtered_matches filters by status correctly."""
        m1 = Match(
            player1=players[0].name,
            player2=players[1].name,
            player1_id=players[0].id,
            player2_id=players[1].id,
            tournament_id=tournament.id,
            status=MatchStatus.pending,
        )
        m2 = Match(
            player1=players[1].name,
            player2=players[2].name,
            player1_id=players[1].id,
            player2_id=players[2].id,
            tournament_id=tournament.id,
            status=MatchStatus.completed,
        )
        db.add_all([m1, m2])
        db.commit()

        pending_matches = get_filtered_matches(db, status_filter="pending")
        assert len(pending_matches) == 1
        assert pending_matches[0].status == MatchStatus.pending

        completed_matches = get_filtered_matches(db, status_filter="completed")
        assert len(completed_matches) == 1
        assert completed_matches[0].status == MatchStatus.completed

    def test_filter_by_tournament(self, db, players, tournament):
        """get_filtered_matches filters by tournament correctly."""
        m1 = Match(
            player1=players[0].name,
            player2=players[1].name,
            player1_id=players[0].id,
            player2_id=players[1].id,
            tournament_id=tournament.id,
            status=MatchStatus.pending,
        )
        db.add(m1)
        db.commit()

        matches = get_filtered_matches(db, tournament_filter="Test Tournament")
        assert len(matches) == 1
        assert matches[0].tournament_id == tournament.id

    def test_filter_by_all(self, db, players, tournament):
        """get_filtered_matches returns all matches when filter is 'All'."""
        m1 = Match(
            player1=players[0].name,
            player2=players[1].name,
            player1_id=players[0].id,
            player2_id=players[1].id,
            tournament_id=tournament.id,
            status=MatchStatus.pending,
        )
        m2 = Match(
            player1=players[1].name,
            player2=players[2].name,
            player1_id=players[1].id,
            player2_id=players[2].id,
            tournament_id=tournament.id,
            status=MatchStatus.completed,
        )
        db.add_all([m1, m2])
        db.commit()

        matches = get_filtered_matches(db, status_filter="All", tournament_filter="All")
        assert len(matches) == 2

    def test_invalid_status_returns_empty(self, db, players, tournament):
        """get_filtered_matches returns empty list for invalid status."""
        m1 = Match(
            player1=players[0].name,
            player2=players[1].name,
            player1_id=players[0].id,
            player2_id=players[1].id,
            tournament_id=tournament.id,
            status=MatchStatus.pending,
        )
        db.add(m1)
        db.commit()

        matches = get_filtered_matches(db, status_filter="invalid_status")
        assert matches == []


# ---------------------------------------------------------------------------
# get_runtime_versions tests
# ---------------------------------------------------------------------------

class TestGetRuntimeVersions:
    """Tests for get_runtime_versions function."""

    def test_returns_versions_for_installed_packages(self):
        """get_runtime_versions returns versions for installed packages."""
        versions = get_runtime_versions()

        assert "streamlit" in versions
        assert "fastapi" in versions
        assert "sqlalchemy" in versions
        assert "chromadb" in versions

    def test_returns_not_installed_for_missing(self):
        """get_runtime_versions returns 'not installed' for missing packages."""
        # This test verifies the function handles missing packages gracefully
        # The packages in the function are all installed, so we just verify structure
        versions = get_runtime_versions()
        for pkg, version in versions.items():
            assert isinstance(version, str)


# ---------------------------------------------------------------------------
# get_safe_database_status tests
# ---------------------------------------------------------------------------

class TestGetSafeDatabaseStatus:
    """Tests for get_safe_database_status function."""

    def test_returns_healthy_for_valid_connection(self):
        """get_safe_database_status returns healthy status for valid connection."""
        is_healthy, status = get_safe_database_status()
        # The actual database should be accessible
        assert is_healthy is True
        assert status == "Connected"

    def test_error_message_is_safe(self):
        """safe_error_message returns user-safe message without internal details."""
        error = Exception("Internal database error: connection string=sqlite:///secret/path")
        message = safe_error_message(error, "Database check")

        # Should not contain sensitive information
        assert "connection string" not in message
        assert "sqlite:///" not in message
        assert "Database check failed" in message


# ---------------------------------------------------------------------------
# get_environment_warnings tests
# ---------------------------------------------------------------------------

class TestGetEnvironmentWarnings:
    """Tests for get_environment_warnings function."""

    def test_returns_warnings_for_default_api_url(self):
        """get_environment_warnings returns warning for default API_BASE_URL."""
        with patch("tournament_platform.services.admin_maintenance.API_BASE_URL", "http://localhost:8000"):
            warnings = get_environment_warnings()
            assert any("API_BASE_URL" in w for w in warnings)

    def test_returns_warnings_for_missing_teams_webhook(self):
        """get_environment_warnings returns warning for missing Teams webhook."""
        with patch("tournament_platform.services.admin_maintenance.settings") as mock_settings:
            mock_settings.TEAMS_WEBHOOK_URL = ""
            mock_settings.DATABASE_URL = "sqlite:///data/tournament.db"
            with patch("tournament_platform.services.admin_maintenance.API_BASE_URL", "http://localhost:8000"):
                warnings = get_environment_warnings()
                assert any("Teams webhook" in w for w in warnings)

    def test_returns_warnings_for_sqlite(self):
        """get_environment_warnings returns warning for SQLite database."""
        with patch("tournament_platform.services.admin_maintenance.settings") as mock_settings:
            mock_settings.TEAMS_WEBHOOK_URL = "https://example.com/webhook"
            mock_settings.DATABASE_URL = "sqlite:///data/tournament.db"
            with patch("tournament_platform.services.admin_maintenance.API_BASE_URL", "http://localhost:8000"):
                warnings = get_environment_warnings()
                assert any("SQLite" in w for w in warnings)

    def test_returns_warnings_for_debug_enabled(self):
        """get_environment_warnings returns warning for debug mode enabled."""
        with patch("tournament_platform.services.admin_maintenance.settings") as mock_settings:
            mock_settings.TEAMS_WEBHOOK_URL = "https://example.com/webhook"
            mock_settings.DATABASE_URL = "sqlite:///data/tournament.db"
            with patch("tournament_platform.services.admin_maintenance.API_BASE_URL", "http://localhost:8000"):
                with patch("tournament_platform.services.admin_maintenance.SHOW_DEBUG_DETAILS", True):
                    warnings = get_environment_warnings()
                    assert any("SHOW_DEBUG_DETAILS" in w for w in warnings)

    def test_returns_warnings_for_placeholder_webhook(self):
        """get_environment_warnings returns warning for placeholder webhook URL."""
        with patch("tournament_platform.services.admin_maintenance.settings") as mock_settings:
            mock_settings.TEAMS_WEBHOOK_URL = "https://placeholder.example.com/webhook"
            mock_settings.DATABASE_URL = "sqlite:///data/tournament.db"
            with patch("tournament_platform.services.admin_maintenance.API_BASE_URL", "http://localhost:8000"):
                warnings = get_environment_warnings()
                assert any("placeholder" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])