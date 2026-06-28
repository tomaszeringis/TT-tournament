"""
Tests for API endpoints using FastAPI TestClient.
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import the app
import sys
sys.path.insert(0, '.')
from tournament_platform.api.server import app, get_db
from tournament_platform.models import Player, Match, Tournament, MatchStatus, VenueTable, Base, AuditLog
from tournament_platform.services.audit_service import log_audit


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def test_db():
    """Create an in-memory database session for testing."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_data(test_db):
    """Create sample data for testing."""
    # Create players
    p1 = Player(name="Alice", rating=1200)
    p2 = Player(name="Bob", rating=1100)
    p3 = Player(name="Charlie", rating=1300)
    test_db.add_all([p1, p2, p3])
    test_db.commit()
    
    # Create tournament
    t = Tournament(name="Test Tournament", tournament_type="knockout")
    test_db.add(t)
    test_db.commit()
    
    # Create venue tables
    table1 = VenueTable(name="Table 1")
    table2 = VenueTable(name="Table 2")
    test_db.add_all([table1, table2])
    test_db.commit()
    
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
    
    test_db.add_all([m1, m2, m3])
    test_db.commit()
    
    return {"players": [p1, p2, p3], "tournament": t, "tables": [table1, table2], "matches": [m1, m2, m3]}


@pytest.fixture
def client(test_db):
    """Create a test client for the FastAPI app."""
    # Override the database dependency using FastAPI's dependency_overrides
    # get_db is a generator, so we need to wrap it properly
    def get_test_db():
        yield test_db
    
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestPublicEndpoints:
    """Tests for public API endpoints."""

    def test_list_tournaments(self, client, sample_data):
        """Test listing all tournaments."""
        response = client.get("/api/public/tournaments")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_public_schedule(self, client, sample_data):
        """Test getting public schedule for a tournament."""
        response = client.get(f"/api/public/tournaments/{sample_data['tournament'].id}/schedule")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_public_rankings(self, client, sample_data):
        """Test getting public rankings for a tournament."""
        response = client.get(f"/api/public/tournaments/{sample_data['tournament'].id}/rankings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_player_path(self, client, sample_data):
        """Test getting player path."""
        response = client.get(f"/api/public/player/Alice/path?tournament_id={sample_data['tournament'].id}")
        assert response.status_code == 200
        data = response.json()
        assert "player_name" in data


class TestOperatorEndpoints:
    """Tests for operator API endpoints."""

    def test_get_operator_queue(self, client, sample_data):
        """Test getting operator queue."""
        response = client.get(f"/api/operator/tournaments/{sample_data['tournament'].id}/queue")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_table_status(self, client, sample_data):
        """Test getting table status."""
        response = client.get(f"/api/operator/tournaments/{sample_data['tournament'].id}/tables")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_next_available_table(self, client, sample_data):
        """Test getting next available table."""
        response = client.get(f"/api/operator/tournaments/{sample_data['tournament'].id}/tables/available")
        assert response.status_code == 200
        data = response.json()
        assert "table" in data or "status" in data

    def test_call_match(self, client, sample_data):
        """Test calling a match."""
        match = sample_data["matches"][1]  # Alice vs Charlie (queued)
        response = client.post(
            f"/api/operator/matches/{match.id}/call",
            json={"table": "Table 1"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["call_status"] == "called"

    def test_start_match(self, client, sample_data):
        """Test starting a match."""
        match = sample_data["matches"][1]  # Alice vs Charlie (queued)
        # First call the match
        client.post(f"/api/operator/matches/{match.id}/call", json={})
        
        response = client.post(f"/api/operator/matches/{match.id}/start")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["call_status"] == "active"

    def test_complete_match(self, client, sample_data):
        """Test completing a match."""
        match = sample_data["matches"][1]  # Alice vs Charlie (queued)
        # First call and start the match
        client.post(f"/api/operator/matches/{match.id}/call", json={})
        client.post(f"/api/operator/matches/{match.id}/start")
        
        response = client.post(f"/api/operator/matches/{match.id}/complete")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["call_status"] == "completed"

    def test_delay_match(self, client, sample_data):
        """Test delaying a match."""
        match = sample_data["matches"][1]  # Alice vs Charlie (queued)
        response = client.post(
            f"/api/operator/matches/{match.id}/delay",
            json={"delay_minutes": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["call_status"] == "delayed"

    def test_reschedule_match(self, client, sample_data):
        """Test rescheduling a match."""
        match = sample_data["matches"][1]  # Alice vs Charlie (queued)
        new_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        response = client.post(
            f"/api/operator/matches/{match.id}/reschedule",
            json={"scheduled_time": new_time, "table": "Table 2"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["call_status"] == "queued"

    def test_reset_call(self, client, sample_data):
        """Test resetting a match call."""
        match = sample_data["matches"][1]  # Alice vs Charlie (queued)
        # First call the match
        client.post(f"/api/operator/matches/{match.id}/call", json={"table": "Table 1"})
        
        response = client.post(f"/api/operator/matches/{match.id}/reset-call")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["call_status"] == "queued"

    def test_get_audit_logs(self, client, test_db, sample_data):
        """Test getting audit logs."""
        # Create an audit entry
        log_audit(
            test_db,
            action="test_action",
            entity_type="match",
            entity_id=sample_data["matches"][0].id,
            actor="test_operator"
        )
        
        response = client.get("/api/operator/audit")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])