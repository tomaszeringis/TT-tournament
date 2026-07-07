"""
MatchManager - Score management for voice-activated tournament scorekeeper.

A simple, privacy-focused scorekeeping system using keyword matching
for intent parsing instead of complex AI reasoning.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional

from tournament_platform.services.voice_event_schema import (
    VoiceEvent,
    EventType,
    EventFactory,
)

try:
    from tournament_platform.app.services.voice_parser import VoiceScoreEvent
except ImportError:
    VoiceScoreEvent = None  # type: ignore


@dataclass
class MatchState:
    """
    Stores the scores for two players, the current set, and match history.

    Designed for table tennis scoring with extensibility for:
    - Deuce handling
    - Set changes
    - Game point detection
    """
    player_a: str = "Player A"
    player_b: str = "Player B"
    player_a_id: Optional[int] = None
    player_b_id: Optional[int] = None
    score_a: int = 0
    score_b: int = 0
    current_set: int = 1
    sets_a: int = 0
    sets_b: int = 0
    match_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "player_a": self.player_a,
            "player_b": self.player_b,
            "player_a_id": self.player_a_id,
            "player_b_id": self.player_b_id,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "current_set": self.current_set,
            "sets_a": self.sets_a,
            "sets_b": self.sets_b,
        }
    
    def get_score_string(self) -> str:
        """Get current score as a human-readable string."""
        return f"{self.score_a}-{self.score_b}"
    
    def get_full_score_string(self) -> str:
        """Get full match score including sets."""
        return f"Set {self.current_set}: {self.score_a}-{self.score_b} (Sets: {self.sets_a}-{self.sets_b})"


class MatchManager:
    """
    Manages match state with voice command processing.
    
    Uses keyword matching for intent parsing instead of complex AI reasoning.
    Supports commands like:
    - "Point to [Player Name]"
    - "Undo last point"
    - "What's the score?"
    """
    
    # Keywords for intent matching
    POINT_KEYWORDS = [
        "point", "scored", "scores", "score", "point for",
        "point to", "gets a point", "gets point", "won the point",
        "that's a point", "point for player"
    ]
    
    UNDO_KEYWORDS = [
        "undo", "take back", "remove point", "wrong", "incorrect",
        "that was wrong", "take that back"
    ]
    
    SCORE_KEYWORDS = [
        "what's the score", "whats the score", "what is the score",
        "score please", "current score", "tell me the score", "show score"
    ]
    
    def __init__(self, player_a: str = "Player A", player_b: str = "Player B", player_a_id: Optional[int] = None, player_b_id: Optional[int] = None):
        self.state = MatchState(player_a=player_a, player_b=player_b, player_a_id=player_a_id, player_b_id=player_b_id)
    
    def update_score(self, transcription: str) -> Tuple[bool, str]:
        """
        Parse transcription and update match state accordingly.
        
        Args:
            transcription: The transcribed text from voice input
            
        Returns:
            Tuple of (success, message) where message is for TTS feedback
        """
        text = transcription.lower().strip()
        
        # Check for undo command
        if any(kw in text for kw in self.UNDO_KEYWORDS):
            return self.undo_last_point()
        
        # Check for score query
        if any(kw in text for kw in self.SCORE_KEYWORDS):
            return True, f"Score is {self.state.score_a} to {self.state.score_b}"
        
        # Check for point commands
        player_a_name = self.state.player_a.lower()
        player_b_name = self.state.player_b.lower()
        
        # Check if point is for Player A
        if any(kw in text for kw in self.POINT_KEYWORDS):
            if player_a_name in text or "player a" in text:
                return self._add_point("A")
            elif player_b_name in text or "player b" in text:
                return self._add_point("B")
        
        # Check for just "player a" or "player b" with point context
        if "player a" in text:
            return self._add_point("A")
        if "player b" in text:
            return self._add_point("B")
        
        return False, "I didn't understand that command. Try saying 'Point to Player A' or 'What's the score?'"
    
    def _add_point(self, player: str) -> Tuple[bool, str]:
        """
        Add a point to the specified player.
        
        Args:
            player: "A" or "B"
            
        Returns:
            Tuple of (success, message)
        """
        # Save current state to history before modification
        self.state.match_history.append({
            "action": "point_added",
            "player": player,
            "previous_score_a": self.state.score_a,
            "previous_score_b": self.state.score_b,
            "previous_set": self.state.current_set,
            "previous_sets_a": self.state.sets_a,
            "previous_sets_b": self.state.sets_b,
        })
        
        if player == "A":
            self.state.score_a += 1
            player_name = self.state.player_a
        else:
            self.state.score_b += 1
            player_name = self.state.player_b
        
        # Check for game point (first to 11, win by 2)
        if self.state.score_a >= 11 or self.state.score_b >= 11:
            if abs(self.state.score_a - self.state.score_b) >= 2:
                # Game won - could extend for set handling
                pass
        
        return True, f"Point for {player_name}. Score is now {self.state.score_a} to {self.state.score_b}"
    
    def _set_score(self, score_a: int, score_b: int) -> Tuple[bool, str]:
        """
        Set the current game score directly.
        
        Args:
            score_a: New score for player A
            score_b: New score for player B
            
        Returns:
            Tuple of (success, message)
        """
        # Validate scores
        if score_a < 0 or score_b < 0:
            return False, "Scores cannot be negative"
        
        if score_a > 21 or score_b > 21:
            return False, "Score exceeds maximum (21)"
        
        # Save current state to history before modification
        self.state.match_history.append({
            "action": "score_set",
            "previous_score_a": self.state.score_a,
            "previous_score_b": self.state.score_b,
            "previous_set": self.state.current_set,
            "previous_sets_a": self.state.sets_a,
            "previous_sets_b": self.state.sets_b,
        })
        
        self.state.score_a = score_a
        self.state.score_b = score_b
        
        # Check for game completion
        self._check_game_completion()
        
        return True, f"Score set to {score_a}-{score_b}"
    
    def _check_game_completion(self) -> None:
        """
        Check if the current game is complete and update set scores if so.
        
        A game is won when a player reaches 11+ points with a 2-point lead.
        """
        score_a = self.state.score_a
        score_b = self.state.score_b
        
        if (score_a >= 11 or score_b >= 11) and abs(score_a - score_b) >= 2:
            # Game won
            if score_a > score_b:
                self.state.sets_a += 1
            else:
                self.state.sets_b += 1
            
            # Reset game score for next game
            self.state.score_a = 0
            self.state.score_b = 0
            self.state.current_set += 1
    
    def apply_voice_event(self, event: VoiceScoreEvent) -> Tuple[bool, str]:
        """
        Apply a parsed voice event to match state.
        
        Args:
            event: Structured voice score event from VoiceParser
            
        Returns:
            Tuple of (success, message)
        """
        if event.type == "set_score":
            if event.score_a is None or event.score_b is None:
                return False, "Invalid score event: missing scores"
            return self._set_score(event.score_a, event.score_b)
        
        elif event.type == "increment":
            if event.player is None:
                return False, "Invalid increment event: missing player"
            return self._add_point(event.player)
        
        elif event.type == "undo":
            return self.undo_last_point()
        
        else:
            return False, f"Unknown voice event type: {event.type}"
    
    def undo_last_point(self) -> Tuple[bool, str]:
        """
        Revert the last point change using match history.
        
        Returns:
            Tuple of (success, message)
        """
        if not self.state.match_history:
            return False, "No points to undo."
        
        last_action = self.state.match_history.pop()
        
        if last_action["action"] == "point_added":
            self.state.score_a = last_action["previous_score_a"]
            self.state.score_b = last_action["previous_score_b"]
            self.state.current_set = last_action["previous_set"]
            self.state.sets_a = last_action["previous_sets_a"]
            self.state.sets_b = last_action["previous_sets_b"]
            return True, f"Point undone. Score is now {self.state.score_a} to {self.state.score_b}"
        
        return False, "Cannot undo that action."
    
    def reset_match(self) -> Tuple[bool, str]:
        """
        Reset the match to initial state.
        
        Returns:
            Tuple of (success, message)
        """
        self.state = MatchState(
            player_a=self.state.player_a,
            player_b=self.state.player_b,
            player_a_id=self.state.player_a_id,
            player_b_id=self.state.player_b_id
        )
        return True, "Match reset. Score is 0 to 0"
    
    def set_player_names(self, player_a: str, player_b: str, player_a_id: Optional[int] = None, player_b_id: Optional[int] = None) -> None:
        """Set custom player names and optionally their database IDs."""
        self.state.player_a = player_a
        self.state.player_b = player_b
        self.state.player_a_id = player_a_id
        self.state.player_b_id = player_b_id

    # ------------------------------------------------------------------
    # Event generation methods
    # ------------------------------------------------------------------

    def generate_point_event(self, player: str, source_transcript: str) -> VoiceEvent:
        """
        Generate a VoiceEvent for a point won.

        Args:
            player: "A" or "B"
            source_transcript: Original voice transcript

        Returns:
            VoiceEvent for the point won
        """
        score_before = f"{self.state.score_a}-{self.state.score_b}"
        if player == "A":
            self.state.score_a += 1
        else:
            self.state.score_b += 1
        score_after = f"{self.state.score_a}-{self.state.score_b}"

        return EventFactory.create_point_event(
            player=self.state.player_a if player == "A" else self.state.player_b,
            score_before=score_before,
            score_after=score_after,
            source_transcript=source_transcript,
            match_id=None,
            tournament_id=None,
            opponent=self.state.player_b if player == "A" else self.state.player_a,
            game_number=self.state.current_set,
        )

    def generate_undo_event(self, source_transcript: str) -> Optional[VoiceEvent]:
        """
        Generate a VoiceEvent for undo.

        Args:
            source_transcript: Original voice transcript

        Returns:
            VoiceEvent for the undo, or None if no history
        """
        if not self.state.match_history:
            return None

        score_before = f"{self.state.score_a}-{self.state.score_b}"
        return EventFactory.create_undo_event(
            score_before=score_before,
            score_after="0-0",
            source_transcript=source_transcript,
        )

    def generate_reset_event(self, source_transcript: str) -> VoiceEvent:
        """
        Generate a VoiceEvent for reset.

        Args:
            source_transcript: Original voice transcript

        Returns:
            VoiceEvent for the reset
        """
        return EventFactory.create_reset_event(
            source_transcript=source_transcript,
        )

    def generate_score_query_event(self, source_transcript: str) -> VoiceEvent:
        """
        Generate a VoiceEvent for score query.

        Args:
            source_transcript: Original voice transcript

        Returns:
            VoiceEvent for the score query
        """
        return EventFactory.create_score_query_event(
            score=f"{self.state.score_a}-{self.state.score_b}",
            source_transcript=source_transcript,
        )

    def generate_match_result_event(
        self,
        player_a: str,
        player_b: str,
        winner: str,
        score: str,
        source_transcript: str,
    ) -> VoiceEvent:
        """
        Generate a VoiceEvent for match result.

        Args:
            player_a: First player name
            player_b: Second player name
            winner: Winner player name
            score: Match score (e.g., "3-1")
            source_transcript: Original voice transcript

        Returns:
            VoiceEvent for the match result
        """
        return EventFactory.create_match_result_event(
            player_a=player_a,
            player_b=player_b,
            winner=winner,
            score=score,
            source_transcript=source_transcript,
        )

    def parse_match_result(self, transcript: str) -> Optional[Dict[str, Any]]:
        """
        Parse a match result from transcript (e.g., "Alice beat Bob 3-1").

        Args:
            transcript: The voice transcript

        Returns:
            Dict with player_a, player_b, winner, score or None if not parseable
        """
        patterns = [
            r"(?P<a>\w+)\s+beat\s+(?P<b>\w+)\s+(?P<score>\d+\s*[-–]\s*\d+)",
            r"(?P<a>\w+)\s+defeated\s+(?P<b>\w+)\s+(?P<score>\d+\s*[-–]\s*\d+)",
            r"(?P<a>\w+)\s+wins\s+over\s+(?P<b>\w+)\s+(?P<score>\d+\s*[-–]\s*\d+)",
            r"(?P<b>\w+)\s+lost\s+to\s+(?P<a>\w+)\s+(?P<score>\d+\s*[-–]\s*\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, transcript, re.IGNORECASE)
            if match:
                return {
                    "player_a": match.group("a"),
                    "player_b": match.group("b"),
                    "winner": match.group("a"),
                    "score": match.group("score").replace(" ", ""),
                }

        return None