"""
Commentary Service — deterministic spoken commentary for the Voice Scorekeeper.

Generates short, natural commentary lines for table-tennis score events
using hand-written templates. No LLM required. No network calls.
"""

import copy
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================================
# Enums
# ============================================================================

class ScoreMoment(str, Enum):
    POINT_A = "point_a"
    POINT_B = "point_b"
    UNDO = "undo"
    DEUCE = "deuce"
    ADVANTAGE_A = "advantage_a"
    ADVANTAGE_B = "advantage_b"
    GAME_POINT_A = "game_point_a"
    GAME_POINT_B = "game_point_b"
    GAME_WON_A = "game_won_a"
    GAME_WON_B = "game_won_b"
    MATCH_WON_A = "match_won_a"
    MATCH_WON_B = "match_won_b"
    INVALID = "invalid"
    RESET = "reset"
    MATCH_SUBMITTED = "match_submitted"
    STREAK_A = "streak_a"
    STREAK_B = "streak_b"
    COMEBACK_A = "comeback_a"
    COMEBACK_B = "comeback_b"


class CommentaryStyle(str, Enum):
    NEUTRAL = "neutral"
    COACH = "coach"
    ANNOUNCER = "announcer"
    MINIMAL = "minimal"
    KIDS = "kids"
    SILENT = "silent"


