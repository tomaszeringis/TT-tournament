"""
Tests for table availability service.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import (
    Player, Match, Tournament, MatchStatus, VenueTable, Base, AuditLog
)
from tournament_platform.services.table_availability_service import (
    get_table_availability_summary,
    set_max_available_tables,
    ensure_minimum_venue_tables,
)
from tournament_platform.services.tournament_read_models import (
    get_table_status,
    get_next_available_table,
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
    table1 = VenueTable(name="Table 1", is_active=1)
    table2 = VenueTable(name="Table 2", is_active=1)
    table3 = VenueTable(name="Table 3", is_active=1)
    table4 = VenueTable(name="Table 4", is_active=0)  # Inactive
    db_session.add_all([table1, table2, table3, table4])
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
        call_status="active"  # Busy table
    )

    m3 = Match(
        player1="Bob", player2="Charlie",
        player1_id=p2.id, player2_id=p3.id,
        tournament_id=t.id,
        status=MatchStatus.pending,
        scheduled_time=now,
        location="Table 3",
        round_number=1,
        bracket_index=1,
        call_status="called"  # Busy table
    )

    db_session.add_all([m1, m2, m3])
    db_session.commit()

    return {"players": [p1, p2, p3], "tournament": t, "tables": [table1, table2, table3, table4], "matches": [m1, m2, m3]}


class TestGetTableAvailabilitySummary:
    def test_returns_all_tables(self, db_session, sample_data):
        """Test that summary returns all tables."""
        result = get_table_availability_summary(db_session)
        assert result["total_tables"] == 4
        assert result["active_tables"] == 3
        assert result["inactive_tables"] == 1

    def test_includes_table_details(self, db_session, sample_data):
        """Test that each table has required fields."""
        result = get_table_availability_summary(db_session)
        for table in result["tables"]:
            assert "id" in table
            assert "name" in table
            assert "is_active" in table
            assert "notes" in table
            assert "current_match_id" in table
            assert "current_match_label" in table
            assert "has_active_or_called_match" in table

    def test_detects_busy_tables(self, db_session, sample_data):
        """Test that busy tables are correctly identified."""
        result = get_table_availability_summary(db_session)
        table2 = next(t for t in result["tables"] if t["name"] == "Table 2")
        table3 = next(t for t in result["tables"] if t["name"] == "Table 3")

        assert table2["has_active_or_called_match"] is True
        assert table3["has_active_or_called_match"] is True

    def test_no_tables(self, db_session):
        """Test with no tables."""
        result = get_table_availability_summary(db_session)
        assert result["total_tables"] == 0
        assert result["active_tables"] == 0
        assert result["inactive_tables"] == 0
        assert result["tables"] == []


class TestSetMaxAvailableTables:
    def test_activates_requested_number(self, db_session, sample_data):
        """Test that set_max_available_tables activates only the requested number."""
        result = set_max_available_tables(db_session, max_tables=2)

        assert result["requested_max_tables"] == 2
        # Table 2 and 3 are busy, so they should stay active
        # When max=2 and 2 busy tables, we get exactly 2 active
        assert result["resulting_active_tables"] == 2

    def test_deactivates_tables_above_limit(self, db_session, sample_data):
        """Test that tables above the limit are deactivated."""
        # First set to 4 to activate all
        set_max_available_tables(db_session, max_tables=4)

        # Now set to 2
        result = set_max_available_tables(db_session, max_tables=2)

        # Check that some tables were deactivated
        assert result["updated_tables"] > 0

    def test_busy_table_not_deactivated(self, db_session, sample_data):
        """Test that busy active/called table is not deactivated when prefer_keep_busy_tables_active=True."""
        result = set_max_available_tables(
            db_session,
            max_tables=1,
            prefer_keep_busy_tables_active=True
        )

        # Should have warning about busy tables
        assert any("busy tables" in w for w in result["warnings"])

        # Busy tables should still be active
        table2 = next(t for t in result["table_summaries"] if t["name"] == "Table 2")
        table3 = next(t for t in result["table_summaries"] if t["name"] == "Table 3")
        assert table2["is_active"] is True
        assert table3["is_active"] is True

    def test_all_busy_exceeds_max(self, db_session, sample_data):
        """Test that if busy table count exceeds requested max, warning is returned."""
        result = set_max_available_tables(
            db_session,
            max_tables=1,
            prefer_keep_busy_tables_active=True
        )

        # 2 busy tables, max is 1
        assert any("busy tables" in w and "exceeds" in w for w in result["warnings"])

    def test_invalid_negative_max(self, db_session, sample_data):
        """Test that invalid negative max_tables fails safely."""
        result = set_max_available_tables(db_session, max_tables=-1)

        assert result["requested_max_tables"] == -1
        assert "max_tables must be >= 0" in result["warnings"]
        # No tables should have changed
        assert result["updated_tables"] == 0

    def test_creates_audit_log(self, db_session, sample_data):
        """Test that action writes AuditLog."""
        set_max_available_tables(db_session, max_tables=2)

        audit_entries = db_session.query(AuditLog).filter(
            AuditLog.action == "set_max_available_tables"
        ).all()

        assert len(audit_entries) == 1
        assert audit_entries[0].entity_type == "venue_table"

    def test_no_venue_tables(self, db_session):
        """Test with no venue tables returns useful warning."""
        result = set_max_available_tables(db_session, max_tables=4)

        assert any("No venue tables exist" in w for w in result["warnings"])
        assert result["resulting_active_tables"] == 0


class TestGetTableStatus:
    def test_includes_is_active(self, db_session, sample_data):
        """Test that get_table_status includes is_active field."""
        result = get_table_status(db_session)

        for table in result:
            assert "is_active" in table

    def test_includes_status_string(self, db_session, sample_data):
        """Test that get_table_status includes status string."""
        result = get_table_status(db_session)

        for table in result:
            assert "status" in table
            assert table["status"] in ["busy", "available", "inactive"]

    def test_busy_status(self, db_session, sample_data):
        """Test that busy status is correctly set."""
        result = get_table_status(db_session)

        table2 = next(t for t in result if t["table_name"] == "Table 2")
        assert table2["status"] == "busy"

    def test_inactive_status(self, db_session, sample_data):
        """Test that inactive status is correctly set."""
        result = get_table_status(db_session)

        table4 = next(t for t in result if t["table_name"] == "Table 4")
        assert table4["status"] == "inactive"

    def test_available_status(self, db_session, sample_data):
        """Test that available status is correctly set."""
        result = get_table_status(db_session)

        table1 = next(t for t in result if t["table_name"] == "Table 1")
        assert table1["status"] == "available"


class TestGetNextAvailableTable:
    def test_excludes_inactive_tables(self, db_session, sample_data):
        """Test that inactive tables are excluded from next available table recommendations."""
        result = get_next_available_table(db_session)

        # Should return a table, and it should be active
        assert result is not None
        # Table 4 is inactive, so it should not be returned
        assert result["table_name"] != "Table 4"

    def test_all_inactive_returns_none(self, db_session):
        """Test that all inactive tables does not crash get_next_available_table."""
        # Create only inactive tables
        table1 = VenueTable(name="Table 1", is_active=0)
        table2 = VenueTable(name="Table 2", is_active=0)
        db_session.add_all([table1, table2])
        db_session.commit()

        result = get_next_available_table(db_session)
        assert result is None

    def test_no_tables_returns_none(self, db_session):
        """Test that no tables returns None gracefully."""
        result = get_next_available_table(db_session)
        assert result is None


class TestEnsureMinimumVenueTables:
    def test_creates_missing_tables(self, db_session, sample_data):
        """Test that ensure_minimum_venue_tables creates missing tables."""
        result = ensure_minimum_venue_tables(db_session, count=6)

        assert result["requested_count"] == 6
        assert result["created_tables"] == 2  # Table 5 and 6
        assert "Table 5" in result["table_names"]
        assert "Table 6" in result["table_names"]

    def test_no_duplicates(self, db_session, sample_data):
        """Test that existing tables are not duplicated."""
        # Already have 4 tables
        result = ensure_minimum_venue_tables(db_session, count=3)

        assert result["created_tables"] == 0
        assert result["table_names"] == []

    def test_creates_audit_log(self, db_session, sample_data):
        """Test that ensure_minimum_venue_tables creates audit log."""
        ensure_minimum_venue_tables(db_session, count=6)

        audit_entries = db_session.query(AuditLog).filter(
            AuditLog.action == "ensure_minimum_venue_tables"
        ).all()

        assert len(audit_entries) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])