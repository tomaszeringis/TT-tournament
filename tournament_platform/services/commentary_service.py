"""
Commentary Service — deterministic spoken commentary for the Voice Scorekeeper.

Generates short, natural commentary lines for table-tennis score events
using hand-written templates. No LLM required. No network calls.
"""

import copy
import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from tournament_platform.services import commentary_templates as _ct_module


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
    PROFESSIONAL = "professional"
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


class CommentaryLanguage(str, Enum):
    EN = "en"
    LT = "lt"


class CommentaryMode(str, Enum):
    OFF = "off"
    VISUAL_ONLY = "visual_only"
    IMPORTANT_ONLY = "important_only"
    AFTER_EVERY_GAME = "after_every_game"
    EVERY_POINT = "every_point"
    SPOKEN = "spoken"


class CommentaryIntensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImportanceLevel(str, Enum):
    NORMAL = "normal"
    IMPORTANT = "important"
    CRITICAL = "critical"


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
    generated_text: Optional[str] = None
    final_text: Optional[str] = None
    template_language: Optional[str] = None
    template_style: Optional[str] = None
    base_template: Optional[str] = None
    used_fallback: bool = False
    fallback_reason: Optional[str] = None
    mixed_language_detected: bool = False
    used_ollama: bool = False
    ollama_rejected_reason: Optional[str] = None
    tts_language_code: Optional[str] = None
    cache_key: Optional[str] = None
    cache_hit: bool = False
    selected_language: Optional[str] = None
    normalized_language: Optional[str] = None
    event_id_str: Optional[str] = None


@dataclass
class CommentarySettings:
    """User preferences for spoken commentary."""
    enabled: bool = False
    style: CommentaryStyle = CommentaryStyle.NEUTRAL
    verbosity: CommentaryVerbosity = CommentaryVerbosity.STANDARD
    voice: str = "default"
    language: str = "en"
    muted: bool = False
    mode: CommentaryMode = CommentaryMode.EVERY_POINT
    intensity: CommentaryIntensity = CommentaryIntensity.MEDIUM
    speak_generated: bool = True
    ollama_rewrite_enabled: bool = False
    ollama_model: str = ""
    ollama_timeout: float = 2.0
    voice_profile_id: str = "browser_default"
    rate: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0


@dataclass
class CommentaryRewriteSettings:
    """Settings for the optional Ollama rewrite layer."""
    enabled: bool = False
    model: str = "llama3:latest"
    host: str = "http://localhost:11434"
    timeout: float = 2.0


# ============================================================================
# Template Library
# ============================================================================

