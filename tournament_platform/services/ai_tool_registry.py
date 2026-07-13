"""
AI Tool Registry - Typed tool definitions for the AI facade.

This module provides a registry of deterministic tools that the AI can use
to answer questions and perform actions. Tools are classified as:
- READ: Execute immediately, return data
- WRITE_PREVIEW: Return preview data, require explicit confirmation before write
"""

from typing import Protocol, List, Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Player, Tournament, VenueTable
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_operator_queue,
    get_table_status,
    get_next_available_table,
    get_player_path,
)
from tournament_platform.services.standings_service import get_standings
from tournament_platform.services.audit_service import log_audit


class ToolType(str, Enum):
    """Classification of tool behavior."""
    READ = "read"  # Execute immediately, no confirmation needed
    WRITE_PREVIEW = "write_preview"  # Return preview, require confirmation


@dataclass
class ToolResult:
    """Result from a tool execution."""
    tool_name: str
    success: bool
    data: Any
    error: Optional[str] = None
    preview: Optional[Dict[str, Any]] = None  # For write_preview tools


class Tool(Protocol):
    """Protocol for AI tools."""
    
    @property
    def name(self) -> str:
        """Unique tool name."""
        ...
    
    @property
    def tool_type(self) -> ToolType:
        """Whether this is a read or write_preview tool."""
        ...
    
    @property
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        ...
    
    def execute(self, db: Session, **kwargs) -> ToolResult:
        """Execute the tool with the given arguments."""
        ...


# ============================================================================
# Read Tools (execute immediately)
# ============================================================================

