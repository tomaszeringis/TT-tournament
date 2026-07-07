"""
Voice Score Parser

Parses voice transcripts into structured score events for table tennis scoring.
Handles ASR mistakes, number word normalization, and command recognition.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class VoiceScoreEvent:
    """Structured event parsed from a voice transcript."""
    type: str  # "set_score", "increment", "undo", "unknown"
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    player: Optional[str] = None  # "A" or "B"
    raw_text: str = ""
    confidence: float = 0.0


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
        if not transcript or not transcript.strip():
            return VoiceScoreEvent(type="unknown", raw_text=transcript or "", confidence=0.0)
        
        raw = transcript.strip()
        text = raw.lower()
        
        # Normalize number words for score extraction
        normalized = _normalize_number_words(text)
        
        # Check for undo commands (on original text to avoid false positives)
        for pattern in self._UNDO_PATTERNS:
            if re.search(pattern, text):
                return VoiceScoreEvent(
                    type="undo",
                    raw_text=raw,
                    confidence=0.9,
                )
        
        # Check for point/increment commands (on original text)
        for pattern, player in self._POINT_PATTERNS:
            if re.search(pattern, text):
                return VoiceScoreEvent(
                    type="increment",
                    player=player,
                    raw_text=raw,
                    confidence=0.85,
                )
        
        # Check for "set score X Y" explicit pattern (on normalized text)
        for pattern in self._SET_SCORE_PATTERNS:
            match = re.search(pattern, normalized)
            if match:
                score_text = match.group(1)
                pair = _extract_score_pair(score_text)
                if pair:
                    return VoiceScoreEvent(
                        type="set_score",
                        score_a=pair[0],
                        score_b=pair[1],
                        raw_text=raw,
                        confidence=0.9,
                    )
        
        # Check for "deuce"
        if re.search(r"\bdeuce\b", text):
            if _is_deuce_allowed(current_score_a, current_score_b):
                return VoiceScoreEvent(
                    type="set_score",
                    score_a=current_score_a,
                    score_b=current_score_b,
                    raw_text=raw,
                    confidence=0.8,
                )
            else:
                # Deuce not valid at current score
                return VoiceScoreEvent(
                    type="unknown",
                    raw_text=raw,
                    confidence=0.3,
                )
        
        # Check for "all" (e.g., "six all" → 6-6)
        if "all" in text.split():
            # Try to extract a number before "all"
            tokens = text.split()
            for i, token in enumerate(tokens):
                if token == "all" and i > 0:
                    prev = tokens[i - 1]
                    if prev in _NUMBER_WORDS:
                        score = _NUMBER_WORDS[prev]
                        return VoiceScoreEvent(
                            type="set_score",
                            score_a=score,
                            score_b=score,
                            raw_text=raw,
                            confidence=0.85,
                        )
                    elif prev.isdigit():
                        score = int(prev)
                        return VoiceScoreEvent(
                            type="set_score",
                            score_a=score,
                            score_b=score,
                            raw_text=raw,
                            confidence=0.85,
                        )
        
        # Check for direct score pair (e.g., "five four", "10 8", "11-9")
        # Use normalized text for number word matching
        pair = _extract_score_pair(normalized)
        if pair:
            return VoiceScoreEvent(
                type="set_score",
                score_a=pair[0],
                score_b=pair[1],
                raw_text=raw,
                confidence=0.8,
            )
        
        # Check for single number (could be "point to player one" without "point")
        # This is handled by the point patterns above, but as a fallback:
        if "player one" in text or "player 1" in text or "player a" in text:
            return VoiceScoreEvent(
                type="increment",
                player="A",
                raw_text=raw,
                confidence=0.5,
            )
        if "player two" in text or "player 2" in text or "player b" in text:
            return VoiceScoreEvent(
                type="increment",
                player="B",
                raw_text=raw,
                confidence=0.5,
            )
        
        return VoiceScoreEvent(
            type="unknown",
            raw_text=raw,
            confidence=0.0,
        )
