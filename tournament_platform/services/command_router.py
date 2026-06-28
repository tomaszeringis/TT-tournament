"""
Text Command Router for Operator Actions

Provides deterministic text-based shortcuts for common operator actions.
Commands are parsed and validated before execution.
"""

import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus
from tournament_platform.services.audit_service import log_audit


# Command patterns and their handlers
COMMAND_PATTERNS = {
    # Call match patterns
    "call": [
        r"^call\s+(.+?)\s+to\s+table\s+(\d+)$",  # "call Alice vs Bob to table 1"
        r"^call\s+(.+?)$",  # "call Alice vs Bob"
        r"^call\s+match\s+(\d+)$",  # "call match 123"
    ],
    # Start match patterns
    "start": [
        r"^start\s+(.+?)$",  # "start Alice vs Bob"
        r"^start\s+match\s+(\d+)$",  # "start match 123"
    ],
    # Complete match patterns
    "complete": [
        r"^complete\s+(.+?)$",  # "complete Alice vs Bob"
        r"^complete\s+match\s+(\d+)$",  # "complete match 123"
    ],
    # Delay match patterns
    "delay": [
        r"^delay\s+(.+?)\s+for\s+(\d+)\s+minutes$",  # "delay Alice vs Bob for 15 minutes"
        r"^delay\s+(.+?)$",  # "delay Alice vs Bob"
        r"^delay\s+match\s+(\d+)$",  # "delay match 123"
    ],
    # Reschedule match patterns
    "reschedule": [
        r"^reschedule\s+(.+?)\s+to\s+(.+?)\s+at\s+(.+?)$",  # "reschedule Alice vs Bob to table 1 at 14:00"
        r"^reschedule\s+match\s+(\d+)\s+to\s+(.+?)$",  # "reschedule match 123 to table 1"
    ],
    # Player path patterns
    "path": [
        r"^path\s+(.+?)$",  # "path Alice"
    ],
    # Table status patterns
    "tables": [
        r"^tables$",  # "tables"
        r"^table\s+status$",  # "table status"
    ],
}


