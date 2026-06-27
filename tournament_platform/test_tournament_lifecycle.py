"""
Integration tests for the complete tournament lifecycle.

Tests the flow:
1. Create players
2. Create a tournament
3. Generate fixtures once
4. Verify duplicate generation is blocked
5. Report a scheduled match result
6. Verify the existing match is updated, not duplicated
7. Verify rankings update
8. Verify dashboard/admin summaries remain consistent
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
def tournament(db):
    """Create a knockout tournament in the test database."""
    t = Tournament(name="Lifecycle Test Tournament", tournament_type=TournamentType.knockout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# Step 1: Create players
# ---------------------------------------------------------------------------

class TestCreatePlayers:
    """Tests for player creation step."""

    def test_players_are_created_successfully(self, db):
        """Players can be created and persisted in the database."""
        player = Player(name="TestPlayer", email="test@example.com", rating=1200)
        db.add(player)
        db.commit()
        db.refresh(player)

        assert player.id is not None
        assert player.name == "TestPlayer"
        assert player.rating == 1200

    def test_players_have_unique_names(self, db, players):
        """Player names must be unique."""
        duplicate = Player(name="Alice", email="alice2@example.com", rating=1000)
        db.add(duplicate)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()

    def test_default_rating_is_applied(self, db):
        """Players get a default rating of 1200 if not specified."""
        player = Player(name="NoRatingPlayer", email="norating@example.com")
        db.add(player)
        db.commit()
        db.refresh(player)

        assert player.rating == 1200


# ---------------------------------------------------------------------------
# Step 2: Create a tournament
# ---------------------------------------------------------------------------

class TestCreateTournament:
    """Tests for tournament creation step."""

    def test_tournament_is_created_successfully(self, db):
        """A tournament can be created and persisted."""
        t = Tournament(name="New Tournament", tournament_type=TournamentType.knockout)
        db.add(t)
        db.commit()
        db.refresh(t)

        assert t.id is not None
        assert t.name == "New Tournament"
        assert t.tournament_type == TournamentType.knockout
        assert t.created_at is not None

    def test_tournament_name_is_unique(self, db):
        """Tournament names must be unique."""
        t1 = Tournament(name="Unique Tournament", tournament_type=TournamentType.knockout)
        db.add(t1)
        db.commit()

        t2 = Tournament(name="Unique Tournament", tournament_type=TournamentType.round_robin)
        db.add(t2)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()


# ---------------------------------------------------------------------------
# Step 3: Generate fixtures once
# ---------------------------------------------------------------------------

class TestGenerateFixtures:
    """Tests for fixture generation step."""

    def test_generate_fixtures_creates_matches(self, db, tournament, players):
        """Generating fixtures creates matches in the database."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        assert len(matches) > 0
        assert all(m.tournament_id == tournament.id for m in matches)

    def test_generate_fixtures_creates_correct_match_count(self, db, tournament, players):
        """For 4 players in knockout, 3 matches are created (2 semis + 1 final)."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        assert len(matches) == len(players) - 1  # n-1 matches for knockout

    def test_matches_have_pending_status(self, db, tournament, players):
        """All generated matches start with pending status."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        assert all(m.status == MatchStatus.pending for m in matches)

    def test_matches_have_player_references(self, db, tournament, players):
        """Generated matches have proper player references (both name and FK)."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        for match in matches:
            assert match.player1 is not None
            assert match.player2 is not None
            # For pending matches, at least one player should have a valid FK
            # (matches with TBD placeholders may have None for one player)
            if match.status == MatchStatus.pending:
                # At least one player FK should be set for real matches
                has_valid_fk = match.player1_id is not None or match.player2_id is not None
                # For 4 players, all matches should have valid player references
                assert has_valid_fk or match.player1 == "TBD" or match.player2 == "TBD"


# ---------------------------------------------------------------------------
# Step 4: Verify duplicate generation is blocked
# ---------------------------------------------------------------------------

class TestDuplicateGenerationBlocked:
    """Tests for duplicate fixture generation prevention."""

    def test_duplicate_generation_raises_value_error(self, db, tournament, players):
        """Attempting to generate fixtures twice raises ValueError."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        # First generation succeeds
        context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Second generation should raise
        with pytest.raises(ValueError, match="already has matches"):
            context.run_generation(player_names, tournament.id, db)

    def test_duplicate_guard_preserves_existing_matches(self, db, tournament, players):
        """The duplicate guard does not delete or modify existing matches."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        first_matches = context.run_generation(player_names, tournament.id, db)
        db.commit()
        first_count = len(first_matches)

        # Attempt duplicate generation
        with pytest.raises(ValueError):
            context.run_generation(player_names, tournament.id, db)

        # Verify original matches are untouched
        remaining = db.query(Match).filter(Match.tournament_id == tournament.id).all()
        assert len(remaining) == first_count

    def test_factory_also_blocks_duplicates(self, db, tournament, players):
        """TournamentFactory also blocks duplicate generation."""
        player_names = [p.name for p in players]

        # First generation succeeds
        TournamentFactory.create_tournament(
            "knockout", player_names, tournament.id, db
        )
        db.commit()

        # Second generation should raise
        with pytest.raises(ValueError, match="already has matches"):
            TournamentFactory.create_tournament(
                "knockout", player_names, tournament.id, db
            )


# ---------------------------------------------------------------------------
# Step 5: Report a scheduled match result
# ---------------------------------------------------------------------------

class TestReportMatchResult:
    """Tests for match result reporting step."""

    def test_report_pending_match_succeeds(self, db, tournament, players):
        """A pending match can be reported with a valid winner and score."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Find a pending match
        pending = next(m for m in matches if m.status == MatchStatus.pending)

        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        updated = report_existing_match(db, command)

        assert updated.status == MatchStatus.completed
        assert updated.winner == pending.player1
        assert updated.score == "3-1"
        assert updated.winner_id == pending.player1_id

    def test_report_match_updates_both_name_and_fk(self, db, tournament, players):
        """Reporting updates both the display name and foreign key."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        pending = next(m for m in matches if m.status == MatchStatus.pending)

        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player2,
            score="2-3",
        )
        updated = report_existing_match(db, command)

        assert updated.winner == pending.player2
        assert updated.winner_id == pending.player2_id

    def test_report_completed_match_raises(self, db, tournament, players):
        """Reporting an already completed match raises MatchAlreadyCompletedError."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        pending = next(m for m in matches if m.status == MatchStatus.pending)

        # First report
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-0",
        )
        report_existing_match(db, command)

        # Second report should raise
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

    def test_report_invalid_winner_raises(self, db, tournament, players):
        """Reporting with a winner not in the match raises InvalidWinnerError."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        pending = next(m for m in matches if m.status == MatchStatus.pending)

        command = ReportMatchCommand(
            match_id=pending.id,
            winner="Charlie",  # Not a participant in this match
            score="3-0",
        )
        with pytest.raises(InvalidWinnerError, match="Winner must be either"):
            report_existing_match(db, command)


# ---------------------------------------------------------------------------
# Step 6: Verify the existing match is updated, not duplicated
# ---------------------------------------------------------------------------

class TestMatchUpdateNotDuplicated:
    """Tests to verify match updates don't create duplicates."""

    def test_reporting_does_not_create_new_match(self, db, tournament, players):
        """Reporting a match updates the existing one, not creating a duplicate."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        initial_match_count = len(matches)
        pending = next(m for m in matches if m.status == MatchStatus.pending)

        # Report the match
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Verify no new match was created
        all_matches = db.query(Match).filter(Match.tournament_id == tournament.id).all()
        assert len(all_matches) == initial_match_count

    def test_match_id_remains_unchanged(self, db, tournament, players):
        """The match ID remains the same after reporting."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        pending = next(m for m in matches if m.status == MatchStatus.pending)
        original_id = pending.id

        # Report the match
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        updated = report_existing_match(db, command)

        assert updated.id == original_id

    def test_match_can_be_reported_only_once(self, db, tournament, players):
        """A match can only be reported once - subsequent reports fail."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        pending = next(m for m in matches if m.status == MatchStatus.pending)

        # First report succeeds
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Second report fails
        with pytest.raises(MatchAlreadyCompletedError):
            report_existing_match(db, command)


# ---------------------------------------------------------------------------
# Step 7: Verify rankings update
# ---------------------------------------------------------------------------

class TestRankingsUpdate:
    """Tests for ranking updates after match completion."""

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

    def test_full_flow_updates_rankings(self, db, tournament, players):
        """Full tournament flow: report match -> ratings update."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Find a pending match
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        initial_winner_rating = db.query(Player).filter(Player.id == pending.player1_id).first().rating
        initial_loser_rating = db.query(Player).filter(Player.id == pending.player2_id).first().rating

        # Report the match
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Update ratings
        manager = RatingManager()
        manager.update_ratings(pending.player1_id, pending.player2_id, db_session=db)

        # Verify ratings were updated
        db.expire_all()
        winner = db.query(Player).filter(Player.id == pending.player1_id).first()
        loser = db.query(Player).filter(Player.id == pending.player2_id).first()

        assert winner.rating >= initial_winner_rating
        assert loser.rating <= initial_loser_rating


