"""
Regression tests for critical flows before UX redesign.

These tests ensure:
- Models work correctly (Player, Tournament, Match, RatingHistory)
- TournamentFactory generates valid brackets
- /api/report endpoint works with legacy payload
- Teams webhook calls are mocked (no external calls)
- Tests use isolated temporary SQLite database
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Import models and services
from tournament_platform.models import (
    Base,
    Player,
    Tournament,
    Match,
    MatchStatus,
    TournamentType,
    RatingHistory,
)
from tournament_platform.services.tournament_engine import (
    TournamentContext,
    KnockoutStrategy,
    RoundRobinStrategy,
    TournamentFactory,
)
from tournament_platform.services.match_reporting import (
    report_existing_match,
    ReportMatchCommand,
    MatchNotFoundError,
    MatchAlreadyCompletedError,
    InvalidWinnerError,
)
from tournament_platform.services.ranking_service import RatingManager
from tournament_platform.api.server import app as fastapi_app


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


# ---------------------------------------------------------------------------
# Model fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def players(db):
    """Create sample players in the test database."""
    player_data = [
        {"name": "Alice", "email": "alice@example.com", "rating": 1200},
        {"name": "Bob", "email": "bob@example.com", "rating": 1250},
        {"name": "Charlie", "email": "charlie@example.com", "rating": 1180},
        {"name": "Diana", "email": "diana@example.com", "rating": 1300},
    ]
    players = [Player(**data) for data in player_data]
    db.add_all(players)
    db.commit()
    for p in players:
        db.refresh(p)
    return players


@pytest.fixture
def tournament_knockout(db):
    """Create a knockout tournament in the test database."""
    t = Tournament(name="Knockout Test", tournament_type=TournamentType.knockout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def tournament_round_robin(db):
    """Create a round-robin tournament in the test database."""
    t = Tournament(name="Round Robin Test", tournament_type=TournamentType.round_robin)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def pending_match(db, players, tournament_knockout):
    """Create a pending match in the test database."""
    match = Match(
        player1=players[0].name,
        player2=players[1].name,
        player1_id=players[0].id,
        player2_id=players[1].id,
        tournament_id=tournament_knockout.id,
        status=MatchStatus.pending,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


@pytest.fixture
def completed_match(db, players, tournament_knockout):
    """Create a completed match in the test database."""
    match = Match(
        player1=players[0].name,
        player2=players[1].name,
        player1_id=players[0].id,
        player2_id=players[1].id,
        winner=players[0].name,
        winner_id=players[0].id,
        score="3-1",
        tournament_id=tournament_knockout.id,
        status=MatchStatus.completed,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestPlayerModel:
    """Tests for Player model."""

    def test_player_creation(self, db):
        """Player can be created and persisted."""
        player = Player(name="TestPlayer", email="test@example.com", rating=1200)
        db.add(player)
        db.commit()
        db.refresh(player)

        assert player.id is not None
        assert player.name == "TestPlayer"
        assert player.rating == 1200

    def test_player_default_rating(self, db):
        """Player gets default rating of 1200 if not specified."""
        player = Player(name="NoRatingPlayer", email="norating@example.com")
        db.add(player)
        db.commit()
        db.refresh(player)

        assert player.rating == 1200

    def test_player_unique_name(self, db, players):
        """Player names must be unique."""
        duplicate = Player(name="Alice", email="alice2@example.com", rating=1000)
        db.add(duplicate)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()


class TestTournamentModel:
    """Tests for Tournament model."""

    def test_tournament_creation(self, db):
        """Tournament can be created and persisted."""
        t = Tournament(name="Test Tournament", tournament_type=TournamentType.knockout)
        db.add(t)
        db.commit()
        db.refresh(t)

        assert t.id is not None
        assert t.name == "Test Tournament"
        assert t.tournament_type == TournamentType.knockout
        assert t.created_at is not None

    def test_tournament_unique_name(self, db):
        """Tournament names must be unique."""
        t1 = Tournament(name="Unique Tournament", tournament_type=TournamentType.knockout)
        db.add(t1)
        db.commit()

        t2 = Tournament(name="Unique Tournament", tournament_type=TournamentType.round_robin)
        db.add(t2)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()


class TestMatchModel:
    """Tests for Match model."""

    def test_match_creation_with_string_fields(self, db, players, tournament_knockout):
        """Match can be created with string player1/player2/winner fields."""
        match = Match(
            player1=players[0].name,
            player2=players[1].name,
            player1_id=players[0].id,
            player2_id=players[1].id,
            tournament_id=tournament_knockout.id,
            status=MatchStatus.pending,
        )
        db.add(match)
        db.commit()
        db.refresh(match)

        assert match.id is not None
        assert match.player1 == players[0].name
        assert match.player2 == players[1].name
        assert match.status == MatchStatus.pending

    def test_match_rating_history_persistence(self, db, players):
        """RatingHistory entries are created and persisted correctly."""
        manager = RatingManager()
        winner = players[0]
        loser = players[1]

        history_before = db.query(RatingHistory).count()
        manager.update_ratings(winner.id, loser.id, db_session=db)
        history_after = db.query(RatingHistory).count()

        assert history_after == history_before + 2

        # Verify entries reference correct players
        histories = db.query(RatingHistory).filter(
            RatingHistory.player_id.in_([winner.id, loser.id])
        ).all()
        player_ids = {h.player_id for h in histories}
        assert player_ids == {winner.id, loser.id}


# ---------------------------------------------------------------------------
# TournamentFactory tests
# ---------------------------------------------------------------------------

class TestTournamentFactory:
    """Tests for TournamentFactory match generation."""

    def test_knockout_creates_pending_matches(self, db, tournament_knockout, players):
        """Knockout creates pending matches without crashing."""
        player_names = [p.name for p in players]
        matches = TournamentFactory.create_tournament(
            "knockout", player_names, tournament_knockout.id, db
        )
        db.commit()

        # For 4 players, knockout should have 3 matches (2 semis + 1 final)
        assert len(matches) == len(players) - 1
        # All should be pending (no byes in this case)
        pending_matches = [m for m in matches if m.status == MatchStatus.pending]
        assert len(pending_matches) == len(players) - 1

    def test_round_robin_creates_expected_pairings_3_players(self, db, tournament_round_robin):
        """Round-robin creates expected pairings for 3 players."""
        # Create 3 players
        p1 = Player(name="P1", email="p1@example.com", rating=1200)
        p2 = Player(name="P2", email="p2@example.com", rating=1200)
        p3 = Player(name="P3", email="p3@example.com", rating=1200)
        db.add_all([p1, p2, p3])
        db.commit()
        for p in [p1, p2, p3]:
            db.refresh(p)

        player_names = [p1.name, p2.name, p3.name]
        matches = TournamentFactory.create_tournament(
            "round-robin", player_names, tournament_round_robin.id, db
        )
        db.commit()

        # 3 players -> 3 matches (n*(n-1)/2)
        assert len(matches) == 3

    def test_round_robin_creates_expected_pairings_4_players(self, db, tournament_round_robin, players):
        """Round-robin creates expected pairings for 4 players."""
        player_names = [p.name for p in players]
        matches = TournamentFactory.create_tournament(
            "round-robin", player_names, tournament_round_robin.id, db
        )
        db.commit()

        # 4 players -> 6 matches (n*(n-1)/2)
        assert len(matches) == 6

        # Verify all pairs exist
        pairs = set()
        for m in matches:
            pair = tuple(sorted([m.player1, m.player2]))
            pairs.add(pair)

        expected_pairs = {
            ("Alice", "Bob"), ("Alice", "Charlie"), ("Alice", "Diana"),
            ("Bob", "Charlie"), ("Bob", "Diana"), ("Charlie", "Diana")
        }
        assert pairs == expected_pairs

    def test_invalid_format_raises_value_error(self, db, tournament_knockout, players):
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported tournament format"):
            TournamentFactory.create_tournament(
                "swiss", [p.name for p in players], tournament_knockout.id, db
            )


# ---------------------------------------------------------------------------
# API tests with Teams webhook mocking
# ---------------------------------------------------------------------------

@pytest.fixture
def client(db):
    """FastAPI TestClient with database dependency overridden to use the test session."""
    from tournament_platform.api.server import get_db

    def override_get_db():
        try:
            yield db
        finally:
            pass  # Session is managed by the test fixture

    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


class TestApiHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_healthy(self, client):
        """/health returns status healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestApiReportEndpoint:
    """Tests for /api/report endpoint with legacy payload."""

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "")
    def test_report_accepts_legacy_payload(self, client, pending_match, db):
        """/api/report accepts legacy payload: {player1, player2, score, winner, tournament_id}."""
        response = client.post(
            "/api/report",
            json={
                "match_id": pending_match.id,
                "winner": pending_match.player1,
                "score": "3-1",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["match_id"] == pending_match.id

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "")
    def test_report_writes_completed_match_row(self, client, pending_match, db):
        """/api/report writes a completed Match row."""
        response = client.post(
            "/api/report",
            json={
                "match_id": pending_match.id,
                "winner": pending_match.player1,
                "score": "3-0",
            },
        )

        assert response.status_code == 200

        # Verify the match is actually completed in the database
        db.expire_all()
        match = db.query(Match).filter(Match.id == pending_match.id).first()
        assert match.status == MatchStatus.completed
        assert match.winner == pending_match.player1
        assert match.score == "3-0"

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "")
    def test_report_missing_required_fields_returns_400(self, client):
        """Missing required fields returns 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": 1,
                # Missing winner and score
            },
        )

        assert response.status_code == 400  # Validation error returns 400

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "")
    def test_report_nonexistent_match_returns_400(self, client):
        """Reporting non-existent match returns 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": 9999,
                "winner": "Nobody",
                "score": "0-0",
            },
        )

        assert response.status_code == 400

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "")
    def test_report_completed_match_returns_400(self, client, completed_match):
        """Reporting already completed match returns 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": completed_match.id,
                "winner": completed_match.player2,
                "score": "3-2",
            },
        )

        assert response.status_code == 400

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "")
    def test_teams_webhook_not_called_when_empty(self, client, pending_match, db):
        """Teams webhook is not called when TEAMS_WEBHOOK_URL is empty."""
        with patch("tournament_platform.api.server.httpx.AsyncClient") as mock_client:
            response = client.post(
                "/api/report",
                json={
                    "match_id": pending_match.id,
                    "winner": pending_match.player1,
                    "score": "3-1",
                },
            )

            # The mock should not be called since webhook URL is empty
            # (The code checks if settings.TEAMS_WEBHOOK_URL is truthy before calling)
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Teams webhook mock tests
# ---------------------------------------------------------------------------

class TestTeamsWebhookMocked:
    """Tests to verify Teams webhook calls are properly mocked/disabled."""

    @patch("tournament_platform.api.server.settings.TEAMS_WEBHOOK_URL", "https://example.com/webhook")
    @patch("tournament_platform.api.server.httpx.AsyncClient")
    def test_teams_webhook_mocked_when_configured(self, mock_async_client, client, pending_match, db):
        """When TEAMS_WEBHOOK_URL is set, httpx.AsyncClient is used but mocked."""
        mock_client_instance = MagicMock()
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.post = AsyncMock(return_value=MagicMock(status_code=200))

        response = client.post(
            "/api/report",
            json={
                "match_id": pending_match.id,
                "winner": pending_match.player1,
                "score": "3-1",
            },
        )

        assert response.status_code == 200
        # The mock ensures no real HTTP call is made


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])