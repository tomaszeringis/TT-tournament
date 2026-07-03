"""
Voice Event Schema - Normalized events for table-tennis voice scorekeeping.

Provides a structured, Pydantic-based schema for voice events that can be
consumed by the commentary service and other downstream systems.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict


class EventType(str, Enum):
    """Types of events for table-tennis voice scorekeeping."""
    POINT_WON = "point_won"
    GAME_WON = "game_won"
    MATCH_SUBMITTED = "match_submitted"
    UNDO = "undo"
    RESET = "reset"
    SERVER_CHANGE = "server_change"
    DEUCE = "deuce"
    GAME_POINT = "game_point"
    MATCH_POINT = "match_point"
    SCORE_QUERY = "score_query"
    MATCH_RESULT = "match_result"


class VoiceEvent(BaseModel):
    """
    A normalized event from voice input for table-tennis scoring.
    
    This schema provides a structured representation of voice commands
    that can be used by commentary, match reporting, and other services.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    match_id: Optional[int] = None
    tournament_id: Optional[int] = None
    player: Optional[str] = None
    opponent: Optional[str] = None
    score_before: str = "0-0"
    score_after: str = "0-0"
    game_number: int = 1
    confidence: float = 0.0
    source_transcript: str = ""
    entities: Dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    action: Optional[str] = None  # For undo/reset actions
    server: Optional[str] = None  # For server change events
    sets: Optional[str] = None  # For game/match won events

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "event_type": "point_won",
                "timestamp": "2024-01-15T10:30:00.000Z",
                "match_id": 123,
                "tournament_id": 1,
                "player": "Alice",
                "opponent": "Bob",
                "score_before": "5-3",
                "score_after": "6-3",
                "game_number": 1,
                "confidence": 0.95,
                "source_transcript": "Point to Alice",
                "entities": {"player": "Alice", "score": "6-3"},
                "requires_confirmation": False,
                "action": None,
                "server": None,
                "sets": None
            }
        }
    )


class EventFactory:
    """
    Factory for creating VoiceEvent instances from various sources.
    """
    
    @staticmethod
    def create_point_event(
        player: str,
        score_before: str,
        score_after: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
        opponent: Optional[str] = None,
        game_number: int = 1,
        entities: Optional[Dict[str, Any]] = None,
    ) -> VoiceEvent:
        """Create a point_won event."""
        return VoiceEvent(
            event_type=EventType.POINT_WON,
            match_id=match_id,
            tournament_id=tournament_id,
            player=player,
            opponent=opponent,
            score_before=score_before,
            score_after=score_after,
            game_number=game_number,
            confidence=confidence,
            source_transcript=source_transcript,
            entities=entities or {"player": player, "score": score_after},
        )
    
    @staticmethod
    def create_undo_event(
        score_before: str,
        score_after: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create an undo event."""
        return VoiceEvent(
            event_type=EventType.UNDO,
            match_id=match_id,
            tournament_id=tournament_id,
            score_before=score_before,
            score_after=score_after,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"action": "undo"},
        )
    
    @staticmethod
    def create_reset_event(
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create a reset event."""
        return VoiceEvent(
            event_type=EventType.RESET,
            match_id=match_id,
            tournament_id=tournament_id,
            score_after="0-0",
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"action": "reset"},
        )
    
    @staticmethod
    def create_score_query_event(
        score: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create a score_query event."""
        return VoiceEvent(
            event_type=EventType.SCORE_QUERY,
            match_id=match_id,
            tournament_id=tournament_id,
            score_after=score,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"score": score},
        )
    
    @staticmethod
    def create_match_result_event(
        player_a: str,
        player_b: str,
        winner: str,
        score: str,
        source_transcript: str,
        confidence: float = 0.9,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
        requires_confirmation: bool = True,
    ) -> VoiceEvent:
        """Create a match_result event."""
        return VoiceEvent(
            event_type=EventType.MATCH_RESULT,
            match_id=match_id,
            tournament_id=tournament_id,
            player=player_a,
            opponent=player_b,
            score_after=score,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={
                "player_a": player_a,
                "player_b": player_b,
                "winner": winner,
                "score": score,
            },
            requires_confirmation=requires_confirmation,
        )
    
    @staticmethod
    def create_server_change_event(
        server: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create a server_change event."""
        return VoiceEvent(
            event_type=EventType.SERVER_CHANGE,
            match_id=match_id,
            tournament_id=tournament_id,
            player=server,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"server": server},
        )
    
    @staticmethod
    def create_deuce_event(
        score: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create a deuce event."""
        return VoiceEvent(
            event_type=EventType.DEUCE,
            match_id=match_id,
            tournament_id=tournament_id,
            score_after=score,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"score": score},
        )
    
    @staticmethod
    def create_game_point_event(
        player: str,
        score: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create a game_point event."""
        return VoiceEvent(
            event_type=EventType.GAME_POINT,
            match_id=match_id,
            tournament_id=tournament_id,
            player=player,
            score_after=score,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"player": player, "score": score},
        )
    
    @staticmethod
    def create_game_won_event(
        winner: str,
        score: str,
        sets: str,
        source_transcript: str,
        confidence: float = 1.0,
        match_id: Optional[int] = None,
        tournament_id: Optional[int] = None,
    ) -> VoiceEvent:
        """Create a game_won event."""
        return VoiceEvent(
            event_type=EventType.GAME_WON,
            match_id=match_id,
            tournament_id=tournament_id,
            player=winner,
            score_after=score,
            confidence=confidence,
            source_transcript=source_transcript,
            entities={"winner": winner, "score": score, "sets": sets},
        )