def _build_template_library() -> Dict[str, Dict[str, Dict[str, List[Dict]]]]:
    """Build the comprehensive template library keyed by event_id, language, style."""
    lib: Dict[str, Dict[str, Dict[str, List[Dict]]]] = {}

    def add(event_id: str, language: str, style: str, templates: List[Dict]):
        lib.setdefault(event_id, {}).setdefault(language, {}).setdefault(style, []).extend(templates)

    add("point_scored", "en", "neutral", [
        {"text": "Point for {player}. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
        {"text": "{player} scores. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "en", "professional", [
        {"text": "{player} takes the point. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "en", "beginner", [
        {"text": "Great job, {player}! {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "en", "coach", [
        {"text": "Good point, {player}. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
        {"text": "Nice one, {player}. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "en", "energetic", [
        {"text": "Point to {player}! {score}. What a shot!", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "lt", "neutral", [
        {"text": "Tašką laimi {player}, rezultatas {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
        {"text": "{player} pelno tašką. Rezultatas {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "lt", "professional", [
        {"text": "{player} pelno svarbų tašką, rezultatas {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "lt", "beginner", [
        {"text": "{player} laimi šį tašką. Rezultatas dabar {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "lt", "coach", [
        {"text": "Gerai, {player}. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "lt", "energetic", [
        {"text": "Svarbus taškas: {player} pelno tašką! {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("point_scored", "lt", "minimal", [
        {"text": "Taškas {player}. {score}.", "required_vars": ["player", "score"], "importance": "normal", "speak_default": True},
    ])
    add("lead_change", "lt", "neutral", [
        {"text": "{player} išsiveržia į priekį, rezultatas {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("deuce", "en", "neutral", [
        {"text": "Deuce. {score}.", "required_vars": ["score"], "importance": "critical", "speak_default": True},
    ])
    add("deuce", "en", "energetic", [
        {"text": "Deuce! {score}. Exciting finish!", "required_vars": ["score"], "importance": "critical", "speak_default": True},
    ])
    add("deuce", "lt", "neutral", [
        {"text": "Lygiosios.", "required_vars": [], "importance": "critical", "speak_default": True},
        {"text": "Rezultatas lygus.", "required_vars": [], "importance": "critical", "speak_default": True},
        {"text": "Lygiųjų būsena.", "required_vars": [], "importance": "critical", "speak_default": True},
    ])
    add("deuce", "lt", "energetic", [
        {"text": "Lygiosios! Įtampa didžiulė.", "required_vars": [], "importance": "critical", "speak_default": True},
    ])
    add("advantage", "lt", "neutral", [
        {"text": "Pranašumas {player}.", "required_vars": ["player"], "importance": "important", "speak_default": True},
        {"text": "{player} turi pranašumą.", "required_vars": ["player"], "importance": "important", "speak_default": True},
    ])
    add("game_point", "lt", "neutral", [
        {"text": "Žaidimo taškas {player}.", "required_vars": ["player"], "importance": "important", "speak_default": True},
        {"text": "{player} turi žaidimo tašką.", "required_vars": ["player"], "importance": "important", "speak_default": True},
        {"text": "{player} arti laimėti žaidimą.", "required_vars": ["player"], "importance": "important", "speak_default": True},
    ])
    add("set_win", "lt", "neutral", [
        {"text": "{player} laimi žaidimą {set}, rezultatas {score}.", "required_vars": ["player", "set", "score"], "importance": "critical", "speak_default": True},
        {"text": "Žaidimą {set} laimėjo {player}, rezultatas {score}.", "required_vars": ["player", "set", "score"], "importance": "critical", "speak_default": True},
    ])
    add("match_win", "lt", "neutral", [
        {"text": "{winner} laimi mačą {score}.", "required_vars": ["winner", "score"], "importance": "critical", "speak_default": True},
        {"text": "Mačas baigtas: {winner} nugalėjo {loser}, rezultatas {score}.", "required_vars": ["winner", "loser", "score"], "importance": "critical", "speak_default": True},
        {"text": "Laimėtojas {winner}, galutinis rezultatas {score}.", "required_vars": ["winner", "score"], "importance": "critical", "speak_default": True},
    ])
    add("undo", "lt", "neutral", [
        {"text": "Taškas pašalintas. {score}.", "required_vars": ["score"], "importance": "normal", "speak_default": True},
    ])
    add("reset", "lt", "neutral", [
        {"text": "Rungtynes iš naujo. 0 : 0.", "required_vars": [], "importance": "normal", "speak_default": True},
    ])
    add("streak", "lt", "neutral", [
        {"text": "{player} laimėjo {count} taškus iš eilės.", "required_vars": ["player", "count"], "importance": "important", "speak_default": True},
        {"text": "{player} turi {count} taškų seriją.", "required_vars": ["player", "count"], "importance": "important", "speak_default": True},
    ])
    add("comeback", "lt", "neutral", [
        {"text": "{player} grįžta į kovą, rezultatas {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
        {"text": "{player} mažina atsilikimą, rezultatas {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("serve", "lt", "neutral", [
        {"text": "Servisas {player}.", "required_vars": ["player"], "importance": "normal", "speak_default": False},
    ])
    add("timeout", "lt", "neutral", [
        {"text": "Pertrauka.", "required_vars": [], "importance": "normal", "speak_default": False},
    ])
    add("error", "lt", "neutral", [
        {"text": "Klaida.", "required_vars": [], "importance": "critical", "speak_default": False},
    ])
    add("idle", "lt", "neutral", [
        {"text": "", "required_vars": [], "importance": "normal", "speak_default": False},
    ])
    add("countdown", "lt", "neutral", [
        {"text": "{count}", "required_vars": ["count"], "importance": "normal", "speak_default": False},
    ])
    add("sync", "lt", "neutral", [
        {"text": "Sinchronizuota.", "required_vars": [], "importance": "normal", "speak_default": False},
    ])
    add("notification", "lt", "neutral", [
        {"text": "{message}", "required_vars": ["message"], "importance": "normal", "speak_default": False},
    ])
    add("result_submitted", "lt", "neutral", [
        {"text": "Rezultatas pateiktas: {winner} laimi {score}.", "required_vars": ["winner", "score"], "importance": "critical", "speak_default": True},
        {"text": "Mačo rezultatas išsaugotas: {winner}, galutinis rezultatas {score}.", "required_vars": ["winner", "score"], "importance": "critical", "speak_default": True},
        {"text": "Rezultatas patvirtintas: {winner} nugalėjo {loser}, {score}.", "required_vars": ["winner", "loser", "score"], "importance": "critical", "speak_default": True},
    ])
    add("error_or_uncertain_command", "lt", "neutral", [
        {"text": "Komanda neatpažinta.", "required_vars": [], "importance": "critical", "speak_default": False},
        {"text": "Nepavyko patikimai suprasti komandos.", "required_vars": [], "importance": "critical", "speak_default": False},
        {"text": "Pakartokite komandą.", "required_vars": [], "importance": "critical", "speak_default": False},
    ])
    add("advantage", "en", "neutral", [
        {"text": "Advantage {player}.", "required_vars": ["player"], "importance": "important", "speak_default": True},
    ])
    add("advantage", "en", "coach", [
        {"text": "Advantage {player}. One point away.", "required_vars": ["player"], "importance": "important", "speak_default": True},
    ])
    add("advantage", "en", "energetic", [
        {"text": "Advantage {player}! One point to win!", "required_vars": ["player"], "importance": "important", "speak_default": True},
    ])
    add("advantage", "lt", "neutral", [
        {"text": "Privilegija {player}.", "required_vars": ["player"], "importance": "important", "speak_default": True},
    ])
    add("game_point", "en", "neutral", [
        {"text": "Game point, {player}. {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("game_point", "en", "coach", [
        {"text": "Game point, {player}. Stay focused. {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("game_point", "en", "energetic", [
        {"text": "Game point {player}! {score}. Close it out!", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("game_point", "lt", "neutral", [
        {"text": "Ikovos taskas, {player}. {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("set_win", "en", "neutral", [
        {"text": "Game to {player}, {score}.", "required_vars": ["player", "score"], "importance": "critical", "speak_default": True},
        {"text": "Game {game_number} goes to {winner}, {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
        {"text": "{winner} wins game {game_number}, final score {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
        {"text": "{winner} takes game {game_number}, {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
        {"text": "Game {game_number} is complete: {winner} wins {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
    ])
    add("set_win", "en", "coach", [
        {"text": "Game to {player}, {score}. Great game.", "required_vars": ["player", "score"], "importance": "critical", "speak_default": True},
        {"text": "{winner} takes game {game_number}, {game_score}. Well played.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
    ])
    add("set_win", "en", "energetic", [
        {"text": "Game {player}! {score}. Well played!", "required_vars": ["player", "score"], "importance": "critical", "speak_default": True},
        {"text": "Game {game_number} to {winner}, {game_score}. What a game!", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
    ])
    add("set_win", "lt", "neutral", [
        {"text": "Zaidimas {player}. {score}.", "required_vars": ["player", "score"], "importance": "critical", "speak_default": True},
        {"text": "{game_number}-ą žaidimą laimi {winner}, rezultatas {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
        {"text": "Žaidimą {game_number} laimėjo {winner}, rezultatas {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
        {"text": "Žaidimas {game_number} baigtas: {winner} laimi {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
        {"text": "{winner} laimi žaidimą {game_number}, rezultatas {game_score}.", "required_vars": ["winner", "game_number", "game_score"], "importance": "critical", "speak_default": True},
    ])
    add("match_win", "en", "neutral", [
        {"text": "Match complete. {player} wins {sets_a} games to {sets_b}.", "required_vars": ["player", "sets_a", "sets_b"], "importance": "critical", "speak_default": True},
    ])
    add("match_win", "en", "coach", [
        {"text": "Match to {player}, {sets_a} to {sets_b}. Outstanding.", "required_vars": ["player", "sets_a", "sets_b"], "importance": "critical", "speak_default": True},
    ])
    add("match_win", "en", "energetic", [
        {"text": "Match {player}! {sets_a} to {sets_b}. Congratulations!", "required_vars": ["player", "sets_a", "sets_b"], "importance": "critical", "speak_default": True},
    ])
    add("match_win", "lt", "neutral", [
        {"text": "Rungtynes baigtos. {player} laimi {sets_a} : {sets_b}.", "required_vars": ["player", "sets_a", "sets_b"], "importance": "critical", "speak_default": True},
    ])
    add("undo", "en", "neutral", [
        {"text": "Point removed. {score}.", "required_vars": ["score"], "importance": "normal", "speak_default": True},
        {"text": "Undo. Score is {score}.", "required_vars": ["score"], "importance": "normal", "speak_default": True},
    ])
    add("undo", "lt", "neutral", [
        {"text": "Taskas pasalintas. {score}.", "required_vars": ["score"], "importance": "normal", "speak_default": True},
    ])
    add("reset", "en", "neutral", [
        {"text": "Match reset. Score is 0 to 0.", "required_vars": [], "importance": "normal", "speak_default": True},
    ])
    add("reset", "lt", "neutral", [
        {"text": "Rungtynes is naujo. 0 : 0.", "required_vars": [], "importance": "normal", "speak_default": True},
    ])
    add("streak", "en", "neutral", [
        {"text": "{player} on a hot streak. {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("streak", "en", "energetic", [
        {"text": "{player} is unstoppable! {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("streak", "lt", "neutral", [
        {"text": "{player} karštas serija. {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("comeback", "en", "neutral", [
        {"text": "What a comeback by {player}! {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("comeback", "en", "energetic", [
        {"text": "Incredible comeback, {player}! {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("comeback", "lt", "neutral", [
        {"text": "Kokia atgimimas, {player}! {score}.", "required_vars": ["player", "score"], "importance": "important", "speak_default": True},
    ])
    add("lead_change", "en", "neutral", [
        {"text": "Lead change. {player_a} {score_a} to {player_b} {score_b}.", "required_vars": ["player_a", "player_b", "score_a", "score_b"], "importance": "important", "speak_default": True},
    ])
    add("lead_change", "en", "energetic", [
        {"text": "Lead change! {player_a} {score_a} to {player_b} {score_b}.", "required_vars": ["player_a", "player_b", "score_a", "score_b"], "importance": "important", "speak_default": True},
    ])
    add("serve", "en", "neutral", [
        {"text": "Serve changes to {player}.", "required_vars": ["player"], "importance": "normal", "speak_default": False},
    ])
    add("serve", "lt", "neutral", [
        {"text": "Servisas {player}.", "required_vars": ["player"], "importance": "normal", "speak_default": False},
    ])
    add("result_submitted", "en", "neutral", [
        {"text": "Match result submitted. {player} wins {sets_a} to {sets_b}.", "required_vars": ["player", "sets_a", "sets_b"], "importance": "critical", "speak_default": True},
    ])
    add("result_submitted", "lt", "neutral", [
        {"text": "Rezultatas issiustas. {player} laimi {sets_a} : {sets_b}.", "required_vars": ["player", "sets_a", "sets_b"], "importance": "critical", "speak_default": True},
    ])
    add("timeout", "en", "neutral", [
        {"text": "Timeout.", "required_vars": [], "importance": "normal", "speak_default": False},
    ])
    add("error", "en", "neutral", [
        {"text": "Error.", "required_vars": [], "importance": "critical", "speak_default": False},
    ])
    add("idle", "en", "neutral", [
        {"text": "", "required_vars": [], "importance": "normal", "speak_default": False},
    ])
    add("countdown", "en", "neutral", [
        {"text": "{count}", "required_vars": ["count"], "importance": "normal", "speak_default": False},
    ])
    add("sync", "en", "neutral", [
        {"text": "Synced.", "required_vars": [], "importance": "normal", "speak_default": False},
    ])
    add("notification", "en", "neutral", [
        {"text": "{message}", "required_vars": ["message"], "importance": "normal", "speak_default": False},
    ])
    return lib


TEMPLATE_LIBRARY: Dict[str, Dict[str, Dict[str, List[Dict]]]] = _build_template_library()


# ============================================================================
# No-Repeat Selection
# ============================================================================

class TemplateSelector:
    """Select templates with no-repeat logic and LRU fallback."""

    def __init__(self, recent_window: int = 5):
        self.recent_window = recent_window

    def _recent_key(self, match_id: Optional[int], language: str, style: str, event_id: str) -> str:
        mid = str(match_id or "global")
        return f"commentary_recent_templates:{mid}:{language}:{style}:{event_id}"

    def _get_recent(self, session_state: Dict[str, Any], key: str) -> List[str]:
        data = session_state.get(key, [])
        if not isinstance(data, list):
            return []
        return data

    def select(
        self,
        event_id: str,
        language: str,
        style: str,
        templates: List[Dict],
        session_state: Dict[str, Any],
        match_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Select a template avoiding recent repeats."""
        if not templates:
            return None
        if len(templates) == 1:
            return templates[0]
        key = self._recent_key(match_id, language, style, event_id)
        recent = self._get_recent(session_state, key)
        candidates = [t for t in templates if t["text"] not in recent]
        if not candidates:
            candidates = list(templates)
        chosen = candidates[0]
        new_recent = (recent + [chosen["text"]])[-self.recent_window:]
        session_state[key] = new_recent
        return chosen


# ============================================================================
# Ollama Rewrite Layer
# ============================================================================

class CommentaryRewriter:
    """Optional local Ollama rewrite layer for commentary text."""

    def __init__(
        self,
        enabled: bool = False,
        model: str = "llama3:latest",
        host: str = "http://localhost:11434",
        timeout: float = 2.0,
    ):
        self.enabled = enabled
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()

    def _cache_key(self, base_text: str, facts: dict, style: str, language: str, event_type: str) -> str:
        payload = json.dumps({
            "base_text": base_text,
            "facts": facts,
            "style": style,
            "language": language,
            "event_type": event_type,
        }, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def rewrite(
        self,
        base_text: str,
        facts: dict,
        style: str,
        language: str,
        event_type: str,
    ) -> Tuple[str, bool]:
        """Rewrite base commentary text via Ollama, with validation and caching.

        Returns (final_text, used_ollama).
        """
        if not self.enabled:
            return base_text, False
        key = self._cache_key(base_text, facts, style, language, event_type)
        with self._lock:
            if key in self._cache:
                return self._cache[key], True
        prompt = self._build_prompt(base_text, facts)
        try:
            rewritten = self._call_ollama(prompt)
            if not self._validate(rewritten, facts, language):
                logger.warning("CommentaryRewriter: validation failed for rewritten text")
                return base_text, False
            with self._lock:
                self._cache[key] = rewritten
            return rewritten, True
        except Exception as exc:
            logger.warning("CommentaryRewriter: Ollama call failed: %s", exc)
            return base_text, False

    def _build_prompt(self, base_text: str, facts: dict) -> str:
        player_a = facts.get("player_a", "")
        player_b = facts.get("player_b", "")
        score_a = facts.get("score_a", "")
        score_b = facts.get("score_b", "")
        winner = facts.get("winner", "")
        loser = facts.get("loser", "")
        set_number = facts.get("set", "")
        game_score = facts.get("score", "")
        language = facts.get("language", "en")
        facts_json = json.dumps(facts, default=str)
        lang_rule = f"- Write only in {language}."
        if language == "lt":
            lang_rule = "- Rašyk tik lietuviškai. Nenaudok anglų kalbos.\n" + lang_rule
        return (
            "You are a table tennis commentary assistant. Rewrite the following commentary into 1-2 short sentences.\n\n"
            "Rules:\n"
            f"- Preserve all player names exactly: {player_a}, {player_b}\n"
            f"- Preserve all scores exactly: {score_a}-{score_b}\n"
            f"- Preserve winner/loser exactly: {winner}, {loser}\n"
            f"- Preserve game/set number exactly: {set_number}\n"
            f"- Preserve game score exactly: {game_score}\n"
            "- Do not add shot types, tactics, rankings, injuries, or emotions\n"
            "- Do not add external knowledge\n"
            "- Output only the commentary text, no markdown\n"
            f"{lang_rule}\n\n"
            f"Base commentary: {base_text}\n"
            f"Facts: {facts_json}\n"
        )

    def _call_ollama(self, prompt: str) -> str:
        import ollama
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"timeout": self.timeout},
        )
        text = response.get("message", {}).get("content", "").strip()
        if not text:
            raise ValueError("Empty Ollama response")
        return text

    def _validate(self, text: str, facts: dict, language: str = "en") -> bool:
        if not text or len(text) > 200:
            return False
        player_a = str(facts.get("player_a", ""))
        player_b = str(facts.get("player_b", ""))
        if player_a and player_a not in text:
            return False
        if player_b and player_b not in text:
            return False
        set_number = str(facts.get("set", ""))
        if set_number and set_number not in text:
            return False
        game_score = str(facts.get("score", ""))
        if game_score and game_score not in text:
            return False
        if language == "lt" and contains_english_commentary(text, language, (player_a, player_b)):
            logger.warning("Ollama rewrite rejected because Lithuanian was selected but output was mixed or English.")
            return False
        return True


# ============================================================================
# Commentary Logging Helpers
# ============================================================================

def log_commentary_event(
    db_session,
    tournament_id: Optional[int],
    match_id: Optional[int],
    player_a: Optional[str],
    player_b: Optional[str],
    event_type: str,
    source_event_json: str,
    score_before_json: Optional[str],
    score_after_json: Optional[str],
    style: str,
    language: str,
    commentary_mode: str,
    intensity: str,
    template_id: Optional[str],
    generated_text: str,
    final_text: str,
    used_ollama: bool,
    ollama_model: Optional[str],
    ollama_cache_hit: bool,
    spoken: bool,
    tts_mode: Optional[str],
    latency_ms: Optional[float],
    error: Optional[str],
    cache_key: Optional[str],
) -> Any:
    """Persist a commentary event to the database."""
    from tournament_platform.models import CommentaryEvent
    row = CommentaryEvent(
        tournament_id=tournament_id,
        match_id=match_id,
        player_a=player_a,
        player_b=player_b,
        event_type=event_type,
        source_event_json=source_event_json,
        score_before_json=score_before_json,
        score_after_json=score_after_json,
        style=style,
        language=language,
        frequency_mode=commentary_mode,
        intensity=intensity,
        template_id=template_id,
        generated_text=generated_text,
        final_text=final_text,
        used_ollama=used_ollama,
        spoken=spoken,
        tts_mode=tts_mode,
        latency_ms=latency_ms,
        error=error,
        cache_key=cache_key,
        ollama_model=ollama_model,
        ollama_cache_hit=ollama_cache_hit,
    )
    db_session.add(row)
    try:
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    return row


def get_recent_commentary_events(match_id: int, limit: int = 20) -> List[Any]:
    """Return recent commentary events for a match."""
    from tournament_platform.models import SessionLocal, CommentaryEvent
    db = SessionLocal()
    try:
        return (
            db.query(CommentaryEvent)
            .filter(CommentaryEvent.match_id == match_id)
            .order_by(CommentaryEvent.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def get_commentary_events_for_tournament(tournament_id: int, limit: int = 50) -> List[Any]:
    """Return recent commentary events for a tournament."""
    from tournament_platform.models import SessionLocal, CommentaryEvent
    db = SessionLocal()
    try:
        return (
            db.query(CommentaryEvent)
            .filter(CommentaryEvent.tournament_id == tournament_id)
            .order_by(CommentaryEvent.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


LEGACY_TEMPLATES: Dict[tuple, List[str]] = {
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
    (ScoreMoment.UNDO, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Point removed. {score}.",
        "Undo. Score is {score}.",
    ],
    (ScoreMoment.UNDO, CommentaryStyle.NEUTRAL, CommentaryVerbosity.MINIMAL): [],
    (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.MINIMAL): ["Deuce."],
    (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Deuce. {score}."],
    (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Deuce! {score}. Exciting finish."],
    (ScoreMoment.ADVANTAGE_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Advantage {player_a}."],
    (ScoreMoment.ADVANTAGE_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Advantage {player_b}."],
    (ScoreMoment.ADVANTAGE_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Advantage {player_a}. One point away."],
    (ScoreMoment.ADVANTAGE_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Advantage {player_b}. One point away."],
    (ScoreMoment.GAME_POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Game point, {player_a}. {score}."],
    (ScoreMoment.GAME_POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Game point, {player_b}. {score}."],
    (ScoreMoment.GAME_POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Game point, {player_a}. {score}. Close it out."],
    (ScoreMoment.GAME_POINT_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Game point, {player_b}. {score}. Close it out."],
    (ScoreMoment.GAME_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Game to {player_a}, {score}."],
    (ScoreMoment.GAME_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Game to {player_b}, {score}."],
    (ScoreMoment.GAME_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Game to {player_a}, {score}. Well played."],
    (ScoreMoment.GAME_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Game to {player_b}, {score}. Well played."],
    (ScoreMoment.MATCH_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Match complete. {player_a} wins {sets_a} games to {sets_b}."],
    (ScoreMoment.MATCH_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Match complete. {player_b} wins {sets_b} games to {sets_a}."],
    (ScoreMoment.MATCH_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Match complete. {player_a} wins {sets_a} games to {sets_b}. Congratulations."],
    (ScoreMoment.MATCH_WON_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.EXPRESSIVE): ["Match complete. {player_b} wins {sets_b} games to {sets_a}. Congratulations."],
    (ScoreMoment.RESET, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Match reset. Score is 0 to 0."],
    (ScoreMoment.INVALID, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Invalid score."],
    (ScoreMoment.MATCH_SUBMITTED, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["Match result submitted."],
    (ScoreMoment.STREAK_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["{player_a} on a hot streak. {score}."],
    (ScoreMoment.STREAK_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["{player_b} on a hot streak. {score}."],
    (ScoreMoment.COMEBACK_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["What a comeback by {player_a}! {score}."],
    (ScoreMoment.COMEBACK_B, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): ["What a comeback by {player_b}! {score}."],
}

LEGACY_COACH_TEMPLATES: Dict[tuple, List[str]] = {
    (ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD): ["Good point, {player_a}. {score}.", "Nice one, {player_a}. {score}."],
    (ScoreMoment.POINT_B, CommentaryVerbosity.STANDARD): ["Good point, {player_b}. {score}.", "Nice one, {player_b}. {score}."],
    (ScoreMoment.GAME_POINT_A, CommentaryVerbosity.STANDARD): ["Game point, {player_a}. Stay focused. {score}."],
    (ScoreMoment.GAME_POINT_B, CommentaryVerbosity.STANDARD): ["Game point, {player_b}. Stay focused. {score}."],
    (ScoreMoment.GAME_WON_A, CommentaryVerbosity.STANDARD): ["Game to {player_a}, {score}. Great game."],
    (ScoreMoment.GAME_WON_B, CommentaryVerbosity.STANDARD): ["Game to {player_b}, {score}. Great game."],
    (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.STANDARD): ["Match to {player_a}, {sets_a} to {sets_b}. Outstanding."],
    (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.STANDARD): ["Match to {player_b}, {sets_b} to {sets_a}. Outstanding."],
}

LEGACY_ANNOUNCER_TEMPLATES: Dict[tuple, List[str]] = {
    (ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD): ["And {player_a} takes the point! {score}."],
    (ScoreMoment.POINT_B, CommentaryVerbosity.STANDARD): ["And {player_b} takes the point! {score}."],
    (ScoreMoment.DEUCE, CommentaryVerbosity.STANDARD): ["Deuce! {score}. The crowd is on their feet."],
    (ScoreMoment.ADVANTAGE_A, CommentaryVerbosity.STANDARD): ["Advantage {player_a}! {score}."],
    (ScoreMoment.ADVANTAGE_B, CommentaryVerbosity.STANDARD): ["Advantage {player_b}! {score}."],
    (ScoreMoment.GAME_POINT_A, CommentaryVerbosity.STANDARD): ["Game point {player_a}! {score}."],
    (ScoreMoment.GAME_POINT_B, CommentaryVerbosity.STANDARD): ["Game point {player_b}! {score}."],
    (ScoreMoment.GAME_WON_A, CommentaryVerbosity.STANDARD): ["Game {player_a}! {score}."],
    (ScoreMoment.GAME_WON_B, CommentaryVerbosity.STANDARD): ["Game {player_b}! {score}."],
    (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.STANDARD): ["Match {player_a}! {sets_a} games to {sets_b}."],
    (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.STANDARD): ["Match {player_b}! {sets_b} games to {sets_a}."],
}

LEGACY_MINIMAL_TEMPLATES: Dict[tuple, List[str]] = {
    (ScoreMoment.DEUCE, CommentaryVerbosity.MINIMAL): ["Deuce."],
    (ScoreMoment.ADVANTAGE_A, CommentaryVerbosity.MINIMAL): ["Advantage {player_a}."],
    (ScoreMoment.ADVANTAGE_B, CommentaryVerbosity.MINIMAL): ["Advantage {player_b}."],
    (ScoreMoment.GAME_POINT_A, CommentaryVerbosity.MINIMAL): ["Game point, {player_a}."],
    (ScoreMoment.GAME_POINT_B, CommentaryVerbosity.MINIMAL): ["Game point, {player_b}."],
    (ScoreMoment.GAME_WON_A, CommentaryVerbosity.MINIMAL): ["Game {player_a}."],
    (ScoreMoment.GAME_WON_B, CommentaryVerbosity.MINIMAL): ["Game {player_b}."],
    (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.MINIMAL): ["Match {player_a}."],
    (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.MINIMAL): ["Match {player_b}."],
}

LEGACY_KIDS_TEMPLATES: Dict[tuple, List[str]] = {
    (ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD): ["Yay, {player_a} scores! {score}.", "Awesome point, {player_a}! {score}."],
    (ScoreMoment.POINT_B, CommentaryVerbosity.STANDARD): ["Yay, {player_b} scores! {score}.", "Awesome point, {player_b}! {score}."],
    (ScoreMoment.GAME_WON_A, CommentaryVerbosity.STANDARD): ["Game to {player_a}, {score}! Great job!"],
    (ScoreMoment.GAME_WON_B, CommentaryVerbosity.STANDARD): ["Game to {player_b}, {score}! Great job!"],
    (ScoreMoment.MATCH_WON_A, CommentaryVerbosity.STANDARD): ["Match to {player_a}, {sets_a} to {sets_b}! You did it!"],
    (ScoreMoment.MATCH_WON_B, CommentaryVerbosity.STANDARD): ["Match to {player_b}, {sets_b} to {sets_a}! You did it!"],
}


ENGLISH_COMMENTARY_FRAGMENTS = (
    "point for",
    "wins the point",
    "takes the point",
    "score ",
    "now ",
    "game point",
    "match point",
    "set ",
    "wins ",
    "defeats",
    "advantage",
    "one point away",
    "final score",
    "victory",
    "lead change",
    "in front",
    "has advantage",
)


def contains_english_commentary(text: str, language: str, player_names: Tuple[str, str]) -> bool:
    if language != "lt":
        return False
    low = text.lower()
    for frag in ENGLISH_COMMENTARY_FRAGMENTS:
        if frag in low and not any(frag in n.lower() for n in player_names):
            return True
    return False


LITHUANIAN_GENERIC_TEMPLATES: Dict[str, List[str]] = {
    "point_scored": [
        "Tašką laimi {player}, rezultatas {score}.",
        "{player} pelno tašką. Rezultatas {score}.",
        "Rezultatas {score}, taškas žaidėjui {player}.",
    ],
    "lead_change": [
        "{player} išsiveržia į priekį, rezultatas {score}.",
        "Dabar pirmauja {player}, rezultatas {score}.",
    ],
    "deuce": [
        "Lygiosios.",
        "Rezultatas lygus.",
        "Lygiųjų būsena.",
    ],
    "advantage": [
        "Pranašumas {player}.",
        "{player} turi pranašumą.",
    ],
    "game_point": [
        "Žaidimo taškas {player}.",
        "{player} turi žaidimo tašką.",
        "{player} arti laimėti žaidimą.",
    ],
    "match_point": [
        "Mačo taškas {player}.",
        "{player} turi mačo tašką.",
        "{player} arti laimėti mačą.",
    ],
    "set_win": [
        "{player} laimi žaidimą {set}, rezultatas {score}.",
        "Žaidimą {set} laimėjo {player}, rezultatas {score}.",
    ],
    "match_win": [
        "{winner} laimi mačą {score}.",
        "Mačas baigtas: {winner} nugalėjo {loser}, rezultatas {score}.",
        "Laimėtojas {winner}, galutinis rezultatas {score}.",
    ],
    "streak": [
        "{player} laimėjo {count} taškus iš eilės.",
        "{player} turi {count} taškų seriją.",
    ],
    "comeback": [
        "{player} grįžta į kovą, rezultatas {score}.",
        "{player} mažina atsilikimą, rezultatas {score}.",
    ],
    "result_submitted": [
        "Rezultatas pateiktas: {winner} laimi {score}.",
        "Mačo rezultatas išsaugotas: {winner}, galutinis rezultatas {score}.",
        "Rezultatas patvirtintas: {winner} nugalėjo {loser}, {score}.",
    ],
    "error_or_uncertain_command": [
        "Komanda neatpažinta.",
        "Nepavyko patikimai suprasti komandos.",
        "Pakartokite komandą.",
    ],
    "serve": [
        "Servisas {player}.",
    ],
    "timeout": [
        "Pertrauka.",
    ],
}

ENGLISH_GENERIC_TEMPLATES: Dict[str, List[str]] = {
    "point_scored": [
        "Point for {player}, score {score}.",
        "{player} scores. Score is {score}.",
    ],
    "lead_change": [
        "Lead change. {player} takes the lead, score {score}.",
    ],
    "deuce": [
        "Deuce.",
        "Score is tied.",
        "Tied game.",
    ],
    "advantage": [
        "Advantage {player}.",
        "{player} has advantage.",
    ],
    "game_point": [
        "Game point {player}.",
        "{player} has game point.",
        "{player} is one point away from winning the game.",
    ],
    "match_point": [
        "Match point {player}.",
        "{player} has match point.",
        "{player} is one point away from winning the match.",
    ],
    "set_win": [
        "{player} wins game {set}, score {score}.",
    ],
    "match_win": [
        "{winner} wins the match {score}.",
        "Match complete: {winner} defeats {loser}, final score {score}.",
        "Winner is {winner}, final score {score}.",
    ],
    "streak": [
        "{player} has won {count} points in a row.",
    ],
    "comeback": [
        "{player} is fighting back, score {score}.",
    ],
    "result_submitted": [
        "Result submitted: {winner} wins {score}.",
    ],
    "error_or_uncertain_command": [
        "Command not recognized.",
        "Could not understand the command.",
        "Please repeat the command.",
    ],
    "serve": [
        "Serve to {player}.",
    ],
    "timeout": [
        "Timeout.",
    ],
}

SAFE_MESSAGE: Dict[str, str] = {
    "lt": "Komentaras negalimas.",
    "en": "Commentary unavailable.",
}


class CommentaryService:
    """
    Deterministic commentary generator for table-tennis scorekeeping.

    Uses hand-written templates. No LLM by default. Optional local Ollama rewrite.
    """

    TEMPLATES = LEGACY_TEMPLATES
    COACH_TEMPLATES = LEGACY_COACH_TEMPLATES
    ANNOUNCER_TEMPLATES = LEGACY_ANNOUNCER_TEMPLATES
    MINIMAL_TEMPLATES = LEGACY_MINIMAL_TEMPLATES
    KIDS_TEMPLATES = LEGACY_KIDS_TEMPLATES

    def __init__(self, rewriter: Optional[CommentaryRewriter] = None):
        self.rewriter = rewriter or CommentaryRewriter()
        self.template_selector = TemplateSelector()
        # Recent template keys per (language, style, category) for deduplication.
        self._recent_template_keys: Dict[Tuple[str, str, str], List[str]] = {}
        self._commentary_cache: Dict[str, Tuple[str, str, str, str, str]] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Event ID mapping
    # ------------------------------------------------------------------

    def get_event_id_from_moment(self, moment: ScoreMoment, state: SpokenScoreState, previous_state: Optional[SpokenScoreState]) -> str:
        if moment in (ScoreMoment.POINT_A, ScoreMoment.POINT_B):
            return "point_scored"
        if moment == ScoreMoment.DEUCE:
            return "deuce"
        if moment in (ScoreMoment.ADVANTAGE_A, ScoreMoment.ADVANTAGE_B):
            return "advantage"
        if moment in (ScoreMoment.GAME_POINT_A, ScoreMoment.GAME_POINT_B):
            return "game_point"
        if moment in (ScoreMoment.GAME_WON_A, ScoreMoment.GAME_WON_B):
            return "set_win"
        if moment in (ScoreMoment.MATCH_WON_A, ScoreMoment.MATCH_WON_B):
            return "match_win"
        if moment in (ScoreMoment.STREAK_A, ScoreMoment.STREAK_B):
            return "streak"
        if moment in (ScoreMoment.COMEBACK_A, ScoreMoment.COMEBACK_B):
            return "comeback"
        if moment == ScoreMoment.UNDO:
            return "undo"
        if moment == ScoreMoment.RESET:
            return "reset"
        if self._detect_lead_change(state, previous_state):
            return "lead_change"
        if self._detect_serve_change(state, previous_state):
            return "serve"
        return "unknown"

    def _detect_lead_change(self, state: SpokenScoreState, previous_state: Optional[SpokenScoreState]) -> bool:
        if previous_state is None:
            return False
        prev_leader = "A" if previous_state.score_a > previous_state.score_b else ("B" if previous_state.score_b > previous_state.score_a else None)
        curr_leader = "A" if state.score_a > state.score_b else ("B" if state.score_b > state.score_a else None)
        if prev_leader and curr_leader and prev_leader != curr_leader:
            return True
        return False

    def _detect_serve_change(self, state: SpokenScoreState, previous_state: Optional[SpokenScoreState]) -> bool:
        if previous_state is None:
            return False
        prev_server = getattr(previous_state, "serving_player", None)
        curr_server = getattr(state, "serving_player", None)
        if prev_server is not None and curr_server is not None and prev_server != curr_server:
            return True
        return False

    # ------------------------------------------------------------------
    # Score moment classification
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

    # ------------------------------------------------------------------
    # Silence / frequency rules
    # ------------------------------------------------------------------

    def should_generate(
        self,
        event_type: str,
        importance: ImportanceLevel,
        mode: CommentaryMode,
        intensity: CommentaryIntensity,
    ) -> bool:
        """Determine whether commentary should be generated for this event."""
        if mode == CommentaryMode.OFF:
            return False
        if mode == CommentaryMode.VISUAL_ONLY:
            return True
        if mode == CommentaryMode.IMPORTANT_ONLY:
            return importance in (ImportanceLevel.IMPORTANT, ImportanceLevel.CRITICAL)
        if mode == CommentaryMode.AFTER_EVERY_GAME:
            return event_type in ("set_win", "match_win", "result_submitted")
        if mode == CommentaryMode.EVERY_POINT:
            return True
        if mode == CommentaryMode.SPOKEN:
            if intensity == CommentaryIntensity.LOW:
                return importance == ImportanceLevel.CRITICAL
            if intensity == CommentaryIntensity.MEDIUM:
                return importance in (ImportanceLevel.IMPORTANT, ImportanceLevel.CRITICAL)
            if intensity == CommentaryIntensity.HIGH:
                return True
        return False

    # ------------------------------------------------------------------
    # Template lookup
    # ------------------------------------------------------------------

    def get_templates(self, event_id: str, language: str, style: str) -> List[Dict]:
        """Return templates from the library for the given event/language/style."""
        event_lib = TEMPLATE_LIBRARY.get(event_id, {})
        lang_lib = event_lib.get(language, {})
        templates = lang_lib.get(style, [])
        if templates:
            return list(templates)
        fallback_style = CommentaryStyle.NEUTRAL.value
        templates = lang_lib.get(fallback_style, [])
        return list(templates)

    def format_score_spoken(self, state: SpokenScoreState, language: str = "en") -> str:
        """Format score as spoken string, e.g. '5 to 3' or '11 to 8'."""
        return f"{state.score_a} to {state.score_b}"

    @staticmethod
    def _format_score(state: SpokenScoreState, language: str) -> str:
        if language == "lt":
            return f"{state.score_a}\u2013{state.score_b}"
        return f"{state.score_a} to {state.score_b}"

    @staticmethod
    def _format_sets(sets_a: int, sets_b: int, language: str) -> str:
        if language == "lt":
            return f"{sets_a} : {sets_b}"
        return f"{sets_a} to {sets_b}"

    def _select_base_template(self, event_id: str, language: str, style: str) -> Tuple[List[str], bool, Optional[str]]:
        t = self.get_templates(event_id, language, style)
        if t:
            return [x["text"] for x in t], False, None
        t = self.get_templates(event_id, language, "neutral")
        if t:
            return [x["text"] for x in t], True, "neutral_fallback"
        generic = LITHUANIAN_GENERIC_TEMPLATES if language == "lt" else ENGLISH_GENERIC_TEMPLATES
        g = generic.get(event_id)
        if g:
            return list(g), True, "generic_fallback"
        return [SAFE_MESSAGE.get(language, SAFE_MESSAGE["en"])], True, "safe_message"

    def _regenerate_lt_neutral(self, event_id: str, format_vars: dict) -> str:
        templates, _, _ = self._select_base_template(event_id, "lt", "neutral")
        for tmpl in templates:
            try:
                return tmpl.format(**format_vars)
            except KeyError:
                continue
        return SAFE_MESSAGE["lt"]

    @staticmethod
    def _lt_game_ordinal(n: int) -> str:
        return f"{n}-ą"

    @staticmethod
    def _normalize_language(language: str) -> str:
        normalized = language.strip().lower()
        if normalized in {"lt", "lithuanian", "lietuvių", "lithuanian (lt)"}:
            return "lt"
        if normalized in {"en", "english", "english (en)"}:
            return "en"
        return "en"

    def get_commentary_templates(
        self,
        style: CommentaryStyle,
        moment: ScoreMoment,
        verbosity: CommentaryVerbosity,
    ) -> List[str]:
        """Return list of template strings for the given style/moment/verbosity (legacy)."""
        if verbosity == CommentaryVerbosity.SILENT or style == CommentaryStyle.SILENT:
            return []

        if style == CommentaryStyle.MINIMAL:
            key = (moment, verbosity)
            templates = LEGACY_MINIMAL_TEMPLATES.get(key, [])
            if templates:
                return templates
            return []

        if style == CommentaryStyle.KIDS:
            key = (moment, verbosity)
            templates = LEGACY_KIDS_TEMPLATES.get(key)
            if templates:
                return templates
            fallback_key = (moment, CommentaryStyle.NEUTRAL, verbosity)
            return LEGACY_TEMPLATES.get(fallback_key, [])

        if style == CommentaryStyle.COACH:
            key = (moment, verbosity)
            templates = LEGACY_COACH_TEMPLATES.get(key)
            if templates:
                return templates

        if style == CommentaryStyle.ANNOUNCER:
            key = (moment, verbosity)
            templates = LEGACY_ANNOUNCER_TEMPLATES.get(key)
            if templates:
                return templates

        key = (moment, style, verbosity)
        templates = LEGACY_TEMPLATES.get(key, [])
        if templates:
            return templates

        fallback_key = (moment, CommentaryStyle.NEUTRAL, verbosity)
        return LEGACY_TEMPLATES.get(fallback_key, [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def choose_commentary_template(self, templates: List[str]) -> str:
        """Pick a template deterministically (first match, or random if multiple)."""
        if not templates:
            return ""
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
        event_id_str = self.get_event_id_from_moment(moment, state, previous_state)
        language = self._normalize_language(settings.language)
        style_str = settings.style.value

        score_key = f"{state.score_a}-{state.score_b}"
        sets_key = f"{state.sets_a}-{state.sets_b}"

        cache_payload = {
            "language": language,
            "style": style_str,
            "event_id": event_id_str,
            "score": score_key,
            "sets": sets_key,
            "player": state.player_a if moment in (ScoreMoment.POINT_A, ScoreMoment.GAME_WON_A, ScoreMoment.MATCH_WON_A, ScoreMoment.ADVANTAGE_A, ScoreMoment.GAME_POINT_A, ScoreMoment.STREAK_A, ScoreMoment.COMEBACK_A) else state.player_b,
        }
        cache_key = hashlib.sha256(json.dumps(cache_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        with self._cache_lock:
            cached = self._commentary_cache.get(cache_key)
        if cached is not None:
            generated_text, final_text, tpl_lang, tpl_style, base_tmpl = cached
            return CommentaryLine(
                text=final_text,
                event_type=event_type,
                priority=3 if moment in (
                    ScoreMoment.GAME_WON_A, ScoreMoment.GAME_WON_B,
                    ScoreMoment.MATCH_WON_A, ScoreMoment.MATCH_WON_B,
                    ScoreMoment.DEUCE, ScoreMoment.ADVANTAGE_A, ScoreMoment.ADVANTAGE_B,
                    ScoreMoment.GAME_POINT_A, ScoreMoment.GAME_POINT_B,
                ) else 2,
                should_speak=True,
                dedupe_key=f"{event_type}:{event_id}",
                event_id=event_id,
                ssml_text=final_text,
                generated_text=generated_text,
                final_text=final_text,
                template_language=tpl_lang,
                template_style=tpl_style,
                base_template=base_tmpl,
                cache_key=cache_key,
                cache_hit=True,
                selected_language=settings.language,
                normalized_language=language,
                event_id_str=event_id_str,
            )

        from tournament_platform.app.services.commentary.generator import CommentaryTextGenerator
        generator = CommentaryTextGenerator(rewriter=self.rewriter)
        line = generator.generate(
            event_type=event_type,
            moment=moment,
            state=state,
            settings=settings,
            event_id_str=event_id_str,
            event_id=event_id,
            previous_state=previous_state,
            recent_store=self._recent_template_keys,
        )
        line.cache_key = cache_key
        line.cache_hit = False

        with self._cache_lock:
            self._commentary_cache[cache_key] = (
                line.generated_text or "",
                line.final_text or "",
                line.template_language or "",
                line.template_style or "",
                line.base_template or "",
            )

        return line

    def build_set_win_commentary(
        self,
        game_event: dict,
        settings: CommentarySettings,
    ) -> CommentaryLine:
        """Build a deterministic set_win CommentaryLine from engine.round_scores data.

        Args:
            game_event: dict with keys:
                event_id (default "set_win", accept "game_won"),
                game_number: int,
                winner: str,
                loser: str,
                game_score: str (e.g. "11–5"),
                match_score: str,
                completed_games: List[str],
                language: str,
                style: str,
                match_id: str (optional, default "none").
            settings: user commentary settings.
        """
        event_id = game_event.get("event_id", "set_win")
        game_number = int(game_event.get("game_number", 1))
        winner = game_event.get("winner", "")
        loser = game_event.get("loser", "")
        game_score = game_event.get("game_score", "")
        match_score = game_event.get("match_score", "")
        completed_games = game_event.get("completed_games", [])
        language = self._normalize_language(game_event.get("language", settings.language))
        style = game_event.get("style", settings.style.value)
        match_id = game_event.get("match_id", "none")

        # Prefer the dedicated phrase-bank module; fall back to the legacy
        # TEMPLATE_LIBRARY lookup if it yields nothing.
        set_variables = {
            "winner": winner,
            "loser": loser,
            "game_number": game_number if language == "en" else self._lt_game_ordinal(game_number),
            "game_score": game_score,
            "match_score": match_score,
            "player_a": game_event.get("player_a", winner),
            "player_b": game_event.get("player_b", loser),
            "score": game_score,
            "set": game_number,
            "streak_count": 1,
            "server": game_event.get("player_a", winner),
            "receiver": game_event.get("player_b", loser),
            "leader": winner,
            "trailer": loser,
            "lead": 0,
            "stage": f"game {game_number}",
        }
        _chosen, generated_text, _ = _ct_module.select_event_template(
            "set_win", language, style, settings.verbosity, set_variables,
            recent_store=self._recent_template_keys,
        )
        base_template = _chosen or ""

        if not generated_text:
            templates = self.get_templates("set_win", language, style)
            if not templates:
                templates = self.get_templates("set_win", language, "neutral")
            generated_text = ""
            base_template = ""
            for tmpl in templates:
                try:
                    generated_text = tmpl["text"].format(**set_variables)
                    base_template = tmpl["text"]
                    break
                except KeyError:
                    continue

        if not generated_text:
            generated_text = SAFE_MESSAGE.get(language, SAFE_MESSAGE["en"])
            base_template = generated_text

        final_text = generated_text
        used_ollama = False

        if settings.ollama_rewrite_enabled and generated_text and generated_text not in (
            SAFE_MESSAGE.get("en", ""),
            SAFE_MESSAGE.get("lt", ""),
        ):
            facts = {
                "winner": winner,
                "loser": loser,
                "set": str(game_number),
                "score": game_score,
                "language": language,
                "match_id": str(match_id),
            }
            rewritten, used_ollama = self.rewriter.rewrite(
                generated_text, facts, style, language, "set_win"
            )
            if used_ollama:
                final_text = rewritten

        tts_language_code = "lt-LT" if language == "lt" else "en-US"
        speech_event_id = f"{match_id}-set-win-{game_number}-{int(time.time() * 1000)}"
        dedupe_key = f"set_win:{game_number}:{winner}:{game_score}"

        return CommentaryLine(
            text=final_text,
            event_type="set_win",
            priority=3,
            should_speak=False,
            dedupe_key=dedupe_key,
            event_id=speech_event_id,
            generated_text=generated_text,
            final_text=final_text,
            template_language=language,
            template_style=style,
            base_template=base_template,
            used_ollama=used_ollama,
            tts_language_code=tts_language_code,
            selected_language=settings.language,
            normalized_language=language,
            event_id_str="set_win",
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
            if state.match_history:
                last = state.match_history[-1]
                if last.get("action") == "point_added":
                    return last.get("player")
            return None

        if (
            state.score_a > previous_state.score_a
            and state.score_b > previous_state.score_b
        ):
            if state.match_history:
                last = state.match_history[-1]
                if last.get("action") == "point_added":
                    return last.get("player")
            return None

        if state.score_a > previous_state.score_a:
            return "A"
        if state.score_b > previous_state.score_b:
            return "B"

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
