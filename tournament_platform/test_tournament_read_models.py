"""
Tests for tournament read model helpers.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import (
    Player, Match, Tournament, MatchStatus, VenueTable, Base
)
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_public_schedule,
    get_public_rankings,
    get_operator_queue,
    get_table_status,
    get_next_available_table,
    get_player_path,
)


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    """Create an in-memory database session for testing."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_data(db_session):
    """Create sample data for testing."""
    # Create players
    p1 = Player(name="Alice", rating=1200)
    p2 = Player(name="Bob", rating=1100)
    p3 = Player(name="Charlie", rating=1300)
    db_session.add_all([p1, p2, p3])
    db_session.commit()
    
    # Create tournament
    t = Tournament(name="Test Tournament", tournament_type="knockout")
    db_session.add(t)
    db_session.commit()
    
    # Create venue tables
    table1 = VenueTable(name="Table 1")
    table2 = VenueTable(name="Table 2")
    db_session.add_all([table1, table2])
    db_session.commit()
    
    # Create matches
    now = datetime.utcnow()
    
    m1 = Match(
        player1="Alice", player2="Bob",
        player1_id=p1.id, player2_id=p2.id,
        tournament_id=t.id,
        status=MatchStatus.completed,
        score="3-1",
        winner="Alice",
        winner_id=p1.id,
        scheduled_time=now - timedelta(hours=2),
        location="Table 1",
        round_number=1,
        bracket_index=0,
        call_status="completed"
    )
    
    m2 = Match(
        player1="Alice", player2="Charlie",
        player1_id=p1.id, player2_id=p3.id,
        tournament_id=t.id,
        status=MatchStatus.pending,
        scheduled_time=now + timedelta(hours=1),
        location="Table 2",
        round_number=2,
        bracket_index=0,
        call_status="queued"
    )
    
    m3 = Match(
        player1="Bob", player2="Charlie",
        player1_id=p2.id, player2_id=p3.id,
        tournament_id=t.id,
        status=MatchStatus.pending,
        scheduled_time=now,
        location="Table 1",
        round_number=1,
        bracket_index=1,
        call_status="active"
    )
    
    db_session.add_all([m1, m2, m3])
    db_session.commit()
    
    return {"players": [p1, p2, p3], "tournament": t, "tables": [table1, table2], "matches": [m1, m2, m3]}


class TestListTournaments:
    def test_list_tournaments_returns_all(self, db_session, sample_data):
        """Test that list_tournaments returns all tournaments."""
        result = list_tournaments(db_session)
        assert len(result) == 1
        assert result[0]["name"] == "Test Tournament"
        assert result[0]["tournament_type"] == "knockout"

    def test_list_tournaments_empty(self, db_session):
        """Test list_tournaments with no tournaments."""
        result = list_tournaments(db_session)
        assert result == []


class TestGetPublicSchedule:
    def test_get_public_schedule_returns_matches(self, db_session, sample_data):
        """Test that get_public_schedule returns matches with correct fields."""
        result = get_public_schedule(db_session, tournament_id=sample_data["tournament"].id)
        assert len(result) == 3
        
        # Check first match has all required fields
        m = result[0]
        assert "id" in m
        assert "tournament_id" in m
        assert "tournament_name" in m
        assert "player1" in m
        assert "player2" in m
        assert "winner" in m
        assert "score" in m
        assert "status" in m
        assert "call_status" in m
        assert "scheduled_time" in m
        assert "location" in m
        assert "round_number" in m
        assert "bracket_index" in m
        assert "display_label" in m

    def test_get_public_schedule_display_label(self, db_session, sample_data):
        """Test display_label format."""
        result = get_public_schedule(db_session, tournament_id=sample_data["tournament"].id)
        # Active match should have label
        active_match = next(m for m in result if m["call_status"] == "active")
        assert "Round" in active_match["display_label"]
        assert "Table" in active_match["display_label"]

    def test_get_public_schedule_no_tournament_filter(self, db_session, sample_data):
        """Test get_public_schedule without tournament filter."""
        result = get_public_schedule(db_session)
        assert len(result) == 3


class TestGetPublicRankings:
    def test_get_public_rankings_sorted_by_rating(self, db_session, sample_data):
        """Test that rankings are sorted by rating descending."""
        result = get_public_rankings(db_session)
        assert len(result) == 3
        # Charlie has highest rating (1300)
        assert result[0]["name"] == "Charlie"
        # Alice has 1200
        assert result[1]["name"] == "Alice"
        # Bob has 1100
        assert result[2]["name"] == "Bob"

    def test_get_public_rankings_includes_stats(self, db_session, sample_data):
        """Test that rankings include match stats."""
        result = get_public_rankings(db_session, tournament_id=sample_data["tournament"].id)
        
        # Alice has 1 win (vs Bob)
        alice = next(p for p in result if p["name"] == "Alice")
        assert alice["wins"] == 1
        assert alice["losses"] == 0
        assert alice["matches_played"] == 1

    def test_get_public_rankings_tournament_filter(self, db_session, sample_data):
        """Test rankings with tournament filter."""
        result = get_public_rankings(db_session, tournament_id=sample_data["tournament"].id)
        assert all("player_id" in p for p in result)
        assert all("win_rate" in p for p in result)


