"""
Tests for the text command router.
"""

import pytest
from datetime import datetime, timezone, timedelta

from tournament_platform.models import (
    Player, Match, Tournament, MatchStatus, VenueTable, Base
)
from tournament_platform.services.command_router import (
    parse_command,
    get_command_help,
)


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    """Create an in-memory database session for testing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_data(db_session):
    """Create sample data for testing."""
    p1 = Player(name="Alice", rating=1200)
    p2 = Player(name="Bob", rating=1100)
    db_session.add_all([p1, p2])
    db_session.commit()
    
    t = Tournament(name="Test Tournament", tournament_type="knockout")
    db_session.add(t)
    db_session.commit()
    
    m = Match(
        player1="Alice", player2="Bob",
        player1_id=p1.id, player2_id=p2.id,
        tournament_id=t.id,
        status=MatchStatus.pending,
        scheduled_time=datetime.now(timezone.utc),
        call_status="not_called"
    )
    db_session.add(m)
    db_session.commit()
    
    return {"players": [p1, p2], "tournament": t, "match": m}


class TestParseCommand:
    def test_parse_call_match(self):
        """Test parsing call command."""
        action, params = parse_command("call Alice vs Bob")
        assert action == "call"
        assert params.get("player_match") == "alice vs bob"

    def test_parse_call_match_with_table(self):
        """Test parsing call command with table."""
        action, params = parse_command("call Alice vs Bob to table 1")
        assert action == "call"
        assert params.get("player_match") == "alice vs bob"
        assert params.get("table") == "1"

    def test_parse_start_match(self):
        """Test parsing start command."""
        action, params = parse_command("start Alice vs Bob")
        assert action == "start"
        assert params.get("player_match") == "alice vs bob"

    def test_parse_complete_match(self):
        """Test parsing complete command."""
        action, params = parse_command("complete Alice vs Bob")
        assert action == "complete"
        assert params.get("player_match") == "alice vs bob"

    def test_parse_delay_match(self):
        """Test parsing delay command."""
        action, params = parse_command("delay Alice vs Bob for 15 minutes")
        assert action == "delay"
        assert params.get("player_match") == "alice vs bob"
        assert params.get("delay_minutes") == 15

    def test_parse_path_command(self):
        """Test parsing path command."""
        action, params = parse_command("path Alice")
        assert action == "path"
        assert params.get("player_name") == "alice"

    def test_parse_tables_command(self):
        """Test parsing tables command."""
        action, params = parse_command("tables")
        assert action == "tables"

    def test_parse_unknown_command(self):
        """Test parsing unknown command."""
        action, params = parse_command("unknown command")
        assert action is None
        assert params is None


class TestCommandHelp:
    def test_get_command_help(self):
        """Test that help text is returned."""
        help_text = get_command_help()
        assert "call" in help_text
        assert "start" in help_text
        assert "complete" in help_text
        assert "delay" in help_text
        assert "reschedule" in help_text
        assert "path" in help_text
        assert "tables" in help_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])