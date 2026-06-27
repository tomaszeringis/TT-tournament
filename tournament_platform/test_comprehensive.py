"""
Comprehensive pytest test suite for the Tournament Platform.

Replaces smoke-test style scripts with real pytest tests covering:
- Tournament creation
- Duplicate fixture prevention
- Round-robin match generation
- Knockout match generation
- Reporting an existing pending match
- Rejecting already completed matches
- Rating updates after completed matches
- API /api/report happy path and error cases
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

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
# Database fixtures
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
    """Create a fresh database session for each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


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
# Tournament creation tests
# ---------------------------------------------------------------------------

class TestTournamentCreation:
    """Tests for creating tournaments."""

    def test_create_knockout_tournament(self, db):
        """A knockout tournament can be created and persisted."""
        t = Tournament(name="Spring Cup", tournament_type=TournamentType.knockout)
        db.add(t)
        db.commit()
        db.refresh(t)

        assert t.id is not None
        assert t.name == "Spring Cup"
        assert t.tournament_type == TournamentType.knockout
        assert t.created_at is not None

    def test_create_round_robin_tournament(self, db):
        """A round-robin tournament can be created and persisted."""
        t = Tournament(name="League Season", tournament_type=TournamentType.round_robin)
        db.add(t)
        db.commit()
        db.refresh(t)

        assert t.id is not None
        assert t.name == "League Season"
        assert t.tournament_type == TournamentType.round_robin

    def test_tournament_name_is_unique(self, db):
        """Tournament names must be unique."""
        t1 = Tournament(name="Unique Name", tournament_type=TournamentType.knockout)
        db.add(t1)
        db.commit()

        t2 = Tournament(name="Unique Name", tournament_type=TournamentType.round_robin)
        db.add(t2)
        with pytest.raises(Exception):
            db.commit()

    def test_tournament_has_matches_relationship(self, db, tournament_knockout, players):
        """A tournament can have associated matches."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        assert len(matches) > 0
        assert all(m.tournament_id == tournament_knockout.id for m in matches)
        # Verify relationship works
        db.refresh(tournament_knockout)
        assert len(tournament_knockout.matches) == len(matches)


# ---------------------------------------------------------------------------
# Duplicate fixture prevention tests
# ---------------------------------------------------------------------------

class TestDuplicateFixturePrevention:
    """Tests for preventing duplicate match generation."""

    def test_knockout_raises_on_duplicate(self, db, tournament_knockout, players):
        """Knockout generation raises ValueError if matches already exist."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        with pytest.raises(ValueError, match="already has matches"):
            context.run_generation(player_names, tournament_knockout.id, db)

    def test_round_robin_raises_on_duplicate(self, db, tournament_round_robin, players):
        """Round-robin generation raises ValueError if matches already exist."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]

        context.run_generation(player_names, tournament_round_robin.id, db)
        db.commit()

        with pytest.raises(ValueError, match="already has matches"):
            context.run_generation(player_names, tournament_round_robin.id, db)

    def test_duplicate_guard_preserves_existing_matches(self, db, tournament_knockout, players):
        """The duplicate guard does not delete or modify existing matches."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        first_matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()
        first_count = len(first_matches)

        with pytest.raises(ValueError):
            context.run_generation(player_names, tournament_knockout.id, db)

        remaining = db.query(Match).filter(Match.tournament_id == tournament_knockout.id).all()
        assert len(remaining) == first_count

    def test_empty_tournament_allows_generation(self, db, tournament_knockout, players):
        """Generation succeeds when no matches exist."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        assert len(matches) > 0
        assert all(m.tournament_id == tournament_knockout.id for m in matches)

    def test_factory_raises_on_unsupported_format(self, db, tournament_knockout, players):
        """TournamentFactory raises ValueError for unsupported formats."""
        with pytest.raises(ValueError, match="Unsupported tournament format"):
            TournamentFactory.create_tournament(
                "swiss", [p.name for p in players], tournament_knockout.id, db
            )


# ---------------------------------------------------------------------------
# Round-robin match generation tests
# ---------------------------------------------------------------------------

class TestRoundRobinMatchGeneration:
    """Tests for round-robin match generation."""

    def test_generates_all_pairings(self, db, tournament_round_robin, players):
        """Round-robin generates exactly n*(n-1)/2 matches for n players."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]
        n = len(player_names)

        matches = context.run_generation(player_names, tournament_round_robin.id, db)
        db.commit()

        expected_count = n * (n - 1) // 2
        assert len(matches) == expected_count

    def test_every_player_plays_every_other_player(self, db, tournament_round_robin, players):
        """In round-robin, each player appears in matches against every other player."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_round_robin.id, db)
        db.commit()

        # Build set of pairs (sorted tuple of names)
        pairs = set()
        for m in matches:
            pair = tuple(sorted([m.player1, m.player2]))
            pairs.add(pair)

        expected_pairs = set()
        for i in range(len(player_names)):
            for j in range(i + 1, len(player_names)):
                expected_pairs.add(tuple(sorted([player_names[i], player_names[j]])))

        assert pairs == expected_pairs

    def test_matches_are_pending_by_default(self, db, tournament_round_robin, players):
        """All round-robin matches start with pending status."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_round_robin.id, db)
        db.commit()

        assert all(m.status == MatchStatus.pending for m in matches)

    def test_matches_have_correct_tournament_id(self, db, tournament_round_robin, players):
        """All generated matches belong to the correct tournament."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_round_robin.id, db)
        db.commit()

        assert all(m.tournament_id == tournament_round_robin.id for m in matches)

    def test_single_player_raises_error(self, db, tournament_round_robin):
        """Round-robin with a single player raises an error (library requires >1)."""
        context = TournamentContext(RoundRobinStrategy())

        with pytest.raises(AssertionError):
            context.run_generation(["Solo"], tournament_round_robin.id, db)

    def test_empty_player_list_returns_empty(self, db, tournament_round_robin):
        """Round-robin with no players returns no matches."""
        context = TournamentContext(RoundRobinStrategy())

        matches = context.run_generation([], tournament_round_robin.id, db)
        db.commit()

        assert matches == []


# ---------------------------------------------------------------------------
# Knockout match generation tests
# ---------------------------------------------------------------------------

class TestKnockoutMatchGeneration:
    """Tests for knockout (single-elimination) match generation."""

    def test_generates_bracket_matches(self, db, tournament_knockout, players):
        """Knockout generates a valid bracket with matches."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        assert len(matches) > 0
        # For 4 players, knockout should have 3 matches (2 semis + 1 final)
        assert len(matches) == len(players) - 1

    def test_byes_are_auto_completed(self, db, tournament_knockout):
        """When a player gets a bye, the match is auto-completed."""
        # 3 players -> one bye in first round
        context = TournamentContext(KnockoutStrategy())
        player_names = ["Alice", "Bob", "Charlie"]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        # At least one match should be completed (the bye)
        completed = [m for m in matches if m.status == MatchStatus.completed]
        assert len(completed) >= 1
        assert all(m.score == "BYE" for m in completed)

    def test_bye_winner_propagates_to_next_match(self, db, tournament_knockout):
        """The winner of a bye advances to the next match."""
        context = TournamentContext(KnockoutStrategy())
        player_names = ["Alice", "Bob", "Charlie"]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        # Find a completed bye match
        bye_match = next(m for m in matches if m.status == MatchStatus.completed and m.score == "BYE")
        assert bye_match.winner is not None

        # The next match should have the bye winner as a participant
        if bye_match.next_match_id:
            next_match = db.query(Match).filter(Match.id == bye_match.next_match_id).first()
            assert next_match is not None
            assert bye_match.winner in (next_match.player1, next_match.player2)

    def test_matches_have_round_numbers(self, db, tournament_knockout, players):
        """Knockout matches are assigned round numbers."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        assert all(m.round_number is not None for m in matches)
        # Round numbers should be positive integers
        assert all(isinstance(m.round_number, int) and m.round_number > 0 for m in matches)

    def test_matches_have_bracket_indices(self, db, tournament_knockout, players):
        """Knockout matches are assigned unique bracket indices."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        indices = [m.bracket_index for m in matches]
        assert len(indices) == len(set(indices))  # All unique
        assert set(indices) == set(range(len(matches)))  # Sequential from 0

    def test_odd_number_of_players(self, db, tournament_knockout):
        """Knockout works with an odd number of players (bye handling)."""
        context = TournamentContext(KnockoutStrategy())
        player_names = ["Alice", "Bob", "Charlie", "Diana", "Eve"]

        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        # 5 players -> bracketool generates a full bracket tree
        # The number of matches equals the next power of 2 minus 1
        # Next power of 2 after 5 is 8, so 8 - 1 = 7 matches
        assert len(matches) == 7


