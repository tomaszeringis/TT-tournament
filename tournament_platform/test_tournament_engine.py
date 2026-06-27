import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, Player, Tournament, Match, MatchStatus, TournamentType
from tournament_platform.services.tournament_engine import (
    TournamentContext,
    KnockoutStrategy,
    RoundRobinStrategy,
)


@pytest.fixture
def db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def tournament(db):
    """Create a tournament in the test database."""
    t = Tournament(name="Test Tournament", tournament_type=TournamentType.knockout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def players(db):
    """Create sample players in the test database."""
    player_names = ["Alice", "Bob", "Charlie", "Diana"]
    players = [Player(name=name, email=f"{name.lower()}@example.com", rating=1200) for name in player_names]
    db.add_all(players)
    db.commit()
    for p in players:
        db.refresh(p)
    return players


class TestDuplicateMatchGuard:
    """Tests for the duplicate match generation guard in TournamentContext."""

    def test_knockout_generation_raises_on_duplicate(self, db, tournament, players):
        """Knockout generation should raise ValueError if matches already exist."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        # First generation should succeed
        context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Second generation should raise
        with pytest.raises(ValueError, match="already has matches"):
            context.run_generation(player_names, tournament.id, db)

    def test_round_robin_generation_raises_on_duplicate(self, db, tournament, players):
        """Round-robin generation should raise ValueError if matches already exist."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]

        # First generation should succeed
        context.run_generation(player_names, tournament.id, db)
        db.commit()

        # Second generation should raise
        with pytest.raises(ValueError, match="already has matches"):
            context.run_generation(player_names, tournament.id, db)

    def test_knockout_generation_succeeds_when_empty(self, db, tournament, players):
        """Knockout generation should succeed when no matches exist."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        assert len(matches) > 0
        assert all(m.tournament_id == tournament.id for m in matches)

    def test_round_robin_generation_succeeds_when_empty(self, db, tournament, players):
        """Round-robin generation should succeed when no matches exist."""
        context = TournamentContext(RoundRobinStrategy())
        player_names = [p.name for p in players]

        matches = context.run_generation(player_names, tournament.id, db)
        db.commit()

        assert len(matches) > 0
        assert all(m.tournament_id == tournament.id for m in matches)

    def test_guard_does_not_delete_existing_matches(self, db, tournament, players):
        """The guard should not delete or modify existing matches on duplicate attempt."""
        context = TournamentContext(KnockoutStrategy())
        player_names = [p.name for p in players]

        # First generation
        first_matches = context.run_generation(player_names, tournament.id, db)
        db.commit()
        first_count = len(first_matches)

        # Attempt duplicate generation
        with pytest.raises(ValueError):
            context.run_generation(player_names, tournament.id, db)

        # Verify original matches are untouched
        remaining = db.query(Match).filter(Match.tournament_id == tournament.id).all()
        assert len(remaining) == first_count
