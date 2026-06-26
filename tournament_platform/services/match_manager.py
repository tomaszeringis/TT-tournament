"""
MatchManager - Score management for voice-activated tournament scorekeeper.

A simple, privacy-focused scorekeeping system using keyword matching
for intent parsing instead of complex AI reasoning.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple


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
    
    def __init__(self, player_a: str = "Player A", player_b: str = "Player B"):
        self.state = MatchState(player_a=player_a, player_b=player_b)
    
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
            player_b=self.state.player_b
        )
        return True, "Match reset. Score is 0 to 0"
    
    def set_player_names(self, player_a: str, player_b: str) -> None:
        """Set custom player names."""
        self.state.player_a = player_a
        self.state.player_b = player_b