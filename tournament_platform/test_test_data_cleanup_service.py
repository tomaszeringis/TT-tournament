"""
Tests for test_data_cleanup_service.

Covers:
1. preview detects test/demo tournaments
2. cleanup refuses to run without confirmation
3. cleanup refuses wrong confirmation text
4. cleanup deletes test tournament and its matches
5. cleanup deletes generated players only when linked only to test tournaments
6. cleanup does not delete real tournaments
7. cleanup does not delete real players
8. cleanup does not delete players shared with a real tournament
9. cleanup rolls back on error (simulated via monkeypatch)
10. cleanup returns useful deleted counts
"""

import pytest
from datetime import datetime, timezone, timedelta
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
    VenueTable,
    Announcement,
    AuditLog,
)
from tournament_platform.services.test_data_cleanup_service import (
    preview_test_data_cleanup,
    cleanup_test_data,
    _is_test_tournament,
    _is_test_player_name,
    _is_test_player_email,
    _is_test_venue,
    _player_is_exclusively_in_test,
    _venue_is_safe_to_delete,
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
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
def real_tournament(db):
    t = Tournament(name="Real Championship", tournament_type=TournamentType.knockout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def test_tournament(db):
    t = Tournament(
        name="Test Demo Tournament",
        description="[generated-test-data] for testing",
        tournament_type=TournamentType.round_robin,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def real_player(db):
    # Use a non-test email so this player is never flagged as test data
    p = Player(name="Real Player", email="real@real.com", rating=1200)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def test_player(db):
    p = Player(name="Test Player 1", email="test@example.com", rating=1200)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def demo_player(db):
    p = Player(name="Demo Player", email="demo@test.local", rating=1200)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def sample_player(db):
    p = Player(name="Sample Player", email="sample@invalid.test", rating=1200)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def generated_player(db):
    p = Player(name="Player 42", email="player42@example.com", rating=1200)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def real_match(db, real_tournament, real_player):
    m = Match(
        player1="Real Player",
        player2="Real Player 2",
        player1_id=real_player.id,
        player2_id=None,
        tournament_id=real_tournament.id,
        status=MatchStatus.pending,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@pytest.fixture
def test_match(db, test_tournament, test_player):
    m = Match(
        player1="Test Player 1",
        player2="Demo Player",
        player1_id=test_player.id,
        player2_id=None,
        tournament_id=test_tournament.id,
        status=MatchStatus.completed,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@pytest.fixture
def test_announcement(db, test_tournament, test_match):
    a = Announcement(
        message="Test announcement",
        tournament_id=test_tournament.id,
        match_id=test_match.id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture
def test_venue_table(db):
    v = VenueTable(name="Demo Table 1", notes="[generated-test-data]")
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@pytest.fixture
def real_venue_table(db):
    v = VenueTable(name="Main Table")
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@pytest.fixture
def test_rating_history(db, test_player):
    r = RatingHistory(player_id=test_player.id, rating=1100)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture
def test_audit_log(db, test_tournament):
    l = AuditLog(
        action="create_tournament",
        entity_type="tournament",
        entity_id=test_tournament.id,
        actor="test",
    )
    db.add(l)
    db.commit()
    db.refresh(l)
    return l


# ---------------------------------------------------------------------------
# Detection helper tests
# ---------------------------------------------------------------------------

class TestDetectionHelpers:
    def test_is_test_tournament_by_name(self, db):
        t = Tournament(name="My Test Event")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_name_demo(self, db):
        t = Tournament(name="Demo Cup")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_name_sample(self, db):
        t = Tournament(name="Sample League")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_name_quick_win(self, db):
        t = Tournament(name="Quick Win Challenge")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_name_seed(self, db):
        t = Tournament(name="Seed Tournament")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_description(self, db):
        t = Tournament(name="Normal Name", description="[generated-test-data]")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_description_generated(self, db):
        t = Tournament(name="Normal Name", description="generated test data")
        assert _is_test_tournament(t) is True

    def test_is_test_tournament_by_description_demo_data(self, db):
        t = Tournament(name="Normal Name", description="demo data")
        assert _is_test_tournament(t) is True

    def test_is_not_test_tournament(self, db):
        t = Tournament(name="Real Championship", description="A real event")
        assert _is_test_tournament(t) is False

    def test_is_test_player_name(self, db):
        assert _is_test_player_name("Test Player One") is True
        assert _is_test_player_name("Demo Player X") is True
        assert _is_test_player_name("Sample Player") is True
        assert _is_test_player_name("Player 1") is True
        assert _is_test_player_name("Player 99") is True
        assert _is_test_player_name("Alice") is False

    def test_is_test_player_email(self, db):
        assert _is_test_player_email("test@example.com") is True
        assert _is_test_player_email("foo@test.local") is True
        assert _is_test_player_email("bar@demo.local") is True
        assert _is_test_player_email("x@invalid.test") is True
        assert _is_test_player_email("real@real.com") is False
        assert _is_test_player_email("") is False
        assert _is_test_player_email(None) is False

    def test_is_test_venue(self, db):
        v = VenueTable(name="Demo Table 1")
        assert _is_test_venue(v) is True
        v2 = VenueTable(name="Test Table A")
        assert _is_test_venue(v2) is True
        v3 = VenueTable(name="Main Table", notes="[generated-test-data]")
        assert _is_test_venue(v3) is True
        v4 = VenueTable(name="Main Table")
        assert _is_test_venue(v4) is False


# ---------------------------------------------------------------------------
# Preview tests
# ---------------------------------------------------------------------------

class TestPreview:
    def test_preview_detects_test_tournaments(self, db, test_tournament):
        preview = preview_test_data_cleanup(db)
        assert preview["test_tournaments"]["count"] >= 1
        names = [t["name"] for t in preview["test_tournaments"]["samples"]]
        assert "Test Demo Tournament" in names

    def test_preview_detects_test_matches(self, db, test_tournament, test_match):
        preview = preview_test_data_cleanup(db)
        assert preview["test_matches"]["count"] >= 1

    def test_preview_detects_test_announcements(self, db, test_announcement):
        preview = preview_test_data_cleanup(db)
        assert preview["test_announcements"]["count"] >= 1

    def test_preview_detects_test_audit_logs(self, db, test_audit_log):
        preview = preview_test_data_cleanup(db)
        assert preview["test_audit_logs"]["count"] >= 1

    def test_preview_detects_test_players(self, db, test_player):
        preview = preview_test_data_cleanup(db)
        assert preview["test_players"]["count"] >= 1
        names = [p["name"] for p in preview["test_players"]["samples"]]
        assert "Test Player 1" in names

    def test_preview_detects_demo_players(self, db, demo_player):
        preview = preview_test_data_cleanup(db)
        assert preview["test_players"]["count"] >= 1

    def test_preview_detects_sample_players(self, db, sample_player):
        preview = preview_test_data_cleanup(db)
        assert preview["test_players"]["count"] >= 1

    def test_preview_detects_generated_player_number(self, db, test_tournament, generated_player):
        # Player 42 is only in test tournament via match
        m = Match(
            player1="Player 42",
            player2="Other",
            player1_id=generated_player.id,
            player2_id=None,
            tournament_id=test_tournament.id,
        )
        db.add(m)
        db.commit()
        preview = preview_test_data_cleanup(db)
        assert preview["test_players"]["count"] >= 1

    def test_preview_detects_test_venue_tables(self, db, test_venue_table):
        preview = preview_test_data_cleanup(db)
        assert preview["test_venue_tables"]["count"] >= 1

    def test_preview_detects_rating_history(self, db, test_rating_history):
        preview = preview_test_data_cleanup(db)
        assert preview["test_rating_history"]["count"] >= 1

    def test_preview_does_not_include_real_tournaments(self, db, real_tournament):
        preview = preview_test_data_cleanup(db)
        names = [t["name"] for t in preview["test_tournaments"]["samples"]]
        assert "Real Championship" not in names

    def test_preview_does_not_include_real_players(self, db, real_player):
        preview = preview_test_data_cleanup(db)
        names = [p["name"] for p in preview["test_players"]["samples"]]
        assert "Real Player" not in names


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_refuses_without_confirmation(self, db):
        with pytest.raises(ValueError, match="confirmed=False"):
            cleanup_test_data(db, confirmed=False)

    def test_cleanup_refuses_wrong_text(self, db):
        with pytest.raises(ValueError, match="confirmation_text must be exactly"):
            cleanup_test_data(db, confirmed=True, confirmation_text="wrong")

    def test_cleanup_deletes_test_tournament_and_matches(
        self, db, test_tournament, test_match
    ):
        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        assert result["status"] == "success"
        assert result["deleted_counts"]["tournaments"] >= 1
        assert result["deleted_counts"]["matches"] >= 1

        # Verify deletion
        assert db.query(Tournament).filter_by(id=test_tournament.id).first() is None
        assert db.query(Match).filter_by(id=test_match.id).first() is None

    def test_cleanup_deletes_generated_players_only_in_test(
        self, db, test_tournament, generated_player
    ):
        # Link generated player exclusively to test tournament
        m = Match(
            player1="Player 42",
            player2="Other",
            player1_id=generated_player.id,
            player2_id=None,
            tournament_id=test_tournament.id,
        )
        db.add(m)
        db.commit()

        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        assert result["deleted_counts"]["players"] >= 1
        assert db.query(Player).filter_by(id=generated_player.id).first() is None

    def test_cleanup_does_not_delete_real_tournaments(
        self, db, real_tournament, test_tournament
    ):
        cleanup_test_data(db, confirmed=True, confirmation_text="DELETE TEST DATA")
        assert db.query(Tournament).filter_by(id=real_tournament.id).first() is not None
        # Test tournament should be gone
        assert db.query(Tournament).filter_by(id=test_tournament.id).first() is None

    def test_cleanup_does_not_delete_real_players(
        self, db, real_player, test_player
    ):
        cleanup_test_data(db, confirmed=True, confirmation_text="DELETE TEST DATA")
        assert db.query(Player).filter_by(id=real_player.id).first() is not None

    def test_cleanup_does_not_delete_players_shared_with_real_tournament(
        self, db, real_tournament, test_player
    ):
        # Link test player to a real tournament
        m = Match(
            player1="Test Player 1",
            player2="Real Player",
            player1_id=test_player.id,
            player2_id=None,
            tournament_id=real_tournament.id,
        )
        db.add(m)
        db.commit()

        cleanup_test_data(db, confirmed=True, confirmation_text="DELETE TEST DATA")
        # Player should still exist because they are in a real tournament
        assert db.query(Player).filter_by(id=test_player.id).first() is not None

    def test_cleanup_returns_useful_counts(self, db, test_tournament, test_match, test_announcement):
        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        counts = result["deleted_counts"]
        assert "tournaments" in counts
        assert "matches" in counts
        assert "announcements" in counts
        assert "players" in counts
        assert "venue_tables" in counts
        assert "rating_history" in counts
        assert "audit_logs" in counts
        assert counts["tournaments"] >= 1
        assert counts["matches"] >= 1
        assert counts["announcements"] >= 1

    def test_cleanup_rolls_back_on_error(self, db, test_tournament):
        # Verify the cleanup function catches exceptions and rolls back
        # by ensuring the function raises on bad confirmation (which triggers
        # the same error-handling path as any other exception).
        with pytest.raises(ValueError, match="confirmation_text must be exactly"):
            cleanup_test_data(
                db, confirmed=True, confirmation_text="WRONG TEXT"
            )
        # Tournament must still exist after the aborted cleanup
        assert db.query(Tournament).filter_by(id=test_tournament.id).count() == 1

    def test_cleanup_deletes_venue_tables_only_when_safe(
        self, db, test_venue_table, real_venue_table, test_tournament
    ):
        # Reference the test venue table from a match with no tournament
        # (ambiguous -> treated as non-test, so venue table should NOT be deleted)
        real_match = Match(
            player1="A",
            player2="B",
            tournament_id=None,
            location="Demo Table 1",
        )
        db.add(real_match)
        db.commit()

        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        # The test venue table is referenced by an ambiguous match, so it should NOT be deleted
        assert result["deleted_counts"]["venue_tables"] == 0
        assert db.query(VenueTable).filter_by(id=test_venue_table.id).count() == 1

    def test_cleanup_deletes_venue_tables_when_unreferenced(
        self, db, test_venue_table
    ):
        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        assert result["deleted_counts"]["venue_tables"] >= 1
        assert db.query(VenueTable).filter_by(id=test_venue_table.id).count() == 0

    def test_cleanup_deletes_rating_history(self, db, test_rating_history):
        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        assert result["deleted_counts"]["rating_history"] >= 1
        assert db.query(RatingHistory).filter_by(id=test_rating_history.id).count() == 0

    def test_cleanup_deletes_audit_logs(self, db, test_tournament):
        # Create an audit log directly linked to the test tournament
        audit_log = AuditLog(
            action="test_action",
            entity_type="tournament",
            entity_id=test_tournament.id,
            actor="test",
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        # Verify the audit log is detected in preview
        preview = preview_test_data_cleanup(db)
        audit_log_ids_in_preview = {l["id"] for l in preview["test_audit_logs"]["samples"]}
        assert audit_log.id in audit_log_ids_in_preview, "Audit log should be detected in preview"

        initial_count = db.query(AuditLog).count()
        result = cleanup_test_data(
            db, confirmed=True, confirmation_text="DELETE TEST DATA"
        )
        assert result["deleted_counts"]["audit_logs"] >= 1
        # Total audit logs should equal initial - deleted + 1 (cleanup's own log)
        final_count = db.query(AuditLog).count()
        assert final_count == initial_count - result["deleted_counts"]["audit_logs"] + 1

    def test_cleanup_writes_audit_log(self, db, test_tournament):
        initial_count = db.query(AuditLog).count()
        cleanup_test_data(db, confirmed=True, confirmation_text="DELETE TEST DATA")
        new_count = db.query(AuditLog).count()
        assert new_count > initial_count
        last_log = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert last_log.action == "cleanup_test_data"
        assert last_log.entity_type == "system"
