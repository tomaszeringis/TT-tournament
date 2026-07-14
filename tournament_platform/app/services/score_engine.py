"""
Score Engine - Pure table tennis scoring rules.

This module is intentionally free of Streamlit and database imports so it can be
unit-tested in isolation and used as the single source of truth for scoring.

Concepts are ported from the PingScore reference (serve switching, deuce/advantage,
configurable points-to-win, best-of-N match progression, and full-state undo). No
PingScore source code is copied verbatim; this is a clean Python reimplementation.

State model
-----------
``MatchState`` holds the full active-match state. All mutating functions take a
``MatchState`` instance, snapshot the pre-action state into ``history`` (for undo),
apply the change, and return a ``ScoreResult`` describing what happened.

Manual scoring (buttons) and voice scoring both call the same functions here, so
rules stay centralized and consistent.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Supported configuration values (mirrors PingScore's format options).
VALID_POINTS_TO_WIN = (11, 15, 21)
VALID_BEST_OF = (1, 3, 5)

BEST_OF_TO_GAMES_TO_WIN = {3: 2, 5: 3}
GAMES_TO_WIN_TO_BEST_OF = {2: 3, 3: 5}


def best_of_to_games_to_win(best_of: int) -> int:
    """Convert a best-of-N value to the games needed to win the match."""
    return BEST_OF_TO_GAMES_TO_WIN.get(best_of, 2)


def games_to_win_to_best_of(games_to_win: int) -> int:
    """Convert a games-to-win value back to best-of-N."""
    return GAMES_TO_WIN_TO_BEST_OF.get(games_to_win, 3)


def _other(player: str) -> str:
    """Return the opponent of the given player label ('A' or 'B')."""
    return "B" if player == "A" else "A"


@dataclass
class MatchState:
    """Full active-match state for a two-player table tennis match."""

    player_a_name: str = "Player A"
    player_b_name: str = "Player B"
    player_a_id: Optional[int] = None
    player_b_id: Optional[int] = None

    score_a: int = 0
    score_b: int = 0

    games_won_a: int = 0
    games_won_b: int = 0
    round_scores: List[Tuple[int, int]] = field(default_factory=list)

    serving_player: str = "A"          # "A" or "B" - who serves the next point
    first_server: str = "A"            # chosen at setup; server of game 1
    game_first_server: str = "A"       # server at the start of the current game
    points_played_this_game: int = 0

    points_to_win: int = 11            # 11 | 15 | 21
    best_of: int = 5                    # 1 | 3 | 5

    history: List[Dict] = field(default_factory=list)

    match_status: str = "in_progress"  # in_progress | game_won | match_won
    last_event: Optional[str] = None
    last_updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        """Serialize state to a plain dict (for persistence/debugging)."""
        return {
            "player_a_name": self.player_a_name,
            "player_b_name": self.player_b_name,
            "player_a_id": self.player_a_id,
            "player_b_id": self.player_b_id,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "games_won_a": self.games_won_a,
            "games_won_b": self.games_won_b,
            "round_scores": list(self.round_scores),
            "serving_player": self.serving_player,
            "first_server": self.first_server,
            "game_first_server": self.game_first_server,
            "points_played_this_game": self.points_played_this_game,
            "points_to_win": self.points_to_win,
            "best_of": self.best_of,
            "match_status": self.match_status,
            "last_event": self.last_event,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MatchState":
        """Rebuild a MatchState from a dict produced by ``to_dict``."""
        return cls(
            player_a_name=data.get("player_a_name", "Player A"),
            player_b_name=data.get("player_b_name", "Player B"),
            player_a_id=data.get("player_a_id"),
            player_b_id=data.get("player_b_id"),
            score_a=data.get("score_a", 0),
            score_b=data.get("score_b", 0),
            games_won_a=data.get("games_won_a", 0),
            games_won_b=data.get("games_won_b", 0),
            round_scores=list(data.get("round_scores", [])),
            serving_player=data.get("serving_player", "A"),
            first_server=data.get("first_server", "A"),
            game_first_server=data.get("game_first_server", data.get("first_server", "A")),
            points_played_this_game=data.get("points_played_this_game", 0),
            points_to_win=data.get("points_to_win", 11),
            best_of=data.get("best_of", 5),
            match_status=data.get("match_status", "in_progress"),
            last_event=data.get("last_event"),
            last_updated_at=data.get("last_updated_at", time.time()),
        )

    def get_score_string(self) -> str:
        """Human-readable current game score, e.g. '5-4'."""
        return f"{self.score_a}-{self.score_b}"

    def get_full_score_string(self) -> str:
        """Human-readable match score including games won."""
        return (
            f"Game: {self.score_a}-{self.score_b} "
            f"(Games: {self.games_won_a}-{self.games_won_b})"
        )


@dataclass
class ScoreResult:
    """Outcome of a scoring action, used for UI feedback and tests."""

    ok: bool = True
    message: str = ""
    point_added: Optional[str] = None          # "A" | "B"
    score_set: Optional[Tuple[int, int]] = None
    serve_switched: bool = False
    deuce: bool = False
    game_won: Optional[str] = None             # "A" | "B"
    match_won: Optional[str] = None            # "A" | "B"
    rejected_reason: Optional[str] = None


def create_match(
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
    player_a_id: Optional[int] = None,
    player_b_id: Optional[int] = None,
    points_to_win: int = 11,
    best_of: int = 5,
    first_server: str = "A",
) -> MatchState:
    """Build a validated ``MatchState`` for a new match."""
    if points_to_win not in VALID_POINTS_TO_WIN:
        raise ValueError(f"points_to_win must be one of {VALID_POINTS_TO_WIN}")
    if best_of not in VALID_BEST_OF:
        raise ValueError(f"best_of must be one of {VALID_BEST_OF}")
    if first_server not in ("A", "B"):
        raise ValueError("first_server must be 'A' or 'B'")
    return MatchState(
        player_a_name=player_a_name,
        player_b_name=player_b_name,
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        points_to_win=points_to_win,
        best_of=best_of,
        first_server=first_server,
        game_first_server=first_server,
        serving_player=first_server,
    )


# ---------------------------------------------------------------------------
# Rule helpers (pure, no mutation)
# ---------------------------------------------------------------------------

def is_deuce(state: MatchState) -> bool:
    """True when both players are at/above (points_to_win - 1) and within 1 point.

    Examples for first-to-11: 10-10, 11-10, 12-11 are deuce; 9-9 and 11-9 are not.
    """
    return (
        state.score_a >= state.points_to_win - 1
        and state.score_b >= state.points_to_win - 1
        and abs(state.score_a - state.score_b) <= 1
    )


def should_switch_serve(state: MatchState) -> bool:
    """Whether the server should change after the most recent point.

    - Before deuce: serve changes every 2 total points.
    - During deuce: serve changes every point.
    - At 0 points played (before the first point) no switch is due.
    """
    if is_deuce(state):
        return True
    return state.points_played_this_game > 0 and state.points_played_this_game % 2 == 0


def get_serving_player(state: MatchState) -> str:
    """Return the label ('A'/'B') of the player who serves next."""
    return state.serving_player


def check_game_winner(state: MatchState) -> Optional[str]:
    """Return 'A' or 'B' if the current game is won, else None.

    A game is won when a player reaches ``points_to_win`` with a lead of at least 2.
    """
    a, b = state.score_a, state.score_b
    if a >= state.points_to_win and (a - b) >= 2:
        return "A"
    if b >= state.points_to_win and (b - a) >= 2:
        return "B"
    return None


def check_match_winner(state: MatchState) -> Optional[str]:
    """Return 'A' or 'B' if the match is won (majority of best-of-N games), else None."""
    needed = state.best_of // 2 + 1
    if state.games_won_a >= needed:
        return "A"
    if state.games_won_b >= needed:
        return "B"
    return None


# ---------------------------------------------------------------------------
# Internal snapshot / restore (for undo)
# ---------------------------------------------------------------------------

def _snapshot(state: MatchState) -> Dict:
    """Capture a full, restorable copy of the mutable state fields."""
    return {
        "player_a_name": state.player_a_name,
        "player_b_name": state.player_b_name,
        "player_a_id": state.player_a_id,
        "player_b_id": state.player_b_id,
        "score_a": state.score_a,
        "score_b": state.score_b,
        "games_won_a": state.games_won_a,
        "games_won_b": state.games_won_b,
        "round_scores": list(state.round_scores),
        "serving_player": state.serving_player,
        "first_server": state.first_server,
        "game_first_server": state.game_first_server,
        "points_played_this_game": state.points_played_this_game,
        "points_to_win": state.points_to_win,
        "best_of": state.best_of,
        "match_status": state.match_status,
        "last_event": state.last_event,
    }


def _restore(state: MatchState, snap: Dict) -> None:
    """Restore state fields from a snapshot produced by ``_snapshot``."""
    state.player_a_name = snap["player_a_name"]
    state.player_b_name = snap["player_b_name"]
    state.player_a_id = snap["player_a_id"]
    state.player_b_id = snap["player_b_id"]
    state.score_a = snap["score_a"]
    state.score_b = snap["score_b"]
    state.games_won_a = snap["games_won_a"]
    state.games_won_b = snap["games_won_b"]
    state.round_scores = list(snap["round_scores"])
    state.serving_player = snap["serving_player"]
    state.first_server = snap["first_server"]
    state.game_first_server = snap["game_first_server"]
    state.points_played_this_game = snap["points_played_this_game"]
    state.points_to_win = snap["points_to_win"]
    state.best_of = snap["best_of"]
    state.match_status = snap["match_status"]
    state.last_event = snap["last_event"]


def _recompute_server(state: MatchState) -> None:
    """Recompute ``serving_player`` from ``first_server`` and total points played.

    Used by ``set_score`` where incremental serve tracking is unavailable. This is
    a deterministic approximation: pre-deuce switches every 2 points; during deuce
    switches every point.
    """
    total = state.points_played_this_game
    if is_deuce(state):
        state.serving_player = (
            state.first_server if total % 2 == 0 else _other(state.first_server)
        )
    else:
        switches = total // 2
        state.serving_player = (
            state.first_server if switches % 2 == 0 else _other(state.first_server)
        )


# ---------------------------------------------------------------------------
# Mutating actions
# ---------------------------------------------------------------------------

def add_point(state: MatchState, player: str) -> ScoreResult:
    """Add a point to ``player`` ('A' or 'B') and apply all rules.

    Pushes a snapshot for undo, updates score/serve, detects deuce and game/match
    completion. Returns a ``ScoreResult`` describing the outcome.
    """
    if state.match_status == "match_won":
        return ScoreResult(ok=False, rejected_reason="Match already decided")
    if player not in ("A", "B"):
        return ScoreResult(ok=False, rejected_reason="Invalid player")

    was_new_game = state.points_played_this_game == 0
    state.history.append(_snapshot(state))

    if player == "A":
        state.score_a += 1
    else:
        state.score_b += 1
    state.points_played_this_game += 1

    # Record the first server of this game (used to pick the next game's server).
    if was_new_game:
        state.game_first_server = state.serving_player

    result = ScoreResult(ok=True, point_added=player)

    if should_switch_serve(state):
        state.serving_player = _other(state.serving_player)
        result.serve_switched = True

    result.deuce = is_deuce(state)

    winner = check_game_winner(state)
    if winner:
        complete_game(state, winner)
        result.game_won = winner
        match_winner = check_match_winner(state)
        if match_winner:
            state.match_status = "match_won"
            result.match_won = match_winner
    else:
        # Continuing play (possibly into the next game after a game was won).
        if state.match_status == "game_won":
            state.match_status = "in_progress"

    state.last_event = f"point_{player}"
    state.last_updated_at = time.time()
    return result


def set_score(
    state: MatchState,
    score_a: int,
    score_b: int,
    explicit: bool = False,
) -> ScoreResult:
    """Set the visible current-game score directly (e.g. spoken 'five four').

    Validates bounds, snapshots for undo, recomputes the server from total points,
    and applies game/match completion if the new score ends a game.
    """
    if state.match_status == "match_won":
        return ScoreResult(ok=False, rejected_reason="Match already decided")
    if score_a < 0 or score_b < 0:
        return ScoreResult(ok=False, rejected_reason="Scores cannot be negative")

    max_score = state.points_to_win + 20
    if score_a > max_score or score_b > max_score:
        return ScoreResult(
            ok=False, rejected_reason=f"Score exceeds maximum ({max_score})"
        )

    state.history.append(_snapshot(state))

    state.score_a = score_a
    state.score_b = score_b
    state.points_played_this_game = score_a + score_b
    _recompute_server(state)
    state.game_first_server = state.serving_player

    result = ScoreResult(ok=True, score_set=(score_a, score_b))

    winner = check_game_winner(state)
    if winner:
        complete_game(state, winner)
        result.game_won = winner
        match_winner = check_match_winner(state)
        if match_winner:
            state.match_status = "match_won"
            result.match_won = match_winner
    else:
        if state.match_status == "game_won":
            state.match_status = "in_progress"

    result.deuce = is_deuce(state)
    state.last_event = "set_score"
    state.last_updated_at = time.time()
    return result


def complete_game(state: MatchState, winner: str) -> None:
    """Record a completed game, reset the game score, and prepare the next game.

    Appends the finished game to ``round_scores``, increments the winner's game
    count, resets scores/point counter, and sets the next game's server to the
    receiver of the game that just finished.
    """
    state.round_scores.append((state.score_a, state.score_b))
    if winner == "A":
        state.games_won_a += 1
    else:
        state.games_won_b += 1
    state.score_a = 0
    state.score_b = 0
    state.points_played_this_game = 0
    # Next game: the receiver of this game becomes the server.
    state.serving_player = _other(state.game_first_server)
    state.match_status = "game_won"


def undo_last_action(state: MatchState) -> ScoreResult:
    """Revert the most recent action, restoring the full previous state."""
    if not state.history:
        return ScoreResult(ok=False, rejected_reason="No actions to undo")
    snap = state.history.pop()
    _restore(state, snap)
    state.last_event = "undo"
    state.last_updated_at = time.time()
    return ScoreResult(ok=True, message="Undo")


def reset_match(state: MatchState) -> ScoreResult:
    """Reset the match to its initial state, keeping names/ids/formats."""
    state.score_a = 0
    state.score_b = 0
    state.games_won_a = 0
    state.games_won_b = 0
    state.round_scores = []
    state.serving_player = state.first_server
    state.game_first_server = state.first_server
    state.points_played_this_game = 0
    state.history = []
    state.match_status = "in_progress"
    state.last_event = "reset"
    state.last_updated_at = time.time()
    return ScoreResult(ok=True, message="Match reset")


def rematch(state: MatchState) -> ScoreResult:
    """Reset for a rematch, swapping the first server."""
    state.first_server = _other(state.first_server)
    return reset_match(state)