def parse_command(text: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Parse a text command and return the action and parameters.
    
    Returns:
        Tuple of (action, params) or (None, None) if no match.
    """
    text = text.strip().lower()
    
    for action, patterns in COMMAND_PATTERNS.items():
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                groups = match.groups()
                params = {}
                
                if action == "call":
                    if len(groups) == 2:
                        params["player_match"] = groups[0]
                        params["table"] = groups[1]
                    else:
                        params["player_match"] = groups[0]
                elif action == "start":
                    if len(groups) == 2:
                        params["match_id"] = int(groups[1])
                    else:
                        params["player_match"] = groups[0]
                elif action == "complete":
                    if len(groups) == 2:
                        params["match_id"] = int(groups[1])
                    else:
                        params["player_match"] = groups[0]
                elif action == "delay":
                    if len(groups) == 2:
                        params["player_match"] = groups[0]
                        params["delay_minutes"] = int(groups[1])
                    else:
                        params["player_match"] = groups[0]
                        params["delay_minutes"] = 15
                elif action == "reschedule":
                    if len(groups) == 3:
                        params["player_match"] = groups[0]
                        params["table"] = groups[1]
                        params["time"] = groups[2]
                    else:
                        params["match_id"] = int(groups[1])
                elif action == "path":
                    params["player_name"] = groups[0]
                
                return action, params
    
    return None, None


def find_match_by_players(db: Session, player_match: str, tournament_id: Optional[int] = None) -> Optional[Match]:
    """
    Find a match by player names (e.g., "Alice vs Bob").
    """
    # Parse player names
    parts = re.split(r"\s+(?:vs|and)\s+", player_match, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None
    
    p1, p2 = parts[0].strip(), parts[1].strip()
    
    query = db.query(Match).filter(
        ((Match.player1 == p1) & (Match.player2 == p2)) |
        ((Match.player1 == p2) & (Match.player2 == p1))
    )
    
    if tournament_id:
        query = query.filter(Match.tournament_id == tournament_id)
    
    return query.order_by(Match.scheduled_time.desc()).first()


def execute_command(
    db: Session,
    text: str,
    tournament_id: Optional[int] = None,
    actor: str = "operator"
) -> Dict[str, Any]:
    """
    Execute a text command and return the result.
    
    All state-changing actions create an audit record.
    """
    action, params = parse_command(text)
    
    if action is None:
        return {
            "status": "error",
            "message": f"Unknown command: {text}",
            "action": None,
        }
    
    if action in ("call", "start", "complete", "delay", "reschedule"):
        # Find the match
        match = None
        if "match_id" in params:
            match = db.query(Match).filter(Match.id == params["match_id"]).first()
        elif "player_match" in params:
            match = find_match_by_players(db, params["player_match"], tournament_id)
        
        if not match:
            return {
                "status": "error",
                "message": f"Match not found: {params.get('player_match', params.get('match_id'))}",
                "action": action,
            }
        
        # Execute the action
        if action == "call":
            table = params.get("table")
            if table:
                match.location = f"Table {table}"
            match.call_status = "called"
            match.called_at = datetime.now(timezone.utc)
            db.commit()
            
            log_audit(db, action="call_match", entity_type="match", entity_id=match.id, actor=actor,
                     payload={"table": table, "player_match": params.get("player_match")})
            
            return {
                "status": "success",
                "action": "call",
                "match_id": match.id,
                "message": f"Called match: {match.player1} vs {match.player2} to {table or 'unassigned table'}",
            }
        
        elif action == "start":
            match.call_status = "active"
            match.started_at = datetime.now(timezone.utc)
            db.commit()
            
            log_audit(db, action="start_match", entity_type="match", entity_id=match.id, actor=actor)
            
            return {
                "status": "success",
                "action": "start",
                "match_id": match.id,
                "message": f"Started match: {match.player1} vs {match.player2}",
            }
        
        elif action == "complete":
            match.call_status = "completed"
            match.completed_at = datetime.now(timezone.utc)
            db.commit()
            
            log_audit(db, action="complete_match", entity_type="match", entity_id=match.id, actor=actor)
            
            return {
                "status": "success",
                "action": "complete",
                "match_id": match.id,
                "message": f"Completed match: {match.player1} vs {match.player2}",
            }
        
        elif action == "delay":
            delay_minutes = params.get("delay_minutes", 15)
            match.call_status = "delayed"
            match.delayed_until = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
            db.commit()
            
            log_audit(db, action="delay_match", entity_type="match", entity_id=match.id, actor=actor,
                     payload={"delay_minutes": delay_minutes})
            
            return {
                "status": "success",
                "action": "delay",
                "match_id": match.id,
                "message": f"Delayed match: {match.player1} vs {match.player2} for {delay_minutes} minutes",
            }
        
        elif action == "reschedule":
            table = params.get("table")
            time_str = params.get("time")
            
            if table:
                match.location = f"Table {table}"
            if time_str:
                try:
                    # Try to parse time
                    if ":" in time_str:
                        # Time only - use today
                        hour, minute = map(int, time_str.split(":"))
                        match.scheduled_time = datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
                    else:
                        match.scheduled_time = datetime.fromisoformat(time_str)
                except ValueError:
                    pass
            
            match.call_status = "queued"
            db.commit()
            
            log_audit(db, action="reschedule_match", entity_type="match", entity_id=match.id, actor=actor,
                     payload={"table": table, "time": time_str})
            
            return {
                "status": "success",
                "action": "reschedule",
                "match_id": match.id,
                "message": f"Rescheduled match: {match.player1} vs {match.player2}",
            }
    
    elif action == "path":
        from tournament_platform.services.tournament_read_models import get_player_path
        player_name = params.get("player_name")
        path = get_player_path(db, player_name, tournament_id=tournament_id)
        
        return {
            "status": "success",
            "action": "path",
            "player_name": player_name,
            "path": path,
        }
    
    elif action == "tables":
        from tournament_platform.services.tournament_read_models import get_table_status
        tables = get_table_status(db, tournament_id=tournament_id)
        
        return {
            "status": "success",
            "action": "tables",
            "tables": tables,
        }
    
    return {
        "status": "error",
        "message": f"Action not implemented: {action}",
        "action": action,
    }


def get_command_help() -> str:
    """Return help text for available commands."""
    return """
**Available Commands:**

- `call <player1> vs <player2>` - Call a match
- `call <player1> vs <player2> to table <n>` - Call a match to a specific table
- `start <player1> vs <player2>` - Start a match
- `complete <player1> vs <player2>` - Complete a match
- `delay <player1> vs <player2> for <n> minutes` - Delay a match
- `reschedule <player1> vs <player2> to table <n> at <time>` - Reschedule a match
- `path <player_name>` - Show player's tournament path
- `tables` - Show table status
"""