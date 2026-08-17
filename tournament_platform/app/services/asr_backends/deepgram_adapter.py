"""
Deepgram Adapter — Transcript normalization + keyterm construction.

Pure functions, no SDK or Streamlit imports, so they can be unit-tested
in complete isolation.  See plan §2.2 and §5.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from tournament_platform.app.services.voice_parser import _NUMBER_WORDS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language-specific command vocabularies
# ---------------------------------------------------------------------------

_EN_CORE_COMMANDS: list[str] = [
    "point red", "point blue", "point player one", "point player two",
    "point to red", "point to blue", "point to player one", "point to player two",
    "undo", "take back", "remove point", "take that back",
    "what is the score", "what's the score", "repeat score",
    "start match", "begin", "pause", "resume", "continue",
    "next game", "new game", "end game", "game over",
    "end timeout", "resume play", "timeout", "time out",
    "who serves", "server", "player one serves", "player two serves",
    "confirm", "yes", "accept", "cancel", "no", "abort",
    "set score", "score",
    "dashboard", "bracket", "rankings", "ranking",
    "public board", "current match", "scoring", "help",
    "call next match", "table ready", "assign table",
    "mark unavailable", "publish result",
    "mark no show", "drop player", "start next round",
    "rules", "ask rules", "question",
    "repeat", "louder", "quieter", "mute", "unmute",
    "slower", "faster", "large text", "high contrast",
    "accessibility help", "voice help", "show help",
]


_LT_CORE_COMMANDS: list[str] = [
    "taškas", "taškus", "taško", "tašką", "atšaukti", "atšaukia",
    "kairė", "kairės", "dešinė", "dešinės",
    "rezultatas", "rezultato",
    "pradėti", "pradėk", "žaisti", "pauzė",
    "atsaukti", "atsaukus", "atgal",
    "kita", "kita rungtinė", "nauja", "nauja rungtinė",
    "pabaiga", "rungtinė pabaiga",
    "laikas", "laiko", "pertrauka",
    "kas serve", "serveris", "pirmasis", "antras",
    "patvirtinti", "taip", "priimti", "atšaukti", "ne", "nutraukti",
    "nustatyti", "rezultatą", "įrašyti",
    "desnis", "desnei", "mažiau",
    "pakartok", "garsiau", "tiksliau",
    "pagalbos", "menui", "pagrindas", "lentelė", "įvertinimai",
]


_EN_NUMBERS: list[str] = [
    "zero", "oh", "love", "one", "two", "to", "too",
    "three", "four", "for", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "twenty one", "twenty-one",
]

_LT_NUMBERS: list[str] = [
    "nulis", "vienas", "du", "dvi", "trys", "trys", "keturi",
    "penki", "šeši", "septyni", "aštuoni", "devyni",
    "dešimt", "vienuolika", "dvylika", "trylika", "keturiolika",
    "penkiolika", "šešiolika", "septyniolika", "aštuolika",
    "devyniolika", "dvidešimt", "dvidešimt vienas",
    "dvidešimt du", "dvidešimt trys", "dvidešimt keturi",
    "dvidešimt penki", "dvidešimt šeši", "dvidešimt septyni",
]

_LT_SIDE_TERMS: list[str] = [
    "kairė", "kairės", "dešinė", "dešinės",
    "raudonas", "raudona", "mėlynas", "mėlyna",
    "žalias", "žalia", "oranžinis", "raudonas",
    "pirmasis", "antras", "pirmasis žaidėjas", "antras žaidėjas",
    "komandos", "komanda", "žaidėjas", "žaidėjai",
]

_EN_SIDE_TERMS: list[str] = [
    "red", "blue", "player one", "player two",
    "player a", "player b", "team a", "team b",
    "side a", "side b", "first player", "second player",
    "home", "away", "team", "players",
]

_TOURNAMENT_TERMS: list[str] = [
    "tournament", "match", "set", "game", "round", "rounds",
    "scoreboard", "table", "table tennis", "ping pong",
    "turnymas", "rungtinė", "kėlinys", "runda", "lentelė",
]

# Phonetic / common ASR homophones for numbers
_NUMBER_HOMOPHONES: list[str] = [
    "won", "wan", "for", "fore", "to", "too", "two", "tu", "tú",
    "ate", "eight", "ait", "ait",
    "nine", "nien", "tine",
]


@dataclass(frozen=True)
class KeytermResult:
    terms: tuple[str, ...]
    count: int
    truncated: int = 0
    truncated_terms: tuple[str, ...] = ()
    version_hash: str = ""

    def serialize(self) -> list[tuple[str, str]]:
        """Produce repeated ('keyterm', term) tuples for URL serialization."""
        return [("keyterm", t) for t in self.terms]


def _strip_punctuation(term: str) -> str:
    """Strip surrounding punctuation and quotes from a keyterm."""
    return term.strip(".,!?;:\"'()[]{}").strip()


def _normalize_for_dedup(term: str) -> str:
    """Case-fold + whitespace-collapse for deduplication only."""
    term = unicodedata.normalize("NFC", term)
    term = re.sub(r"\s+", " ", term)
    return term.casefold()


def build_deepgram_keyterms(
    *,
    player_names: Sequence[str] = (),
    language: str = "lt",
    team_names: Sequence[str] = (),
    custom_terms: Sequence[str] = (),
    max_terms: int = 100,
    include_numbers: bool = True,
) -> KeytermResult:
    """Build a prioritized Deepgram keyterm list.

    Priority order (plan §7):
    1. Current match player names
    2. Core score commands (LT/EN)
    3. Numbers and variants (0–21, homophones)
    4. Side/player-selection terms
    5. Tournament terminology
    6. Optional custom terms

    Rules:
    - Strip punctuation/quotes, normalize whitespace, case-fold for dedup only
    - Hard cap: ``max_terms`` (default 100)
    - Truncation preserves priority order (keep player names → commands → numbers)
    - Log warning on truncation
    """
    lang = language.strip().lower()
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(term: str) -> None:
        cleaned = _strip_punctuation(term)
        if not cleaned:
            return
        key = _normalize_for_dedup(cleaned)
        if key in seen:
            return
        seen.add(key)
        ordered.append(cleaned)

    # Priority 1: Player names
    for name in player_names:
        _add(name)
    for name in team_names:
        _add(name)

    # Priority 2: Core score commands for the active language
    if lang == "lt":
        for cmd in _LT_CORE_COMMANDS:
            _add(cmd)
    else:
        for cmd in _EN_CORE_COMMANDS:
            _add(cmd)

    # Priority 3: Numbers (cross-language homophones included)
    if include_numbers:
        all_numbers = _EN_NUMBERS + _LT_NUMBERS + _NUMBER_HOMOPHONES
        for num in all_numbers:
            _add(num)

    # Priority 4: Side / player-selection terms for the active language
    if lang == "lt":
        for term in _LT_SIDE_TERMS:
            _add(term)
    else:
        for term in _EN_SIDE_TERMS:
            _add(term)
    for color in ("red", "blue", "teal", "green", "orange", "read"):
        _add(color)

    # Priority 5: Tournament terminology
    for term in _TOURNAMENT_TERMS:
        _add(term)

    # Priority 6: Optional custom terms
    for term in custom_terms:
        _add(term)

    truncated_terms: tuple[str, ...] = ()
    truncated = 0
    if len(ordered) > max_terms:
        truncated_terms = tuple(ordered[max_terms:])
        truncated = len(ordered) - max_terms
        ordered = ordered[:max_terms]
        logger.warning(
            "Deepgram keyterms truncated from %d to %d (dropped: %s)",
            len(ordered) + truncated,
            max_terms,
            ", ".join(truncated_terms[:5]),
        )

    version_hash = hashlib.sha256(
        "|".join(ordered).encode("utf-8")
    ).hexdigest()[:16]

    return KeytermResult(
        terms=tuple(ordered),
        count=len(ordered),
        truncated=truncated,
        truncated_terms=truncated_terms,
        version_hash=version_hash,
    )


class DeepgramAdapter:
    """Pure functions for transcript post-processing from Deepgram.

    - NFC Unicode normalization (Lithuanian diacritics)
    - Whitespace collapse
    - Numeral formatting
    - Metadata preservation (interim vs final, confidence)
    """

    def normalize(self, text: str) -> str:
        """Normalize a transcript: NFC strip + whitespace collapse."""
        if not text:
            return ""
        text = unicodedata.normalize("NFC", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def process_transcript(self, text: str, *, is_interim: bool = False) -> str:
        """Full post-processing pipeline for a Deepgram transcript.

        Interim transcripts are normalized but not converted to numerals
        (they are diagnostics only; never enter the scoring queue).
        """
        if not text:
            return ""
        normalized = self.normalize(text)
        if not is_interim:
            normalized = self._format_numerals(normalized)
        return normalized

    def _format_numerals(self, text: str) -> str:
        """Convert number words to digits where the parser expects them."""
        words = text.split()
        result: list[str] = []
        for word in words:
            lower = word.lower().strip(".,!?")
            if lower in _NUMBER_WORDS:
                result.append(str(_NUMBER_WORDS[lower]))
            else:
                result.append(word)
        return " ".join(result)

    def extract_transcript(self, message: object) -> str:
        """Extract the primary transcript from a Deepgram Listen v1 Results message."""
        if isinstance(message, dict):
            channel = message.get("channel")
            if not channel:
                return ""
            alternatives = channel.get("alternatives")
            if alternatives and len(alternatives) > 0:
                return alternatives[0].get("transcript", "") or ""
            return ""

        alternatives = (
            getattr(message, "channel", None)
            and getattr(message.channel, "alternatives", None)
        )
        if alternatives and len(alternatives) > 0:
            return getattr(alternatives[0], "transcript", "") or ""
        return ""

    def is_final(self, message: object) -> bool:
        """Check if a Deepgram message has is_final=True."""
        if isinstance(message, dict):
            return bool(message.get("is_final"))
        return bool(getattr(message, "is_final", None))

    def is_speech_final(self, message: object) -> bool:
        """Check if a Deepgram message has speech_final=True."""
        if isinstance(message, dict):
            return bool(message.get("speech_final"))
        return bool(getattr(message, "speech_final", None))

    def extract_confidence(self, message: object) -> float:
        """Extract the primary alternative's confidence (0.0 to 1.0)."""
        if isinstance(message, dict):
            channel = message.get("channel")
            if not channel:
                return 0.0
            alternatives = channel.get("alternatives")
            if alternatives and len(alternatives) > 0:
                return float(alternatives[0].get("confidence", 0.0))
            return 0.0

        alternatives = (
            getattr(message, "channel", None)
            and getattr(message.channel, "alternatives", None)
        )
        if alternatives and len(alternatives) > 0:
            return float(getattr(alternatives[0], "confidence", 0.0))
        return 0.0