class ListTournamentsTool:
    """Return all tournaments with basic info."""
    
    name = "list_tournaments"
    tool_type = ToolType.READ
    description = "List all tournaments with their ID, name, and type"
    
    def execute(self, db: Session, **kwargs) -> ToolResult:
        try:
            data = list_tournaments(db)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class GetOperatorQueueTool:
    """Return the operator queue for a tournament."""
    
    name = "get_operator_queue"
    tool_type = ToolType.READ
    description = "Get pending/queued/called/active/delayed matches for a tournament"
    
    def execute(self, db: Session, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            data = get_operator_queue(db, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class GetTableStatusTool:
    """Return table status for a tournament."""
    
    name = "get_table_status"
    tool_type = ToolType.READ
    description = "Get each venue table and its current/next match"
    
    def execute(self, db: Session, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            data = get_table_status(db, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class GetNextAvailableTableTool:
    """Return the next available table."""
    
    name = "get_next_available_table"
    tool_type = ToolType.READ
    description = "Find the next available table for a match"
    
    def execute(self, db: Session, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            data = get_next_available_table(db, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class GetPublicRankingsTool:
    """Return public rankings for a tournament."""
    
    name = "get_public_rankings"
    tool_type = ToolType.READ
    description = "Get players sorted by rating with win/loss stats"
    
    def execute(self, db: Session, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            data = get_standings(db, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class GetPlayerPathTool:
    """Return a player's path through a tournament."""
    
    name = "get_player_path"
    tool_type = ToolType.READ
    description = "Get a player's match history and projected bracket path"
    
    def execute(self, db: Session, player_name: str, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            data = get_player_path(db, player_name, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


# ============================================================================
# Write Preview Tools (return preview, require confirmation)
# ============================================================================

class GetTournamentHealthTool:
    """Get tournament health with issues (read-only, but returns structured issues)."""
    
    name = "get_tournament_health"
    tool_type = ToolType.READ
    description = "Get tournament health including match counts, table utilization, and detected issues"
    
    def execute(self, db: Session, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            # Import here to avoid circular import
            from tournament_platform.services.health_service import get_tournament_health
            data = get_tournament_health(db, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class FindDuplicatePlayersTool:
    """Find potential duplicate players (read-only analysis)."""
    
    name = "find_duplicate_players"
    tool_type = ToolType.READ
    description = "Find players with matching emails or similar names"
    
    def execute(self, db: Session, **kwargs) -> ToolResult:
        try:
            from tournament_platform.services.duplicate_players import find_duplicate_candidates
            data = find_duplicate_candidates(db)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class ValidatePairingsTool:
    """Validate tournament pairings (read-only analysis)."""
    
    name = "validate_pairings"
    tool_type = ToolType.READ
    description = "Validate knockout links, byes, and bracket consistency"
    
    def execute(self, db: Session, tournament_id: int, **kwargs) -> ToolResult:
        try:
            from tournament_platform.services.pairing_validator import validate_tournament_pairings
            data = validate_tournament_pairings(db, tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class ForecastMatchStartTool:
    """Forecast match start times (read-only simulation)."""
    
    name = "forecast_match_start"
    tool_type = ToolType.READ
    description = "Forecast when matches will start based on current table availability"
    
    def execute(self, db: Session, tournament_id: Optional[int] = None, **kwargs) -> ToolResult:
        try:
            from tournament_platform.services.schedule_forecast import forecast_match_start_times
            data = forecast_match_start_times(db, tournament_id=tournament_id)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


class CreateAnnouncementPreviewTool:
    """Create announcement preview (no write, just preview)."""
    
    name = "create_announcement_preview"
    tool_type = ToolType.WRITE_PREVIEW
    description = "Preview an announcement message for a match or stage"
    
    def execute(
        self,
        db: Session,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
        template_type: str = "match_call",
        **kwargs
    ) -> ToolResult:
        try:
            from tournament_platform.services.announcement_templates import render_announcement_template
            from tournament_platform.services.announcement_service import (
                generate_match_call_message,
                generate_semifinal_start_message,
                generate_final_start_message,
            )
            
            if match_id:
                match = db.query(Match).filter(Match.id == match_id).first()
                if not match:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        data=None,
                        error=f"Match {match_id} not found",
                    )
                message = generate_match_call_message(match)
            elif tournament_id:
                tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
                if not tournament:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        data=None,
                        error=f"Tournament {tournament_id} not found",
                    )
                if template_type == "semifinal_start":
                    message = generate_semifinal_start_message(tournament)
                elif template_type == "final_start":
                    message = generate_final_start_message(tournament)
                else:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        data=None,
                        error=f"Unknown template type: {template_type}",
                    )
            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    data=None,
                    error="Either match_id or tournament_id required",
                )
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={"message": message, "template_type": template_type},
                preview={"message": message, "match_id": match_id, "tournament_id": tournament_id},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(e),
            )


# ============================================================================
# Tool Registry
# ============================================================================

# Registry of all available tools
TOOL_REGISTRY: Dict[str, Tool] = {
    "list_tournaments": ListTournamentsTool(),
    "get_operator_queue": GetOperatorQueueTool(),
    "get_table_status": GetTableStatusTool(),
    "get_next_available_table": GetNextAvailableTableTool(),
    "get_public_rankings": GetPublicRankingsTool(),
    "get_player_path": GetPlayerPathTool(),
    "get_tournament_health": GetTournamentHealthTool(),
    "find_duplicate_players": FindDuplicatePlayersTool(),
    "validate_pairings": ValidatePairingsTool(),
    "forecast_match_start": ForecastMatchStartTool(),
    "create_announcement_preview": CreateAnnouncementPreviewTool(),
}


def get_tool(name: str) -> Optional[Tool]:
    """Get a tool by name."""
    return TOOL_REGISTRY.get(name)


def get_all_tools() -> List[Dict[str, str]]:
    """Get all tools with their metadata."""
    return [
        {
            "name": tool.name,
            "type": tool.tool_type.value,
            "description": tool.description,
        }
        for tool in TOOL_REGISTRY.values()
    ]


def execute_tool(
    tool_name: str,
    db: Session,
    confirmed: bool = False,
    **kwargs
) -> ToolResult:
    """
    Execute a tool by name.
    
    For write_preview tools, if not confirmed, returns preview data.
    For read tools, always executes immediately.
    """
    tool = get_tool(tool_name)
    if tool is None:
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"Unknown tool: {tool_name}",
        )
    
    return tool.execute(db, **kwargs)