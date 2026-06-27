"""
Pydantic schemas for API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


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
