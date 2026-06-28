"""
Operator commands service for text/voice shortcuts.

This module provides deterministic parsing and execution of operator commands
for match management, table assignment, and player path queries.
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Any, Dict, List

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, VenueTable, Announcement
from tournament_platform.services.tournament_read_models import (
    get_next_available_table,
    get_player_path,
)
from tournament_platform.services.audit_service import log_audit

logger = logging.getLogger(__name__)


class OperatorIntent(str, Enum):
    """Supported operator command intents."""
    NEXT_AVAILABLE_TABLE = "next_available_table"
    CALL_MATCH_TO_TABLE = "call_match_to_table"
    CALL_MATCH = "call_match"
    MARK_TABLE_DELAYED = "mark_table_delayed"
    DELAY_MATCH = "delay_match"
    SHOW_PLAYER_PATH = "show_player_path"
    ANNOUNCE_STAGE_START = "announce_stage_start"
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    """Result of parsing an operator command text."""
    intent: OperatorIntent
    confidence: float  # 0.0 to 1.0
    args: Dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    preview: str = ""
    errors: List[str] = field(default_factory=list)


# Command patterns for deterministic parsing
_COMMAND_PATTERNS = [
    # "next available table" - read only, no confirmation needed
    (r"^next\s+available\s+table\s*$", OperatorIntent.NEXT_AVAILABLE_TABLE, 1.0, False),
    
    # "call match 12 to table 3" - state changing, needs confirmation
    (r"^call\s+match\s+(\d+)\s+to\s+table\s+(\d+)\s*$", OperatorIntent.CALL_MATCH_TO_TABLE, 1.0, True),
    
    # "call match 12" - state changing, needs confirmation
    (r"^call\s+match\s+(\d+)\s*$", OperatorIntent.CALL_MATCH, 1.0, True),
    
    # "mark table 2 delayed" - state changing, needs confirmation
    (r"^mark\s+table\s+(\d+)\s+delayed\s*$", OperatorIntent.MARK_TABLE_DELAYED, 1.0, True),
    
    # "delay match 15 for 10 minutes" - state changing, needs confirmation
    (r"^delay\s+match\s+(\d+)\s+for\s+(\d+)\s+minutes?\s*$", OperatorIntent.DELAY_MATCH, 1.0, True),
    
    # "show player path John Smith" - read only, no confirmation needed
    (r"^show\s+player\s+path\s+(.+)\s*$", OperatorIntent.SHOW_PLAYER_PATH, 1.0, False),
    
    # "announce semifinal start" - state changing, needs confirmation
    (r"^announce\s+(.+?)\s+start(ing)?\s*(now)?\s*$", OperatorIntent.ANNOUNCE_STAGE_START, 1.0, True),
]


def parse_operator_command(text: str) -> ParsedCommand:
    """
    Parse operator command text into a structured ParsedCommand.
    
    Uses deterministic regex matching for supported commands.
    
    Args:
        text: The command text to parse (case-insensitive)
        
    Returns:
        ParsedCommand with intent, args, confidence, and preview
    """
    if not text or not text.strip():
        return ParsedCommand(
            intent=OperatorIntent.UNKNOWN,
            confidence=0.0,
            errors=["Empty command text"],
        )
    
    original_text = text.strip()
    text_lower = original_text.lower()
    
    for pattern, intent, confidence, needs_confirm in _COMMAND_PATTERNS:
        match = re.match(pattern, text_lower)
        if match:
            args = {}
            groups = match.groups()
            
            if intent == OperatorIntent.NEXT_AVAILABLE_TABLE:
                preview = "Find the next available table"
                
            elif intent == OperatorIntent.CALL_MATCH_TO_TABLE:
                args["match_id"] = int(groups[0])
                args["table_id"] = int(groups[1])
                preview = f"Call match #{args['match_id']} to table #{args['table_id']}"
                
            elif intent == OperatorIntent.CALL_MATCH:
                args["match_id"] = int(groups[0])
                preview = f"Call match #{args['match_id']}"
                
            elif intent == OperatorIntent.MARK_TABLE_DELAYED:
                args["table_id"] = int(groups[0])
                preview = f"Mark table #{args['table_id']} as delayed"
                
            elif intent == OperatorIntent.DELAY_MATCH:
                args["match_id"] = int(groups[0])
                args["delay_minutes"] = int(groups[1])
                preview = f"Delay match #{args['match_id']} for {args['delay_minutes']} minutes"
                
            elif intent == OperatorIntent.SHOW_PLAYER_PATH:
                # Extract player name with original casing, normalize whitespace
                name_match = re.match(r"^show\s+player\s+path\s+(.+)\s*$", original_text, re.IGNORECASE)
                if name_match:
                    # Normalize whitespace in player name
                    args["player_name"] = re.sub(r'\s+', ' ', name_match.group(1).strip())
                else:
                    args["player_name"] = re.sub(r'\s+', ' ', groups[0].strip())
                preview = f"Show player path for: {args['player_name']}"
                
            elif intent == OperatorIntent.ANNOUNCE_STAGE_START:
                args["stage_name"] = groups[0].strip()
                args["is_immediate"] = groups[2] is not None  # "now" captured
                preview = f"Announce {args['stage_name']} start"
            
            return ParsedCommand(
                intent=intent,
                confidence=confidence,
                args=args,
                requires_confirmation=needs_confirm,
                preview=preview,
            )
    
    # No pattern matched
    return ParsedCommand(
        intent=OperatorIntent.UNKNOWN,
        confidence=0.0,
        errors=[f"Unknown command: '{original_text}'"],
    )


def apply_operator_command(
    db: Session,
    parsed_command: ParsedCommand,
    confirmed: bool = False,
    tournament_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Apply a parsed operator command to the database.
    
    For read-only commands, returns result without requiring confirmation.
    For state-changing commands, requires confirmed=True.
    
    Args:
        db: SQLAlchemy database session
        parsed_command: The parsed command to apply
        confirmed: Whether the operator has confirmed the action
        tournament_id: Optional tournament context for the command
        
    Returns:
        Structured result with status, message, and any relevant data
    """
    if parsed_command.intent == OperatorIntent.UNKNOWN:
        return {
            "status": "error",
            "message": "Unknown command",
            "errors": parsed_command.errors,
        }
    
    # Handle read-only commands (no confirmation needed)
    if not parsed_command.requires_confirmation:
        return _apply_readonly_command(db, parsed_command, tournament_id)
    
    # Handle state-changing commands (confirmation required)
    if not confirmed:
        return {
            "status": "needs_confirmation",
            "message": "This action requires confirmation",
            "intent": parsed_command.intent.value,
            "args": parsed_command.args,
            "preview": parsed_command.preview,
        }
    
    return _apply_state_changing_command(db, parsed_command, tournament_id)