class TestGetOperatorQueue:
    def test_get_operator_queue_returns_matches(self, db_session, sample_data):
        """Test that get_operator_queue returns matches with conflict flags."""
        result = get_operator_queue(db_session, tournament_id=sample_data["tournament"].id)
        assert len(result) == 3
        
        for m in result:
            assert "conflict_flags" in m
            assert isinstance(m["conflict_flags"], list)

    def test_get_operator_queue_conflict_detection(self, db_session, sample_data):
        """Test that table conflicts are detected."""
        # Add another match on Table 1 to create a conflict
        m4 = Match(
            player1="Alice", player2="Charlie",
            player1_id=sample_data["players"][0].id,
            player2_id=sample_data["players"][2].id,
            tournament_id=sample_data["tournament"].id,
            status=MatchStatus.pending,
            scheduled_time=datetime.utcnow() + timedelta(hours=3),
            location="Table 1",
            round_number=2,
            bracket_index=1,
            call_status="queued"
        )
        db_session.add(m4)
        db_session.commit()
        
        result = get_operator_queue(db_session, tournament_id=sample_data["tournament"].id)
        
        # Alice vs Charlie (m4) is on Table 1 which has an active match (m3)
        # Use location to distinguish from m2 (Alice vs Charlie on Table 2)
        alice_charlie_match = next(m for m in result if m["player1"] == "Alice" and m["player2"] == "Charlie" and m["location"] == "Table 1")
        assert "table_conflict" in alice_charlie_match["conflict_flags"]

    def test_get_operator_queue_missing_table_flag(self, db_session):
        """Test that missing table is flagged."""
        # Create match without location
        m = Match(player1="Test", player2="Player", call_status="queued")
        db_session.add(m)
        db_session.commit()
        
        result = get_operator_queue(db_session)
        test_match = next(m for m in result if m["player1"] == "Test")
        assert "missing_table" in test_match["conflict_flags"]


class TestGetTableStatus:
    def test_get_table_status_returns_all_tables(self, db_session, sample_data):
        """Test that get_table_status returns all active tables."""
        result = get_table_status(db_session, tournament_id=sample_data["tournament"].id)
        assert len(result) == 2
        
        for t in result:
            assert "table_id" in t
            assert "table_name" in t
            assert "current_match" in t
            assert "next_match" in t

    def test_get_table_status_current_and_next(self, db_session, sample_data):
        """Test that current and next matches are correctly identified."""
        result = get_table_status(db_session, tournament_id=sample_data["tournament"].id)
        
        table1 = next(t for t in result if t["table_name"] == "Table 1")
        # Table 1 has active match (Bob vs Charlie)
        assert table1["current_match"] is not None
        assert table1["current_match"]["player1"] == "Bob"


class TestGetNextAvailableTable:
    def test_get_next_available_table_free_table(self, db_session, sample_data):
        """Test that free table is returned when available."""
        result = get_next_available_table(db_session, tournament_id=sample_data["tournament"].id)
        # Table 2 has no active/called match
        assert result is not None
        assert result["status"] == "free"

    def test_get_next_available_table_all_busy(self, db_session):
        """Test that oldest match table is returned when all busy."""
        # Create only active matches
        p1 = Player(name="P1", rating=1000)
        p2 = Player(name="P2", rating=1000)
        p3 = Player(name="P3", rating=1000)
        db_session.add_all([p1, p2, p3])
        db_session.commit()
        
        t = Tournament(name="T")
        db_session.add(t)
        db_session.commit()
        
        table = VenueTable(name="Table 1")
        db_session.add(table)
        db_session.commit()
        
        now = datetime.utcnow()
        m1 = Match(
            player1="P1", player2="P2",
            location="Table 1",
            call_status="active",
            scheduled_time=now - timedelta(hours=2)
        )
        m2 = Match(
            player1="P2", player2="P3",
            location="Table 1",
            call_status="active",
            scheduled_time=now - timedelta(hours=1)
        )
        db_session.add_all([m1, m2])
        db_session.commit()
        
        result = get_next_available_table(db_session)
        # Should return the table with oldest match
        assert result is not None
        assert result["status"] == "busy"

    def test_get_next_available_table_no_tables(self, db_session):
        """Test with no tables."""
        result = get_next_available_table(db_session)
        assert result is None


class TestGetPlayerPath:
    def test_get_player_path_completed_and_pending(self, db_session, sample_data):
        """Test that player path returns completed and pending matches."""
        result = get_player_path(db_session, "Alice", tournament_id=sample_data["tournament"].id)
        
        assert "completed_matches" in result
        assert "next_pending_match" in result
        assert "projected_path" in result
        
        # Alice has 1 completed match
        assert len(result["completed_matches"]) == 1
        assert result["completed_matches"][0]["winner"] == "Alice"
        
        # Alice has 1 pending match
        assert result["next_pending_match"] is not None
        assert result["next_pending_match"]["player2"] == "Charlie"

    def test_get_player_path_no_matches(self, db_session, sample_data):
        """Test player path with no matches."""
        result = get_player_path(db_session, "NonExistent")
        
        assert result["completed_matches"] == []
        assert result["next_pending_match"] is None
        assert result["projected_path"] == []

    def test_get_player_path_projected(self, db_session, sample_data):
        """Test that projected path is built from next_match_id."""
        # Set up next_match_id relationship
        m1 = sample_data["matches"][0]  # Alice vs Bob (completed)
        m2 = sample_data["matches"][1]  # Alice vs Charlie (pending)
        m1.next_match_id = m2.id
        db_session.commit()
        
        result = get_player_path(db_session, "Alice", tournament_id=sample_data["tournament"].id)
        
        # Should have projected path
        assert len(result["projected_path"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])