class CommentaryVerbosity(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    EXPRESSIVE = "expressive"
    SILENT = "silent"


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class SpokenScoreState:
    """Lightweight snapshot of score state for commentary generation."""
    score_a: int
    score_b: int
    sets_a: int
    sets_b: int
    current_set: int
    player_a: str
    player_b: str
    player_a_id: Optional[int]
    player_b_id: Optional[int]
    match_history: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_match_state(cls, state: Any) -> "SpokenScoreState":
        """Create from a MatchState-like object."""
        return cls(
            score_a=state.score_a,
            score_b=state.score_b,
            sets_a=state.sets_a,
            sets_b=state.sets_b,
            current_set=state.current_set,
            player_a=state.player_a,
            player_b=state.player_b,
            player_a_id=state.player_a_id,
            player_b_id=state.player_b_id,
            match_history=list(getattr(state, "match_history", [])),
        )


@dataclass
class CommentaryLine:
    """A single commentary line ready for TTS."""
    text: str
    event_type: str
    priority: int  # 1=low, 2=normal, 3=high
    should_speak: bool
    dedupe_key: str
    event_id: str
    ssml_text: Optional[str] = None


@dataclass
class CommentarySettings:
    """User preferences for spoken commentary."""
    enabled: bool = False
    style: CommentaryStyle = CommentaryStyle.NEUTRAL
    verbosity: CommentaryVerbosity = CommentaryVerbosity.STANDARD
    voice: str = "default"
    language: str = "en"
    muted: bool = False


# ============================================================================
# Commentary Service
# ============================================================================

class CommentaryService:
    """
    Deterministic commentary generator for table-tennis scorekeeping.

    Uses hand-written templates. No LLM. No network calls.
    """

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    TEMPLATES: Dict[tuple, List[str]] = {
        # --- Point events ---
        (ScoreMoment.POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Point to {player_a}. {score}.",
            "{player_a} scores. {score}.",
        ],
        (ScoreMoment.POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Point to {player_b}. {score}.",
            "{player_b} scores. {score}.",
        ],
        (ScoreMoment.POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.MINIMAL): [],
        (ScoreMoment.POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.MINIMAL): [],
        (ScoreMoment.POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Point to {player_a}. {score}. Nice shot.",
            "{player_a} with the point. {score}. Keep it going.",
        ],
        (ScoreMoment.POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Point to {player_b}. {score}. Nice shot.",
            "{player_b} with the point. {score}. Keep it going.",
        ],
        # --- Undo ---
        (ScoreMoment.UNDO, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Point removed. {score}.",
            "Undo. Score is {score}.",
        ],
        (ScoreMoment.UNDO, CommentaryStyle.NEUTRAL, CommentaryVerbosity.MINIMAL): [],
        # --- Deuce ---
        (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.MINIMAL): [
            "Deuce.",
        ],
        (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Deuce. {score}.",
        ],
        (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Deuce! {score}. Exciting finish.",
        ],
        # --- Advantage ---
        (ScoreMoment.ADVANTAGE_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Advantage {player_a}.",
        ],
        (ScoreMoment.ADVANTAGE_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Advantage {player_b}.",
        ],
        (ScoreMoment.ADVANTAGE_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Advantage {player_a}. One point away.",
        ],
        (ScoreMoment.ADVANTAGE_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Advantage {player_b}. One point away.",
        ],
        # --- Game point ---
        (ScoreMoment.GAME_POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Game point, {player_a}. {score}.",
        ],
        (ScoreMoment.GAME_POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Game point, {player_b}. {score}.",
        ],
        (ScoreMoment.GAME_POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Game point, {player_a}. {score}. Close it out.",
        ],
        (ScoreMoment.GAME_POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Game point, {player_b}. {score}. Close it out.",
        ],
        # --- Game won ---
        (ScoreMoment.GAME_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Game to {player_a}, {score}.",
        ],
        (ScoreMoment.GAME_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Game to {player_b}, {score}.",
        ],
        (ScoreMoment.GAME_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Game to {player_a}, {score}. Well played.",
        ],
        (ScoreMoment.GAME_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Game to {player_b}, {score}. Well played.",
        ],
        # --- Match won ---
        (ScoreMoment.MATCH_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Match complete. {player_a} wins {sets_a} games to {sets_b}.",
        ],
        (ScoreMoment.MATCH_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Match complete. {player_b} wins {sets_b} games to {sets_a}.",
        ],
        (ScoreMoment.MATCH_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Match complete. {player_a} wins {sets_a} games to {sets_b}. Congratulations.",
        ],
        (ScoreMoment.MATCH_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): [
            "Match complete. {player_b} wins {sets_b} games to {sets_a}. Congratulations.",
        ],
        # --- Reset ---
        (ScoreMoment.RESET, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Match reset. Score is 0 to 0.",
        ],
        # --- Invalid ---
        (ScoreMoment.INVALID, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Invalid score.",
        ],
        # --- Match submitted ---
        (ScoreMoment.MATCH_SUBMITTED, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "Match result submitted.",
        ],
        # --- Streak ---
        (ScoreMoment.STREAK_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "{player_a} on a hot streak. {score}.",
        ],
        (ScoreMoment.STREAK_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "{player_b} on a hot streak. {score}.",
        ],
        # --- Comeback ---
        (ScoreMoment.COMEBACK_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "What a comeback by {player_a}! {score}.",
        ],
        (ScoreMoment.COMEBACK_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
            "What a comeback by {player_b}! {score}.",
        ],
    }

    # Coach-style overrides
    COACH_TEMPLATES: Dict[tuple, List[str]] = {
        (ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD): [
            "Good point, {player_a}. {score}.",
            "Nice one, {player_a}. {score}.",
        ],
        (ScoreMoment.POINT_B, CommentaryVerbosity.STANDARD): [
            "Good point, {player_b}. {score}.",
            "Nice one, {player_b}. {score}.",
        ],
        (ScoreMoment.GAME_POINT_A, CommentaryVerbosity.STANDARD): [
            "Game point, {player_a}. Stay focused. {score}.",
        ],
        (ScoreMoment.GAME_POINT_B, CommentaryVerbosity.STANDARD): [
            "Game point, {player_b}. Stay focused. {score}.",
        ],
        (ScoreMoment.GAME_WON_A, CommentaryVerbosity.STANDARD): [
            "Game to {player_a}, {score}. Great game.",
        ],
        (ScoreMoment.GAME_WON_B, CommentaryVerbosity.STANDARD): [
            "Game to {player_b}, {score}. Great game.",
        ],
        (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.STANDARD): [
            "Match to {player_a}, {sets_a} to {sets_b}. Outstanding.",
        ],
        (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.STANDARD): [
            "Match to {player_b}, {sets_b} to {sets_a}. Outstanding.",
        ],
    }

    # Announcer-style overrides
    ANNOUNCER_TEMPLATES: Dict[tuple, List[str]] = {
        (ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD): [
            "And {player_a} takes the point! {score}.",
        ],
        (ScoreMoment.POINT_B, CommentaryVerbosity.STANDARD): [
            "And {player_b} takes the point! {score}.",
        ],
        (ScoreMoment.DEUCE, CommentaryVerbosity.STANDARD): [
            "Deuce! {score}. The crowd is on their feet.",
        ],
        (ScoreMoment.ADVANTAGE_A, CommentaryVerbosity.STANDARD): [
            "Advantage {player_a}! {score}.",
        ],
        (ScoreMoment.ADVANTAGE_B, CommentaryVerbosity.STANDARD): [
            "Advantage {player_b}! {score}.",
        ],
        (ScoreMoment.GAME_POINT_A, CommentaryVerbosity.STANDARD): [
            "Game point {player_a}! {score}.",
        ],
        (ScoreMoment.GAME_POINT_B, CommentaryVerbosity.STANDARD): [
            "Game point {player_b}! {score}.",
        ],
        (ScoreMoment.GAME_WON_A, CommentaryVerbosity.STANDARD): [
            "Game {player_a}! {score}.",
        ],
        (ScoreMoment.GAME_WON_B, CommentaryVerbosity.STANDARD): [
            "Game {player_b}! {score}.",
        ],
        (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.STANDARD): [
            "Match {player_a}! {sets_a} games to {sets_b}.",
        ],
        (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.STANDARD): [
            "Match {player_b}! {sets_b} games to {sets_a}.",
        ],
    }

    # Minimal style — only high-priority events
    MINIMAL_TEMPLATES: Dict[tuple, List[str]] = {
        (ScoreMoment.DEUCE, CommentaryVerbosity.MINIMAL): ["Deuce."],
        (ScoreMoment.ADVANTAGE_A, CommentaryVerbosity.MINIMAL): ["Advantage {player_a}."],
        (ScoreMoment.ADVANTAGE_B, CommentaryVerbosity.MINIMAL): ["Advantage {player_b}."],
        (ScoreMoment.GAME_POINT_A, CommentaryVerbosity.MINIMAL): ["Game point, {player_a}."],
        (ScoreMoment.GAME_POINT_B, CommentaryVerbosity.MINIMAL): ["Game point, {player_b}."],
        (ScoreMoment.GAME_WON_A, CommentaryVerbosity.MINIMAL): ["Game {player_a}."],
        (ScoreMoment.GAME_WON_B, CommentaryVerbosity.MINIMAL): ["Game {player_b}."],
        (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.MINIMAL): [
            "Match {player_a}."
        ],
        (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.MINIMAL): [
            "Match {player_b}."
        ],
    }

    # Kids style — friendlier language
    KIDS_TEMPLATES: Dict[tuple, List[str]] = {
        (ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD): [
            "Yay, {player_a} scores! {score}.",
            "Awesome point, {player_a}! {score}.",
        ],
        (ScoreMoment.POINT_B, CommentaryVerbosity.STANDARD): [
            "Yay, {player_b} scores! {score}.",
            "Awesome point, {player_b}! {score}.",
        ],
        (ScoreMoment.GAME_WON_A, CommentaryVerbosity.STANDARD): [
            "Game to {player_a}, {score}! Great job!",
        ],
        (ScoreMoment.GAME_WON_B, CommentaryVerbosity.STANDARD): [
            "Game to {player_b}, {score}! Great job!",
        ],
        (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.STANDARD): [
            "Match to {player_a}, {sets_a} to {sets_b}! You did it!",
        ],
        (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.STANDARD): [
            "Match to {player_b}, {sets_b} to {sets_a}! You did it!",
        ],
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_score_moment(
        self,
        state: SpokenScoreState,
        previous_state: Optional[SpokenScoreState] = None,
    ) -> ScoreMoment:
        """
        Classify the current score state into a ScoreMoment.

        Uses match_history to determine who scored and whether the previous
        state was different.
        """
        a, b = state.score_a, state.score_b
        prev_a = previous_state.score_a if previous_state else a
        prev_b = previous_state.score_b if previous_state else b

        # Determine scorer from history or state diff
        scorer = self._detect_scorer(state, previous_state)

        # Match won detection (best of 5, first to 3 sets)
        if state.sets_a >= 3 or state.sets_b >= 3:
            if scorer == "A" and state.sets_a >= 3:
                return ScoreMoment.MATCH_WON_A
            if scorer == "B" and state.sets_b >= 3:
                return ScoreMoment.MATCH_WON_B

        # Game won detection (first to 11, win by 2)
        if (a >= 11 or b >= 11) and abs(a - b) >= 2:
            if scorer == "A":
                return ScoreMoment.GAME_WON_A
            if scorer == "B":
                return ScoreMoment.GAME_WON_B

        # Game point detection (10 to opponent <= 9)
        if scorer == "A" and a >= 10 and b <= 9:
            return ScoreMoment.GAME_POINT_A
        if scorer == "B" and b >= 10 and a <= 9:
            return ScoreMoment.GAME_POINT_B

        # Advantage / Deuce detection (both >= 10)
        if a >= 10 and b >= 10:
            if a > b:
                return ScoreMoment.ADVANTAGE_A
            elif b > a:
                return ScoreMoment.ADVANTAGE_B
            else:
                return ScoreMoment.DEUCE

        # Deuce at exactly 10-10
        if a == 10 and b == 10:
            return ScoreMoment.DEUCE

        # Undo or reset — check BEFORE normal point so undo takes precedence
        if previous_state is not None and (a < prev_a or b < prev_b):
            return ScoreMoment.UNDO

        # Normal point
        if scorer == "A":
            moment = ScoreMoment.POINT_A
        elif scorer == "B":
            moment = ScoreMoment.POINT_B
        else:
            moment = ScoreMoment.INVALID

        # Streak detection (3+ consecutive points by same player)
        if self._is_streak(state, min_streak=3):
            if scorer == "A":
                moment = ScoreMoment.STREAK_A
            elif scorer == "B":
                moment = ScoreMoment.STREAK_B

        # Comeback detection (trailed by >= 5 and now tied or ahead)
        if self._is_comeback(state, previous_state, threshold=5):
            if scorer == "A":
                moment = ScoreMoment.COMEBACK_A
            elif scorer == "B":
                moment = ScoreMoment.COMEBACK_B

        return moment

    def format_score_spoken(self, state: SpokenScoreState) -> str:
        """Format score as spoken string, e.g. '5 to 3' or '11 to 8'."""
        return f"{state.score_a} to {state.score_b}"

    def get_commentary_templates(
        self,
        style: CommentaryStyle,
        moment: ScoreMoment,
        verbosity: CommentaryVerbosity,
    ) -> List[str]:
        """Return list of template strings for the given style/moment/verbosity."""
        if verbosity == CommentaryVerbosity.SILENT or style == CommentaryStyle.SILENT:
            return []

        # Minimal style has its own restricted set
        if style == CommentaryStyle.MINIMAL:
            key = (moment, verbosity)
            templates = self.MINIMAL_TEMPLATES.get(key, [])
            if templates:
                return templates
            # Minimal falls back to empty for non-high-priority events
            return []

        # Kids style overrides
        if style == CommentaryStyle.KIDS:
            key = (moment, verbosity)
            templates = self.KIDS_TEMPLATES.get(key)
            if templates:
                return templates
            # Fallback to neutral for kids style
            fallback_key = (moment, CommentaryStyle.NEUTRAL, verbosity)
            return self.TEMPLATES.get(fallback_key, [])

        # Coach style overrides
        if style == CommentaryStyle.COACH:
            key = (moment, verbosity)
            templates = self.COACH_TEMPLATES.get(key)
            if templates:
                return templates

        # Announcer style overrides
        if style == CommentaryStyle.ANNOUNCER:
            key = (moment, verbosity)
            templates = self.ANNOUNCER_TEMPLATES.get(key)
            if templates:
                return templates

        # Default: neutral templates
        key = (moment, style, verbosity)
        templates = self.TEMPLATES.get(key, [])
        if templates:
            return templates

        # Fallback: try neutral + same verbosity
        fallback_key = (moment, CommentaryStyle.NEUTRAL, verbosity)
        return self.TEMPLATES.get(fallback_key, [])

    def choose_commentary_template(self, templates: List[str]) -> str:
        """Pick a template deterministically (first match, or random if multiple)."""
        if not templates:
            return ""
        # Deterministic: use first template. Could add round-robin later.
        return templates[0]

    def build_score_commentary(
        self,
        event_type: str,
        state: SpokenScoreState,
        settings: CommentarySettings,
        event_id: str,
        previous_state: Optional[SpokenScoreState] = None,
    ) -> CommentaryLine:
        """
        Build a CommentaryLine for the given event.

        Args:
            event_type: string identifier for the event (e.g. "point_a", "undo").
            state: current score state.
            settings: user commentary settings.
            event_id: unique event identifier for dedupe.
            previous_state: state before the event (optional).
        """
        # Respect enabled/muted settings early
        if not settings.enabled or settings.muted:
            return CommentaryLine(
                text="",
                event_type=event_type,
                priority=1,
                should_speak=False,
                dedupe_key=f"{event_type}:{event_id}",
                event_id=event_id,
            )

        moment = self.classify_score_moment(state, previous_state)
        templates = self.get_commentary_templates(settings.style, moment, settings.verbosity)
        template = self.choose_commentary_template(templates)

        if not template:
            return CommentaryLine(
                text="",
                event_type=event_type,
                priority=1,
                should_speak=False,
                dedupe_key=f"{event_type}:{event_id}",
                event_id=event_id,
            )

        text = template.format(
            player_a=state.player_a,
            player_b=state.player_b,
            score=self.format_score_spoken(state),
            sets_a=state.sets_a,
            sets_b=state.sets_b,
        )

        priority = 3 if moment in (
            ScoreMoment.GAME_WON_A,
            ScoreMoment.GAME_WON_B,
            ScoreMoment.MATCH_WON_A,
            ScoreMoment.MATCH_WON_B,
            ScoreMoment.DEUCE,
            ScoreMoment.ADVANTAGE_A,
            ScoreMoment.ADVANTAGE_B,
            ScoreMoment.GAME_POINT_A,
            ScoreMoment.GAME_POINT_B,
        ) else 2

        return CommentaryLine(
            text=text,
            event_type=event_type,
            priority=priority,
            should_speak=True,
            dedupe_key=f"{event_type}:{event_id}",
            event_id=event_id,
            ssml_text=text,  # plain text is already SSML-safe
        )

    def should_speak_commentary(
        self,
        last_event_id: Optional[str],
        current_event_id: str,
        settings: CommentarySettings,
    ) -> bool:
        """
        Determine whether the current commentary should be spoken.

        Returns False if:
        - Commentary is disabled
        - Commentary is muted
        - The event_id matches the last spoken event_id (rerun dedupe)
        """
        if not settings.enabled:
            return False
        if settings.muted:
            return False
        if last_event_id is not None and last_event_id == current_event_id:
            return False
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _detect_scorer(
        self,
        state: SpokenScoreState,
        previous_state: Optional[SpokenScoreState],
    ) -> Optional[str]:
        """Detect who scored the last point from history or state diff."""
        if previous_state is None:
            # No previous state — check history
            if state.match_history:
                last = state.match_history[-1]
                if last.get("action") == "point_added":
                    return last.get("player")
            return None

        # If both scores changed (shouldn't happen in real play), prefer history
        if (
            state.score_a > previous_state.score_a
            and state.score_b > previous_state.score_b
        ):
            if state.match_history:
                last = state.match_history[-1]
                if last.get("action") == "point_added":
                    return last.get("player")
            return None

        # State diff
        if state.score_a > previous_state.score_a:
            return "A"
        if state.score_b > previous_state.score_b:
            return "B"

        # If scores didn't increase, check history for undo
        if state.match_history:
            last = state.match_history[-1]
            if last.get("action") == "point_added":
                return last.get("player")

        return None

    def _is_streak(self, state: SpokenScoreState, min_streak: int = 3) -> bool:
        if len(state.match_history) < min_streak:
            return False
        recent = state.match_history[-min_streak:]
        players = [e.get("player") for e in recent if e.get("action") == "point_added"]
        if len(players) < min_streak:
            return False
        return len(set(players)) == 1

    def _is_comeback(
        self,
        state: SpokenScoreState,
        previous_state: Optional[SpokenScoreState],
        threshold: int = 5,
    ) -> bool:
        if previous_state is None:
            return False
        prev_diff = previous_state.score_a - previous_state.score_b
        curr_diff = state.score_a - state.score_b
        if prev_diff <= -threshold and curr_diff >= 0:
            return True
        if prev_diff >= threshold and curr_diff <= 0:
            return True
        return False