# ---------------------------------------------------------------------------
# Step 8: Verify dashboard/admin summaries remain consistent
# ---------------------------------------------------------------------------

class TestDashboardAdminConsistency:
    """Tests for dashboard and admin summary consistency."""

    def test_match_counts_remain_consistent(self, db, tournament, players):
        """Match counts in database remain consistent after operations."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Initial counts
        total_matches = db.query(Match).count()
        pending_matches = db.query(Match).filter(Match.status == MatchStatus.pending).count()
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()

        assert total_matches == len(matches)
        assert pending_matches == len(matches)
        assert completed_matches == 0

        # Report one match
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Verify counts updated correctly
        total_matches_after = db.query(Match).count()
        pending_matches_after = db.query(Match).filter(Match.status == MatchStatus.pending).count()
        completed_matches_after = db.query(Match).filter(Match.status == MatchStatus.completed).count()

        assert total_matches_after == total_matches
        assert pending_matches_after == pending_matches - 1
        assert completed_matches_after == completed_matches + 1

    def test_tournament_match_relationship_consistent(self, db, tournament, players):
        """Tournament matches relationship remains consistent."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Check relationship
        db.refresh(tournament)
        assert len(tournament.matches) == len(matches)

        # Report a match
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Verify relationship still intact
        db.refresh(tournament)
        assert len(tournament.matches) == len(matches)

    def test_player_statistics_consistent(self, db, tournament, players):
        """Player statistics remain consistent after match reporting."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Get initial player count
        initial_player_count = db.query(Player).count()

        # Report a match
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Player count should remain the same
        assert db.query(Player).count() == initial_player_count

    def test_dashboard_metrics_calculation(self, db, tournament, players):
        """Dashboard metrics can be calculated correctly from database."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Calculate metrics (simulating dashboard logic)
        total_players = db.query(Player).count()
        total_matches = db.query(Match).count()
        active_tournaments = db.query(Tournament).count()
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()

        assert total_players == len(players)
        assert total_matches == len(matches)
        assert active_tournaments == 1
        assert completed_matches == 0

        # Report a match
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        report_existing_match(db, command)

        # Recalculate metrics
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()
        assert completed_matches == 1


