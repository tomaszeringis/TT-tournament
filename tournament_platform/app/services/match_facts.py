"""
MatchFacts dataclass — the single immutable source of truth for recap generation.

Every recap is generated from ``MatchFacts``. No other data is allowed as input.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class MatchFacts:
    match_id: int
    tournament_id: int
    player_a: str
    player_b: str
    winner: str
    final_score: str
    game_scores: List[str]
    completed_at: Optional[datetime]
    player_a_rating: Optional[int] = None
    player_b_rating: Optional[int] = None
    tags: List[str] = field(default_factory=list)

    def loser_name(self) -> str:
        return self.player_b if self.winner == self.player_a else self.player_a
