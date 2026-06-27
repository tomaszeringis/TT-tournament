"""
Pydantic schemas for API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class MatchResultParseRequest(BaseModel):
    """Request body for parsing a match result from natural language text."""
    text: str = Field(..., description="Natural language transcript describing the match result")
    tournament_id: Optional[int] = Field(None, description="Optional tournament ID for context")
    match_id: Optional[int] = Field(None, description="Optional match ID for context")


class MatchResultParseResponse(BaseModel):
    """Structured response from match result parsing."""
    status: str = Field(
        ...,
        description="Parse status: 'success', 'needs_review', or 'error'"
    )
    transcript: str = Field(..., description="The original transcript text")
    player1: Optional[str] = Field(None, description="First player name")
    player2: Optional[str] = Field(None, description="Second player name")
    winner: Optional[str] = Field(None, description="Winner name (must be player1 or player2)")
    score: Optional[str] = Field(None, description="Normalized score string like '3-1'")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0 to 1"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="List of warnings about ambiguous or uncertain parsing"
    )
    raw: Optional[Dict[str, Any]] = Field(
        None,
        description="Raw parsed data for debugging"
    )


class LeaderboardEntry(BaseModel):
    """Single entry in the ratings leaderboard."""
    player_id: int = Field(..., description="Player ID")
    name: str = Field(..., description="Player name")
    rating: int = Field(..., description="Current rating")
    matches_played: int = Field(..., description="Total matches played")
    wins: int = Field(..., description="Total wins")
    losses: int = Field(..., description="Total losses")
    last_rating_change: Optional[int] = Field(None, description="Most recent rating change from history")


class RatingHistoryEntry(BaseModel):
    """Single rating history entry."""
    id: int
    rating: int
    timestamp: str


class PreviewMatchRequest(BaseModel):
    """Request to preview the rating impact of a potential match."""
    player1_id: int = Field(..., description="ID of the first player")
    player2_id: int = Field(..., description="ID of the second player")
    winner_id: Optional[int] = Field(None, description="Optional predicted winner ID")


class PreviewMatchResponse(BaseModel):
    """Response with rating preview and upset analysis."""
    player1_id: int
    player2_id: int
    player1_rating: int
    player2_rating: int
    rating_difference: int
    expected_favorite: int
    upset_possible: bool
    explanation: str
    predicted_rating_changes: Optional[Dict[str, int]] = None


class ActiveMatchResponse(BaseModel):
    """Single active/pending match for scorekeeper selection."""
    match_id: int
    player1_id: Optional[int] = None
    player1_name: Optional[str] = None
    player2_id: Optional[int] = None
    player2_name: Optional[str] = None
    status: str
    round_number: Optional[int] = None
    bracket_index: Optional[int] = None
    scheduled_time: Optional[str] = None
    location: Optional[str] = None
    score: Optional[str] = None
    incomplete: bool = False


class ActiveTournamentMatchesResponse(BaseModel):
    """Response for active tournament matches endpoint."""
    tournament_id: int
    tournament_name: str
    matches: List[ActiveMatchResponse] = []