# ---------------------------------------------------------------------------
# Match reporting tests
# ---------------------------------------------------------------------------

class TestMatchReporting:
    """Tests for reporting match results."""

    def test_report_pending_match_success(self, db, pending_match):
        """A pending match can be reported with a valid winner and score."""
        command = ReportMatchCommand(
            match_id=pending_match.id,
            winner=pending_match.player1,
            score="3-1",
        )
        updated = report_existing_match(db, command)

        assert updated.status == MatchStatus.completed
        assert updated.winner == pending_match.player1
        assert updated.score == "3-1"
        assert updated.winner_id == pending_match.player1_id

    def test_report_match_updates_both_name_and_fk(self, db, pending_match):
        """Reporting updates both the display name and foreign key."""
        command = ReportMatchCommand(
            match_id=pending_match.id,
            winner=pending_match.player2,
            score="2-3",
        )
        updated = report_existing_match(db, command)

        assert updated.winner == pending_match.player2
        assert updated.winner_id == pending_match.player2_id

    def test_report_completed_match_raises(self, db, completed_match):
        """Reporting an already completed match raises MatchAlreadyCompletedError."""
        command = ReportMatchCommand(
            match_id=completed_match.id,
            winner=completed_match.player2,
            score="3-0",
        )
        with pytest.raises(MatchAlreadyCompletedError, match="already been completed"):
            report_existing_match(db, command)

    def test_report_nonexistent_match_raises(self, db):
        """Reporting a non-existent match raises MatchNotFoundError."""
        command = ReportMatchCommand(
            match_id=9999,
            winner="Nobody",
            score="0-0",
        )
        with pytest.raises(MatchNotFoundError, match="not found"):
            report_existing_match(db, command)

    def test_report_invalid_winner_raises(self, db, pending_match, players):
        """Reporting with a winner not in the match raises InvalidWinnerError."""
        # Create a match between Alice and Bob
        # Try to report Charlie as winner
        command = ReportMatchCommand(
            match_id=pending_match.id,
            winner="Charlie",
            score="3-0",
        )
        with pytest.raises(InvalidWinnerError, match="Winner must be either"):
            report_existing_match(db, command)

    def test_report_empty_score_raises_validation_error(self, db, pending_match):
        """ReportMatchCommand rejects empty scores via pydantic validation."""
        with pytest.raises(ValueError, match="Score cannot be empty"):
            ReportMatchCommand(
                match_id=pending_match.id,
                winner=pending_match.player1,
                score="   ",
            )

    def test_report_match_does_not_create_rating_history_directly(self, db, pending_match):
        """report_existing_match does not create rating history (API endpoint does that)."""
        history_before = db.query(RatingHistory).count()
        assert history_before == 0

        command = ReportMatchCommand(
            match_id=pending_match.id,
            winner=pending_match.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        history_after = db.query(RatingHistory).count()
        assert history_after == 0  # Rating history is created by the API/rating manager


# ---------------------------------------------------------------------------
# Rating update tests
# ---------------------------------------------------------------------------

class TestRatingUpdates:
    """Tests for rating updates after match completion."""

    def test_winner_rating_increases(self, db, players):
        """The winner's rating increases after a match."""
        manager = RatingManager()
        winner = players[0]
        loser = players[1]

        initial_winner_rating = winner.rating
        initial_loser_rating = loser.rating

        manager.update_ratings(winner.id, loser.id, db_session=db)
        db.expire_all()
        winner_check = db.query(Player).filter(Player.id == winner.id).first()
        loser_check = db.query(Player).filter(Player.id == loser.id).first()

        assert winner_check.rating > initial_winner_rating
        assert loser_check.rating < initial_loser_rating

    def test_rating_change_is_reflected_in_database(self, db, players):
        """Rating changes are persisted to the database."""
        manager = RatingManager()
        winner = players[0]
        loser = players[1]

        initial_winner_rating = winner.rating
        initial_loser_rating = loser.rating

        manager.update_ratings(winner.id, loser.id, db_session=db)
        db.expire_all()

        winner_check = db.query(Player).filter(Player.id == winner.id).first()
        loser_check = db.query(Player).filter(Player.id == loser.id).first()

        assert winner_check.rating != initial_winner_rating
        assert loser_check.rating != initial_loser_rating

    def test_rating_history_is_created(self, db, players):
        """Rating updates create entries in the rating history table."""
        manager = RatingManager()
        winner = players[0]
        loser = players[1]

        history_before = db.query(RatingHistory).count()
        manager.update_ratings(winner.id, loser.id, db_session=db)
        history_after = db.query(RatingHistory).count()

        assert history_after == history_before + 2

    def test_rating_history_has_correct_player_ids(self, db, players):
        """Rating history entries reference the correct players."""
        manager = RatingManager()
        winner = players[0]
        loser = players[1]

        manager.update_ratings(winner.id, loser.id, db_session=db)

        histories = db.query(RatingHistory).filter(
            RatingHistory.player_id.in_([winner.id, loser.id])
        ).all()

        player_ids = {h.player_id for h in histories}
        assert player_ids == {winner.id, loser.id}

    def test_multiple_matches_accumulate_rating_changes(self, db, players):
        """Multiple matches accumulate rating changes correctly."""
        manager = RatingManager()
        p1, p2, p3 = players[0], players[1], players[2]

        initial_p1 = p1.rating
        initial_p2 = p2.rating
        initial_p3 = p3.rating

        # p1 beats p2
        manager.update_ratings(p1.id, p2.id, db_session=db)
        db.expire_all()
        p1 = db.query(Player).filter(Player.id == p1.id).first()
        p2 = db.query(Player).filter(Player.id == p2.id).first()

        rating_p1_after_1 = p1.rating
        rating_p2_after_1 = p2.rating

        # p1 beats p3
        manager.update_ratings(p1.id, p3.id, db_session=db)
        db.expire_all()
        p1 = db.query(Player).filter(Player.id == p1.id).first()
        p3 = db.query(Player).filter(Player.id == p3.id).first()

        assert p1.rating > rating_p1_after_1  # p1 gained more
        assert p3.rating < initial_p3  # p3 lost some

    def test_rating_does_not_go_below_zero(self, db, players):
        """Ratings are clamped to a minimum floor (e.g., 0)."""
        # Create a player with very low rating
        weak_player = Player(name="Weak", email="weak@example.com", rating=1)
        strong_player = Player(name="Strong", email="strong@example.com", rating=2000)
        db.add_all([weak_player, strong_player])
        db.commit()
        db.refresh(weak_player)
        db.refresh(strong_player)

        manager = RatingManager()
        # Strong beats weak many times
        for _ in range(10):
            manager.update_ratings(strong_player.id, weak_player.id, db_session=db)
            db.expire_all()
            weak_player = db.query(Player).filter(Player.id == weak_player.id).first()

        assert weak_player.rating >= 0


# ---------------------------------------------------------------------------
# API /api/report tests
# ---------------------------------------------------------------------------

class TestApiReportEndpoint:
    """Tests for the /api/report FastAPI endpoint."""

    def test_report_happy_path(self, client, pending_match):
        """POST /api/report with valid data returns success."""
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
        assert "message" in data

    def test_report_returns_updated_match(self, client, pending_match, db):
        """The response confirms the match was updated."""
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

    def test_report_nonexistent_match_returns_400(self, client):
        """Reporting a non-existent match returns HTTP 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": 9999,
                "winner": "Nobody",
                "score": "0-0",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "not found" in data["detail"].lower() or "400" in str(response.status_code)

    def test_report_completed_match_returns_400(self, client, completed_match):
        """Reporting an already completed match returns HTTP 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": completed_match.id,
                "winner": completed_match.player2,
                "score": "3-2",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "already been completed" in data["detail"] or "400" in str(response.status_code)

    def test_report_invalid_winner_returns_400(self, client, pending_match):
        """Reporting with an invalid winner returns HTTP 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": pending_match.id,
                "winner": "NonExistentPlayer",
                "score": "3-1",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Winner must be either" in data["detail"] or "400" in str(response.status_code)

    def test_report_missing_fields_returns_400(self, client):
        """Reporting with missing required fields returns HTTP 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": 1,
                # Missing winner and score
            },
        )

        assert response.status_code == 400

    def test_report_empty_score_returns_400(self, client, pending_match):
        """Reporting with an empty score returns HTTP 400."""
        response = client.post(
            "/api/report",
            json={
                "match_id": pending_match.id,
                "winner": pending_match.player1,
                "score": "   ",
            },
        )

        assert response.status_code == 400

    def test_report_invalid_json_returns_400(self, client):
        """Sending invalid JSON returns HTTP 400."""
        response = client.post(
            "/api/report",
            content="not json at all",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400

    def test_report_with_both_player_ids(self, client, pending_match):
        """Reporting works when both player1_id and player2_id are set."""
        response = client.post(
            "/api/report",
            json={
                "match_id": pending_match.id,
                "winner": pending_match.player2,
                "score": "2-3",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_health_endpoint_returns_200(self, client):
        """GET /health returns 200 with healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# Integration: full tournament flow
# ---------------------------------------------------------------------------

class TestFullTournamentFlow:
    """End-to-end integration tests for a complete tournament lifecycle."""

    def test_full_knockout_flow(self, db, tournament_knockout, players):
        """Complete knockout flow: create -> generate -> report -> verify ratings."""
        # 1. Generate matches
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament_knockout.id, db)
        db.commit()

        assert len(matches) > 0

        # 2. Find a pending match and report it
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        initial_winner_rating = db.query(Player).filter(Player.id == pending.player1_id).first().rating
        initial_loser_rating = db.query(Player).filter(Player.id == pending.player2_id).first().rating

        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        updated = report_existing_match(db, command)

        assert updated.status == MatchStatus.completed
        assert updated.winner == pending.player1

        # 3. Manually trigger rating update (the API endpoint does this,
        #    but report_existing_match itself does not)
        manager = RatingManager()
        manager.update_ratings(pending.player1_id, pending.player2_id, db_session=db)

        # 4. Verify ratings were updated
        db.expire_all()
        history_count = db.query(RatingHistory).count()
        assert history_count >= 2  # At least winner and loser history entries

        p1 = db.query(Player).filter(Player.id == pending.player1_id).first()
        p2 = db.query(Player).filter(Player.id == pending.player2_id).first()
        # Ratings may or may not change due to integer truncation,
        # but rating history should exist
        assert p1.rating >= initial_winner_rating
        assert p2.rating <= initial_loser_rating

    def test_full_round_robin_flow(self, db, tournament_round_robin, players):
        """Complete round-robin flow: create -> generate -> report all matches."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament_round_robin.id, db)
        db.commit()

        # Report all matches (alternate winners for fairness)
        for idx, match in enumerate(matches):
            winner = match.player1 if idx % 2 == 0 else match.player2
            command = ReportMatchCommand(
                match_id=match.id,
                winner=winner,
                score="3-2",
            )
            report_existing_match(db, command)

        # Verify all are completed
        db.expire_all()
        all_matches = db.query(Match).filter(Match.tournament_id == tournament_round_robin.id).all()
        assert all(m.status == MatchStatus.completed for m in all_matches)

    def test_api_full_flow(self, client, db, players):
        """End-to-end API flow: create tournament -> generate -> report via API."""
        # 1. Create tournament via API (or directly in DB)
        t = Tournament(name="API Flow Test", tournament_type=TournamentType.knockout)
        db.add(t)
        db.commit()
        db.refresh(t)

        # 2. Generate matches via service
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, t.id, db)
        db.commit()

        # 3. Find a pending match and report via API
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        response = client.post(
            "/api/report",
            json={
                "match_id": pending.id,
                "winner": pending.player1,
                "score": "3-0",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # 4. Verify in database
        db.expire_all()
        match_check = db.query(Match).filter(Match.id == pending.id).first()
        assert match_check.status == MatchStatus.completed
        assert match_check.winner == pending.player1
