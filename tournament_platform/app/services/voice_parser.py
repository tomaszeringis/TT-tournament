"""
Voice Score Parser

Parses voice transcripts into structured score events for table tennis scoring.
Handles ASR mistakes, number word normalization, and command recognition.
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VoiceScoreEvent:
    """Structured event parsed from a voice transcript.

    Core fields (type/score/player/raw_text/confidence) are unchanged for
    backward compatibility. Extended metadata fields support observability,
    speaker identification, and future LLM/multilingual routing without
    altering scoring behavior.
    """
    type: str  # "set_score", "increment", "undo", "unknown", "repeat", "stop_listening"
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    player: Optional[str] = None  # "A" or "B"
    raw_text: str = ""
    confidence: float = 0.0
    # --- Extended metadata (Phase 1 hardening; all optional, non-breaking) ---
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    source: str = "asr"  # "asr" | "llm" | "manual" | "debug" | "push_to_talk" | "continuous"
    session_id: Optional[str] = None  # continuous listening session ID for stale event detection
    uncertainty: float = 0.0  # higher = less certain; convenience for observability
    speaker_label: Optional[str] = None  # Phase 2 (speaker identification)
    language: str = "en"  # reserved; multilingual not implemented per directive
    requires_confirmation: bool = False  # Phase 4/7 (TTS/LLM confirmation)
    asr_latency_ms: Optional[float] = None  # Phase 5/9 observability
    noise_rms: Optional[float] = None  # Phase 5 observability


# Number word to digit mapping
_NUMBER_WORDS = {
    "zero": 0, "oh": 0, "love": 0,
    "one": 1,
    "two": 2, "to": 2, "too": 2,
    "three": 3,
    "four": 4, "for": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty one": 21, "twenty-one": 21,
}


def _normalize_number_words(text: str) -> str:
    """
    Normalize common ASR mistakes and number words in text.
    
    - "for" → "four" when used as a standalone word or in score context
    - "to"/"too" → "two" when used as a standalone word or in score context
    - "oh"/"zero"/"love" → "0"
    - Other number words → digits
    """
    words = text.split()
    normalized = []
    
    for word in words:
        lower = word.lower().strip(".,!?")
        if lower in _NUMBER_WORDS:
            normalized.append(str(_NUMBER_WORDS[lower]))
        else:
            normalized.append(word)
    
    return " ".join(normalized)


def _extract_score_pair(text: str) -> Optional[tuple[int, int]]:
    """
    Extract a pair of scores from text.
    
    Supports formats:
    - "five four" → (5, 4)
    - "6 4" → (6, 4)
    - "ten-eight" → (10, 8)
    - "11 9" → (11, 9)
    """
    # First, try to find two consecutive number words or digits
    tokens = text.lower().split()
    
    numbers = []
    for token in tokens:
        token = token.strip(".,!?-")
        if token in _NUMBER_WORDS:
            numbers.append(_NUMBER_WORDS[token])
        elif token.isdigit():
            numbers.append(int(token))
    
    if len(numbers) >= 2:
        return (numbers[0], numbers[1])
    
    # Try regex for patterns like "10-8" or "10 - 8"
    match = re.search(r'(\d+)\s*[-–]\s*(\d+)', text)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    
    return None


def _is_deuce_allowed(score_a: int, score_b: int) -> bool:
    """
    Check if deuce is a valid state given current scores.
    Deuce is only valid when both players have at least 10 points.
    """
    return score_a >= 10 and score_b >= 10


class VoiceParser:
    """
    Parses voice transcripts into structured score events.
    
    Supported phrases:
    - "five four" → set_score 5-4
    - "six all" → set_score 6-6
    - "ten eight" → set_score 10-8
    - "eleven nine" → set_score 11-9
    - "deuce" → set_score (equal) if current score allows it
    - "set score seven five" → set_score 7-5
    - "point player one" → increment A
    - "last point to player two" → increment B
    - "undo" → undo
    """
    
    # Command patterns (checked before score patterns)
    _UNDO_PATTERNS = [
        r"\bundo\b",
        r"\btake\s+back\b",
        r"\bremove\s+point\b",
        r"\btake\s+that\s+back\b",
    ]
    
    # Point/increment patterns - order matters, more specific first
    _POINT_PATTERNS = [
        # "point to player one" / "point to player 1" / "point to player a"
        (r"\bpoint\s+to\s+player\s+(one|1|a)\b", "A"),
        (r"\bpoint\s+to\s+player\s+(two|2|b)\b", "B"),
        # "last point to player one" etc.
        (r"\blast\s+point\s+to\s+player\s+(one|1|a)\b", "A"),
        (r"\blast\s+point\s+to\s+player\s+(two|2|b)\b", "B"),
        # "point player one" / "point player 1" / "point player a"
        (r"\bpoint\s+player\s+(one|1|a)\b", "A"),
        (r"\bpoint\s+player\s+(two|2|b)\b", "B"),
        # "last point player one" etc.
        (r"\blast\s+point\s+player\s+(one|1|a)\b", "A"),
        (r"\blast\s+point\s+player\s+(two|2|b)\b", "B"),
        # "player one scores" / "player 1 scores" / "player a scores"
        (r"\bplayer\s+(one|1|a)\s+scores?\b", "A"),
        (r"\bplayer\s+(two|2|b)\s+scores?\b", "B"),
        # "player one" / "player 1" / "player a" (with point context from earlier keywords)
        (r"\bplayer\s+(one|1|a)\b", "A"),
        (r"\bplayer\s+(two|2|b)\b", "B"),
    ]

    # Color aliases (PingScore-style command design):
    # blue/teal/green -> Player A point; red/orange/read -> Player B point.
    # "read" covers ASR mis-transcription of "red".
    _COLOR_ALIAS_PATTERNS = [
        (r"\b(blue|teal|green)\b", "A"),
        (r"\b(red|orange|read)\b", "B"),
    ]
    
    _SET_SCORE_PATTERNS = [
        r"\bset\s+score\s+(.+)",
        r"\bset\s+the\s+score\s+(.+)",
    ]
    
    def parse(
        self,
        transcript: str,
        current_score_a: int = 0,
        current_score_b: int = 0,
    ) -> VoiceScoreEvent:
        """
        Parse a voice transcript into a structured score event.

        Args:
            transcript: Raw text from ASR
            current_score_a: Current score for player A (for deuce validation)
            current_score_b: Current score for player B (for deuce validation)

        Returns:
            VoiceScoreEvent with parsed intent and values
        """
        from tournament_platform.app.services.voice.commands import parse as _grammar_parse

        result = _grammar_parse(transcript, current_score_a, current_score_b)
        return result.to_score_event()
