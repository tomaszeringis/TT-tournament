"""
Pydantic schemas for API request/response validation.
These schemas are used by the FastAPI endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ============================================================================
# Public Board Schemas
# ============================================================================

class TournamentInfo(BaseModel):
    """Basic tournament information for public listing."""
    id: int
    name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str


class PublicMatch(BaseModel):
    """Match information for public schedule view."""
    id: int
    player1_name: str
    player2_name: str
    status: str
    round_number: Optional[int] = None
    bracket_index: Optional[int] = None
    scheduled_time: Optional[str] = None
    location: Optional[str] = None
    score: Optional[str] = None


class PublicScheduleResponse(BaseModel):
    """Response for public schedule endpoint."""
    tournament_id: int
    tournament_name: str
    matches: List[PublicMatch] = []


class PublicRankingEntry(BaseModel):
    """Single entry in public rankings."""
    player_id: int
    name: str
    rating: int
    matches_played: int
    wins: int
    losses: int


class PublicRankingsResponse(BaseModel):
    """Response for public rankings endpoint."""
    tournament_id: int
    tournament_name: str
    rankings: List[PublicRankingEntry] = []


class PlayerPathMatch(BaseModel):
    """Match in a player's tournament path."""
    round: int
    opponent: str
    result: Optional[str] = None
    score: Optional[str] = None


class PlayerPathResponse(BaseModel):
    """Response for player path endpoint."""
    player_name: str
    tournament_id: Optional[int] = None
    tournament_name: Optional[str] = None
    current_round: int
    path: List[PlayerPathMatch] = []


# ============================================================================
# Operator Console Schemas
# ============================================================================

class CallMatchRequest(BaseModel):
    """Request to call a match to a table."""
    table: Optional[str] = None


class CallMatchResponse(BaseModel):
    """Response for call match endpoint."""
    status: str
    match_id: int
    call_status: str


class TableStatus(BaseModel):
    """Status of a single table."""
    name: str
    is_active: bool
    current_match: Optional[PublicMatch] = None


class TableStatusResponse(BaseModel):
    """Response for table status endpoint."""
    tournament_id: int
    tables: List[TableStatus] = []


class NextAvailableTableResponse(BaseModel):
    """Response for next available table endpoint."""
    table: Optional[str] = None
    status: str


class OperatorQueueMatch(BaseModel):
    """Match in the operator queue."""
    id: int
    player1_name: str
    player2_name: str
    status: str
    call_status: str
    round_number: Optional[int] = None
    scheduled_time: Optional[str] = None
    location: Optional[str] = None


class OperatorQueueResponse(BaseModel):
    """Response for operator queue endpoint."""
    tournament_id: int
    tournament_name: str
    queue: List[OperatorQueueMatch] = []


class AuditLogEntry(BaseModel):
    """Single audit log entry."""
    id: int
    action: str
    entity_type: str
    entity_id: int
    actor: str
    timestamp: str
    payload: Optional[dict] = None


class AuditLogResponse(BaseModel):
    """Response for audit log endpoint."""
    logs: List[AuditLogEntry] = []


# ============================================================================
# Text Command Router Schemas
# ============================================================================

class TextCommandRequest(BaseModel):
    """Request to process a text command."""
    command: str = Field(..., description="Text command to process (e.g., 'call match 123 table 4')")


class TextCommandResponse(BaseModel):
    """Response from text command processing."""
    status: str
    action: str
    match_id: Optional[int] = None
    table: Optional[str] = None
    message: str


# ============================================================================
# Voice Command Schemas
# ============================================================================

class VoiceCommandRequest(BaseModel):
    """Request to process a voice command (transcribed text)."""
    text: str = Field(..., description="Transcribed voice command text")
    tournament_id: Optional[int] = None


class VoiceCommandResponse(BaseModel):
    """Response from voice command processing."""
    status: str
    action: str
    match_id: Optional[int] = None
    table: Optional[str] = None
    message: str
    confidence: Optional[float] = None