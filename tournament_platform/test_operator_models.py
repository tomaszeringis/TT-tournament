"""
Tests for operator workflow models and audit service.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import (
    Player, Match, Tournament, MatchStatus,
    VenueTable, Announcement, AuditLog, Base
)
from tournament_platform.services.audit_service import log_audit, get_audit_logs


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


class TestVenueTable:
    def test_create_venue_table(self, db_session):
        """Test creating a venue table."""
        table = VenueTable(name="Table 1", is_active=1)
        db_session.add(table)
        db_session.commit()
        
        assert table.id is not None
        assert table.name == "Table 1"
        assert table.is_active == 1

    def test_venue_table_default_values(self, db_session):
        """Test venue table default values."""
        table = VenueTable(name="Table 2")
        db_session.add(table)
        db_session.commit()
        
        assert table.is_active == 1  # Default
        assert table.notes is None
        assert table.created_at is not None

    def test_venue_table_unique_name(self, db_session):
        """Test that venue table names are unique."""
        table1 = VenueTable(name="Table 1")
        table2 = VenueTable(name="Table 1")  # Duplicate
        
        db_session.add(table1)
        db_session.commit()
        
        db_session.add(table2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


class TestMatchOperatorFields:
    def test_match_default_call_status(self, db_session):
        """Test match has default call_status."""
        match = Match(player1="Alice", player2="Bob")
        db_session.add(match)
        db_session.commit()
        
        assert match.call_status == "not_called"

    def test_match_operator_fields_nullable(self, db_session):
        """Test operator fields are nullable."""
        match = Match(
            player1="Alice",
            player2="Bob",
            call_status="queued",
            called_at=datetime.utcnow(),
            operator_note="Test note"
        )
        db_session.add(match)
        db_session.commit()
        
        assert match.called_at is not None
        assert match.operator_note == "Test note"
        assert match.started_at is None
        assert match.completed_at is None
        assert match.delayed_until is None


class TestAnnouncement:
    def test_create_announcement(self, db_session):
        """Test creating an announcement."""
        announcement = Announcement(
            message="Next match: Alice vs Bob at Table 1",
            channel="local"
        )
        db_session.add(announcement)
        db_session.commit()
        
        assert announcement.id is not None
        assert announcement.sent_status == "pending"
        assert announcement.channel == "local"

    def test_announcement_with_match(self, db_session):
        """Test announcement linked to a match."""
        match = Match(player1="Alice", player2="Bob")
        db_session.add(match)
        db_session.commit()
        
        announcement = Announcement(
            match_id=match.id,
            message="Match ready",
            channel="local"
        )
        db_session.add(announcement)
        db_session.commit()
        
        assert announcement.match_id == match.id


class TestAuditLog:
    def test_create_audit_log(self, db_session):
        """Test creating an audit log entry."""
        audit = AuditLog(
            actor="operator",
            action="call_match",
            entity_type="match",
            entity_id=1
        )
        db_session.add(audit)
        db_session.commit()
        
        assert audit.id is not None
        assert audit.actor == "operator"
        assert audit.action == "call_match"

    def test_audit_log_default_actor(self, db_session):
        """Test audit log default actor value."""
        audit = AuditLog(action="test", entity_type="test")
        db_session.add(audit)
        db_session.commit()
        
        assert audit.actor == "operator"


class TestAuditService:
    def test_log_audit_creates_entry(self, db_session):
        """Test that log_audit creates an audit entry."""
        result = log_audit(
            db=db_session,
            action="call_match",
            entity_type="match",
            entity_id=1,
            actor="test_operator",
            payload={"table": "Table 1"}
        )
        
        assert result is not None
        assert result.action == "call_match"
        assert result.entity_type == "match"
        assert result.entity_id == 1

    def test_log_audit_payload_serialization(self, db_session):
        """Test that log_audit serializes payload to JSON."""
        result = log_audit(
            db=db_session,
            action="reschedule",
            entity_type="match",
            entity_id=2,
            payload={"old_time": "10:00", "new_time": "11:00"}
        )
        
        assert result is not None
        assert '"old_time": "10:00"' in result.payload_json

    def test_log_audit_never_crashes(self, db_session):
        """Test that log_audit never crashes even with bad data."""
        # This should not raise an exception
        result = log_audit(
            db=db_session,
            action="test",
            entity_type="test",
            entity_id=999,
            payload={"bad": object()}  # Non-serializable
        )
        
        # Should still return an entry (with string fallback)
        assert result is not None

    def test_get_audit_logs(self, db_session):
        """Test retrieving audit logs."""
        log_audit(db_session, "action1", "type1", 1)
        log_audit(db_session, "action2", "type2", 2)
        
        logs = get_audit_logs(db_session, limit=10)
        assert len(logs) == 2

    def test_get_audit_logs_filter_by_entity(self, db_session):
        """Test filtering audit logs by entity type."""
        log_audit(db_session, "action1", "match", 1)
        log_audit(db_session, "action2", "tournament", 2)
        
        match_logs = get_audit_logs(db_session, entity_type="match")
        assert len(match_logs) == 1
        assert match_logs[0]["entity_type"] == "match"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])