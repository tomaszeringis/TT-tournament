from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PointEvent:
    match_id: Optional[int]
    game_index: int
    point_index: int
    scorer_side: str
    player_a_id: Optional[int]
    player_b_id: Optional[int]
    score_a_before: int
    score_b_before: int
    score_a_after: int
    score_b_after: int
    games_a_before: int
    games_b_before: int
    games_a_after: int
    games_b_after: int
    game_target: int
    best_of: int
    win_by: int = 2
    is_game_winning_point: bool = False
    is_match_winning_point: bool = False
    timestamp: Optional[float] = None
    source: str = "manual"
    server_id: Optional[str] = None
    rally_length: Optional[int] = None
    end_reason: Optional[str] = None
    shot_type: Optional[str] = None
    placement: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class WinProbabilityPoint:
    point_index: int
    probability_a: float
    probability_b: float
    score_a: int
    score_b: int
    game_target: int
    best_of: int


@dataclass
class DominationPoint:
    point_index: int
    score_domination: float
    momentum_domination: float
    pressure_domination: float
    global_domination: float


@dataclass
class AdvancedMatchInsight:
    match_id: Optional[int]
    player_a_name: str
    player_b_name: str
    win_probability_timeline: List[WinProbabilityPoint]
    domination_timeline: List[DominationPoint]
    pressure_summary: Dict[str, Any]
    momentum_summary: Dict[str, Any]
    shot_diversity_summary: Optional[Dict[str, Any]]
    global_domination: float
    domination_winner: str
    biggest_momentum_swing: float
    pressure_points_won_a: int
    total_pressure_points: int
    longest_run_player: str
    longest_run: int
    key_turning_points: List[str]
    narrative_summary: str
    warnings: List[str]
    pressure_point_indices: List[int] = field(default_factory=list)