def _apply_readonly_command(
    db: Session,
    parsed_command: ParsedCommand,
    tournament_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply read-only commands that don't modify state."""
    if parsed_command.intent == OperatorIntent.NEXT_AVAILABLE_TABLE:
        if not tournament_id:
            return {
                "status": "error",
                "message": "Tournament ID required for this command",
            }
        result = get_next_available_table(db, tournament_id=tournament_id)
        return {
            "status": "success",
            "message": f"Next available table: {result.get('table_name', 'None')}",
            "data": result,
        }
    
    elif parsed_command.intent == OperatorIntent.SHOW_PLAYER_PATH:
        player_name = parsed_command.args.get("player_name", "")
        result = get_player_path(db, player_name, tournament_id=tournament_id)
        return {
            "status": "success",
            "message": f"Player path for {player_name}",
            "data": result,
        }
    
    return {
        "status": "error",
        "message": f"Unknown read-only intent: {parsed_command.intent}",
    }


def _apply_state_changing_command(
    db: Session,
    parsed_command: ParsedCommand,
    tournament_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply state-changing commands that modify the database."""
    if parsed_command.intent == OperatorIntent.CALL_MATCH_TO_TABLE:
        match_id = parsed_command.args.get("match_id")
        table_id = parsed_command.args.get("table_id")
        
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            return {
                "status": "error",
                "message": f"Match #{match_id} not found",
            }
        
        table = db.query(VenueTable).filter(VenueTable.id == table_id).first()
        if not table:
            return {
                "status": "error",
                "message": f"Table #{table_id} not found",
            }
        
        # Update match call status
        match.call_status = "called"
        match.location = table.name
        match.called_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(match)
        
        # Log audit
        log_audit(
            db,
            action="call_match",
            entity_type="match",
            entity_id=match_id,
            payload={
                "table_id": table_id,
                "table_name": table.name,
                "call_status": "called",
            },
        )
        
        return {
            "status": "success",
            "message": f"Match #{match_id} called to table {table.name}",
            "match_id": match_id,
            "table_id": table_id,
        }
    
    elif parsed_command.intent == OperatorIntent.CALL_MATCH:
        match_id = parsed_command.args.get("match_id")
        
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            return {
                "status": "error",
                "message": f"Match #{match_id} not found",
            }
        
        # Update match call status (without specific table)
        match.call_status = "called"
        match.called_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(match)
        
        # Log audit
        log_audit(
            db,
            action="call_match",
            entity_type="match",
            entity_id=match_id,
            payload={
                "call_status": "called",
                "no_table_specified": True,
            },
        )
        
        return {
            "status": "success",
            "message": f"Match #{match_id} called",
            "match_id": match_id,
        }
    
    elif parsed_command.intent == OperatorIntent.MARK_TABLE_DELAYED:
        table_id = parsed_command.args.get("table_id")
        
        table = db.query(VenueTable).filter(VenueTable.id == table_id).first()
        if not table:
            return {
                "status": "error",
                "message": f"Table #{table_id} not found",
            }
        
        # Update table status (we use operator_note to indicate delay)
        table.notes = f"Delayed at {datetime.now(timezone.utc).isoformat()}"
        db.commit()
        db.refresh(table)
        
        # Log audit
        log_audit(
            db,
            action="mark_table_delayed",
            entity_type="table",
            entity_id=table_id,
            payload={
                "table_name": table.name,
                "notes": table.notes,
            },
        )
        
        return {
            "status": "success",
            "message": f"Table #{table_id} marked as delayed",
            "table_id": table_id,
        }
    
    elif parsed_command.intent == OperatorIntent.DELAY_MATCH:
        match_id = parsed_command.args.get("match_id")
        delay_minutes = parsed_command.args.get("delay_minutes", 15)
        
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            return {
                "status": "error",
                "message": f"Match #{match_id} not found",
            }
        
        # Calculate delayed_until time
        delayed_until = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
        
        # Update match
        match.call_status = "delayed"
        match.delayed_until = delayed_until
        db.commit()
        db.refresh(match)
        
        # Log audit
        log_audit(
            db,
            action="delay_match",
            entity_type="match",
            entity_id=match_id,
            payload={
                "delay_minutes": delay_minutes,
                "delayed_until": delayed_until.isoformat(),
            },
        )
        
        return {
            "status": "success",
            "message": f"Match #{match_id} delayed for {delay_minutes} minutes",
            "match_id": match_id,
            "delayed_until": delayed_until.isoformat(),
        }
    
    elif parsed_command.intent == OperatorIntent.ANNOUNCE_STAGE_START:
        stage_name = parsed_command.args.get("stage_name", "")
        
        # Create announcement record
        announcement = Announcement(
            message=f"{stage_name} starting",
            channel="local",
            sent_status="pending",
        )
        db.add(announcement)
        db.commit()
        db.refresh(announcement)
        
        # Log audit
        log_audit(
            db,
            action="announce_stage_start",
            entity_type="announcement",
            entity_id=announcement.id,
            payload={
                "stage_name": stage_name,
                "is_immediate": parsed_command.args.get("is_immediate", False),
            },
        )
        
        return {
            "status": "success",
            "message": f"Announced: {stage_name} start",
            "announcement_id": announcement.id,
        }
    
    return {
        "status": "error",
        "message": f"Unknown state-changing intent: {parsed_command.intent}",
    }