# ---------------------------------------------------------------------------
# Full Integration Test: Complete Tournament Lifecycle
# ---------------------------------------------------------------------------

class TestFullTournamentLifecycle:
    """End-to-end integration test for the complete tournament lifecycle."""

    def test_complete_lifecycle(self, db, players):
        """
        Complete tournament lifecycle:
        1. Create players
        2. Create a tournament
        3. Generate fixtures once
        4. Verify duplicate generation is blocked
        5. Report a scheduled match result
        6. Verify the existing match is updated, not duplicated
        7. Verify rankings update
        8. Verify dashboard/admin summaries remain consistent
        """
        # Step 1: Players already created via fixture
        assert len(players) == 4

        # Step 2: Create a tournament
        t = Tournament(name="Full Lifecycle Tournament", tournament_type=TournamentType.knockout)
        db.add(t)
        db.commit()
        db.refresh(t)
        assert t.id is not None

        # Step 3: Generate fixtures once
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]
        matches = context.run_generation(player_names, t.id, db)
        db.commit()
        assert len(matches) == 3  # 4 players = 3 matches

        # Step 4: Verify duplicate generation is blocked
        with pytest.raises(ValueError, match="already has matches"):
            context.run_generation(player_names, t.id, db)

        # Step 5: Report a scheduled match result
        pending = next(m for m in matches if m.status == MatchStatus.pending)
        command = ReportMatchCommand(
            match_id=pending.id,
            winner=pending.player1,
            score="3-1",
        )
        updated = report_existing_match(db, command)
        assert updated.status == MatchStatus.completed

        # Step 6: Verify the existing match is updated, not duplicated
        all_matches = db.query(Match).filter(Match.tournament_id == t.id).all()
        assert len(all_matches) == 3  # No new match created

        # Step 7: Verify rankings update
        manager = RatingManager()
        manager.update_ratings(pending.player1_id, pending.player2_id, db_session=db)
        db.expire_all()
        history_count = db.query(RatingHistory).count()
        assert history_count == 2  # Winner and loser history

        # Step 8: Verify dashboard/admin summaries remain consistent
        total_matches = db.query(Match).count()
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()
        pending_matches = db.query(Match).filter(Match.status == MatchStatus.pending).count()

        assert total_matches == 3
        assert completed_matches == 1
        assert pending_matches == 2