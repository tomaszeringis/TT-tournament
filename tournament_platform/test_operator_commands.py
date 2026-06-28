"""
Tests for operator_commands service.
"""

import pytest
from datetime import datetime, timezone, timedelta
import uuid

from tournament_platform.services.operator_commands import (
    parse_operator_command,
    apply_operator_command,
    OperatorIntent,
    ParsedCommand,
)
from tournament_platform.models import SessionLocal, Match, MatchStatus, VenueTable, Tournament, init_db


@pytest.fixture
def db():
    """Create a test database session."""
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_tournament(db):
    """Create a test tournament."""
    unique_name = f"Test Tournament {uuid.uuid4().hex[:8]}"
    tournament = Tournament(name=unique_name, description="Test")
    db.add(tournament)
    db.commit()
    db.refresh(tournament)
    return tournament


@pytest.fixture
def test_table(db, test_tournament):
    """Create a test table."""
    unique_name = f"Table {uuid.uuid4().hex[:8]}"
    table = VenueTable(name=unique_name, is_active=1)
    db.add(table)
    db.commit()
    db.refresh(table)
    return table


@pytest.fixture
def test_match(db, test_tournament):
    """Create a test match."""
    match = Match(
        player1="Player A",
        player2="Player B",
        tournament_id=test_tournament.id,
        status=MatchStatus.pending,
        call_status="not_called",
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


class TestParseOperatorCommand:
    """Tests for parse_operator_command function."""

    def test_next_available_table(self):
        """Test parsing 'next available table' command."""
        result = parse_operator_command("next available table")
        assert result.intent == OperatorIntent.NEXT_AVAILABLE_TABLE
        assert result.confidence == 1.0
        assert result.requires_confirmation is False
        assert result.preview == "Find the next available table"

    def test_next_available_table_with_spaces(self):
        """Test parsing with extra spaces."""
        result = parse_operator_command("  next   available   table  ")
        assert result.intent == OperatorIntent.NEXT_AVAILABLE_TABLE

    def test_call_match_to_table(self):
        """Test parsing 'call match 12 to table 3' command."""
        result = parse_operator_command("call match 12 to table 3")
        assert result.intent == OperatorIntent.CALL_MATCH_TO_TABLE
        assert result.confidence == 1.0
        assert result.requires_confirmation is True
        assert result.args["match_id"] == 12
        assert result.args["table_id"] == 3
        assert "match #12" in result.preview.lower()
        assert "table #3" in result.preview.lower()

    def test_call_match(self):
        """Test parsing 'call match 12' command."""
        result = parse_operator_command("call match 12")
        assert result.intent == OperatorIntent.CALL_MATCH
        assert result.confidence == 1.0
        assert result.requires_confirmation is True
        assert result.args["match_id"] == 12

    def test_mark_table_delayed(self):
        """Test parsing 'mark table 2 delayed' command."""
        result = parse_operator_command("mark table 2 delayed")
        assert result.intent == OperatorIntent.MARK_TABLE_DELAYED
        assert result.confidence == 1.0
        assert result.requires_confirmation is True
        assert result.args["table_id"] == 2

    def test_delay_match(self):
        """Test parsing 'delay match 15 for 10 minutes' command."""
        result = parse_operator_command("delay match 15 for 10 minutes")
        assert result.intent == OperatorIntent.DELAY_MATCH
        assert result.confidence == 1.0
        assert result.requires_confirmation is True
        assert result.args["match_id"] == 15
        assert result.args["delay_minutes"] == 10

    def test_delay_match_singular(self):
        """Test parsing with singular 'minute'."""
        result = parse_operator_command("delay match 15 for 5 minute")
        assert result.intent == OperatorIntent.DELAY_MATCH
        assert result.args["delay_minutes"] == 5

    def test_show_player_path(self):
        """Test parsing 'show player path John Smith' command."""
        result = parse_operator_command("show player path John Smith")
        assert result.intent == OperatorIntent.SHOW_PLAYER_PATH
        assert result.confidence == 1.0
        assert result.requires_confirmation is False
        assert result.args["player_name"] == "John Smith"

    def test_show_player_path_with_spaces(self):
        """Test parsing player path with extra spaces."""
        result = parse_operator_command("show player path   John   Smith  ")
        assert result.intent == OperatorIntent.SHOW_PLAYER_PATH
        assert result.args["player_name"] == "John Smith"

    def test_announce_semifinal_start(self):
        """Test parsing 'announce semifinal start' command."""
        result = parse_operator_command("announce semifinal start")
        assert result.intent == OperatorIntent.ANNOUNCE_STAGE_START
        assert result.confidence == 1.0
        assert result.requires_confirmation is True
        assert result.args["stage_name"] == "semifinal"
        assert result.args["is_immediate"] is False

    def test_announce_final_starting_now(self):
        """Test parsing 'announce final starting now' command."""
        result = parse_operator_command("announce final starting now")
        assert result.intent == OperatorIntent.ANNOUNCE_STAGE_START
        assert result.args["stage_name"] == "final"
        assert result.args["is_immediate"] is True

    def test_unknown_command(self):
        """Test parsing unknown command."""
        result = parse_operator_command("do something random")
        assert result.intent == OperatorIntent.UNKNOWN
        assert result.confidence == 0.0
        assert len(result.errors) > 0

    def test_empty_command(self):
        """Test parsing empty command."""
        result = parse_operator_command("")
        assert result.intent == OperatorIntent.UNKNOWN
        assert result.confidence == 0.0
        assert "Empty command text" in result.errors[0]

    def test_whitespace_only_command(self):
        """Test parsing whitespace-only command."""
        result = parse_operator_command("   ")
        assert result.intent == OperatorIntent.UNKNOWN


class TestApplyOperatorCommand:
    """Tests for apply_operator_command function."""

    def test_unknown_command_returns_error(self, db):
        """Test that unknown commands return error status."""
        parsed = ParsedCommand(
            intent=OperatorIntent.UNKNOWN,
            confidence=0.0,
            errors=["Unknown command"],
        )
        result = apply_operator_command(db, parsed)
        assert result["status"] == "error"
        assert "Unknown command" in result["message"]

    def test_readonly_command_no_confirmation_needed(self, db, test_tournament):
        """Test that read-only commands execute without confirmation."""
        parsed = parse_operator_command("show player path John Smith")
        result = apply_operator_command(
            db,
            parsed,
            confirmed=False,  # Not confirmed, but should still work
            tournament_id=test_tournament.id,
        )
        assert result["status"] == "success"
        assert "player path" in result["message"].lower()

    def test_state_changing_command_needs_confirmation(self, db, test_match):
        """Test that state-changing commands require confirmation."""
        parsed = parse_operator_command(f"call match {test_match.id}")
        result = apply_operator_command(
            db,
            parsed,
            confirmed=False,
            tournament_id=test_match.tournament_id,
        )
        assert result["status"] == "needs_confirmation"
        assert result["intent"] == "call_match"

    def test_state_changing_command_with_confirmation(self, db, test_match, test_table):
        """Test that state-changing commands execute with confirmation."""
        parsed = parse_operator_command(f"call match {test_match.id} to table {test_table.id}")
        result = apply_operator_command(
            db,
            parsed,
            confirmed=True,
            tournament_id=test_match.tournament_id,
        )
        assert result["status"] == "success"
        assert "called" in result["message"].lower()

        # Verify match was updated
        db.refresh(test_match)
        assert test_match.call_status == "called"
        assert test_match.location == test_table.name

    def test_call_match_without_table(self, db, test_match):
        """Test calling a match without specifying a table."""
        parsed = parse_operator_command(f"call match {test_match.id}")
        result = apply_operator_command(
            db,
            parsed,
            confirmed=True,
            tournament_id=test_match.tournament_id,
        )
        assert result["status"] == "success"

        # Verify match was updated
        db.refresh(test_match)
        assert test_match.call_status == "called"

    def test_delay_match(self, db, test_match):
        """Test delaying a match."""
        parsed = parse_operator_command(f"delay match {test_match.id} for 10 minutes")
        result = apply_operator_command(
            db,
            parsed,
            confirmed=True,
            tournament_id=test_match.tournament_id,
        )
        assert result["status"] == "success"
        assert "delayed" in result["message"].lower()

        # Verify match was updated
        db.refresh(test_match)
        assert test_match.call_status == "delayed"
        assert test_match.delayed_until is not None

    def test_mark_table_delayed(self, db, test_table):
        """Test marking a table as delayed."""
        parsed = parse_operator_command(f"mark table {test_table.id} delayed")
        result = apply_operator_command(
            db,
            parsed,
            confirmed=True,
        )
        assert result["status"] == "success"

        # Verify table was updated
        db.refresh(test_table)
        assert test_table.notes is not None
        assert "Delayed" in test_table.notes

    def test_nonexistent_match(self, db):
        """Test calling a non-existent match."""
        parsed = parse_operator_command("call match 99999")
        result = apply_operator_command(db, parsed, confirmed=True)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_nonexistent_table(self, db):
        """Test marking a non-existent table as delayed."""
        parsed = parse_operator_command("mark table 99999 delayed")
        result = apply_operator_command(db, parsed, confirmed=True)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_next_available_table_without_tournament(self, db):
        """Test next available table without tournament context."""
        parsed = parse_operator_command("next available table")
        result = apply_operator_command(db, parsed, confirmed=True, tournament_id=None)
        assert result["status"] == "error"
        assert "Tournament ID required" in result["message"]


class TestOperatorIntentEnum:
    """Tests for OperatorIntent enum."""

    def test_intent_values(self):
        """Test that all expected intents are defined."""
        expected_intents = [
            "next_available_table",
            "call_match_to_table",
            "call_match",
            "mark_table_delayed",
            "delay_match",
            "show_player_path",
            "announce_stage_start",
            "unknown",
        ]
        for intent in expected_intents:
            assert hasattr(OperatorIntent, intent.upper().replace(" ", "_").replace("-", "_"))


class TestParsedCommand:
    """Tests for ParsedCommand dataclass."""

    def test_default_values(self):
        """Test default values for ParsedCommand."""
        cmd = ParsedCommand(intent=OperatorIntent.UNKNOWN, confidence=0.5)
        assert cmd.args == {}
        assert cmd.requires_confirmation is False
        assert cmd.preview == ""
        assert cmd.errors == []

    def test_custom_values(self):
        """Test custom values for ParsedCommand."""
        cmd = ParsedCommand(
            intent=OperatorIntent.CALL_MATCH,
            confidence=0.9,
            args={"match_id": 123},
            requires_confirmation=True,
            preview="Call match #123",
            errors=["test error"],
        )
        assert cmd.args == {"match_id": 123}
        assert cmd.requires_confirmation is True
        assert cmd.preview == "Call match #123"
        assert cmd.errors == ["test error"]