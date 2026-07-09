"""
Voice Command Grammar

Canonical intent enum and pattern matcher for table-tennis voice commands.
Replaces ad-hoc VoiceParser patterns; keeps normalization helpers for reuse.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from tournament_platform.app.services.voice_parser import (
    _NUMBER_WORDS,
    _extract_score_pair,
    _is_deuce_allowed,
    _normalize_number_words,
)


class VoiceIntent(str, Enum):
    SCORE_POINT = "score_point"
    SET_SCORE = "set_score"
    UNDO = "undo"
    REPEAT_SCORE = "repeat_score"
    START_MATCH = "start_match"
    PAUSE_MATCH = "pause_match"
    RESUME_MATCH = "resume_match"
    START_NEXT_GAME = "start_next_game"
    END_GAME = "end_game"
    TIMEOUT_START = "timeout_start"
    TIMEOUT_END = "timeout_end"
    SERVER_CHECK = "server_check"
    SET_SERVER = "set_server"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


# Safety levels used by ConfirmationPolicy
_SAFETY_MAP = {
    VoiceIntent.SCORE_POINT: "simple",
    VoiceIntent.SET_SCORE: "medium",
    VoiceIntent.UNDO: "safe",
    VoiceIntent.REPEAT_SCORE: "read_only",
    VoiceIntent.START_MATCH: "medium",
    VoiceIntent.PAUSE_MATCH: "medium",
    VoiceIntent.RESUME_MATCH: "medium",
    VoiceIntent.START_NEXT_GAME: "medium",
    VoiceIntent.END_GAME: "medium",
    VoiceIntent.TIMEOUT_START: "medium",
    VoiceIntent.TIMEOUT_END: "medium",
    VoiceIntent.SERVER_CHECK: "read_only",
    VoiceIntent.SET_SERVER: "medium",
    VoiceIntent.CONFIRM: "control",
    VoiceIntent.CANCEL: "control",
    VoiceIntent.UNKNOWN: "unknown",
}


# Command patterns: (intent, regex_pattern, confidence, slot_extractors)
# Slot extractors map slot name -> callable(match) -> value
_COMMAND_PATTERNS: List[tuple] = [
    (VoiceIntent.UNDO, r"\bundo\b", 0.9, {}),
    (VoiceIntent.UNDO, r"\btake\s+back\b", 0.85, {}),
    (VoiceIntent.UNDO, r"\bremove\s+point\b", 0.85, {}),
    (VoiceIntent.UNDO, r"\btake\s+that\s+back\b", 0.85, {}),
    (VoiceIntent.REPEAT_SCORE, r"\bwhat'?s\s+the\s+score\b", 0.9, {}),
    (VoiceIntent.REPEAT_SCORE, r"\brepeat\s+score\b", 0.9, {}),
    (VoiceIntent.START_MATCH, r"\bstart\s+match\b", 0.85, {}),
    (VoiceIntent.START_MATCH, r"\bbegin\b", 0.7, {}),
    (VoiceIntent.PAUSE_MATCH, r"\bpause\b", 0.8, {}),
    (VoiceIntent.PAUSE_MATCH, r"\btimeout\s+break\b", 0.85, {}),
    (VoiceIntent.RESUME_MATCH, r"\bresume\b", 0.8, {}),
    (VoiceIntent.RESUME_MATCH, r"\bcontinue\b", 0.75, {}),
    (VoiceIntent.START_NEXT_GAME, r"\bnext\s+game\b", 0.85, {}),
    (VoiceIntent.START_NEXT_GAME, r"\bnew\s+game\b", 0.8, {}),
    (VoiceIntent.END_GAME, r"\bend\s+game\b", 0.85, {}),
    (VoiceIntent.END_GAME, r"\bgame\s+over\b", 0.85, {}),
    (VoiceIntent.TIMEOUT_START, r"\btimeout\b", 0.85, {}),
    (VoiceIntent.TIMEOUT_START, r"\btime\s+out\b", 0.85, {}),
    (VoiceIntent.TIMEOUT_END, r"\bend\s+timeout\b", 0.85, {}),
    (VoiceIntent.TIMEOUT_END, r"\bresume\s+play\b", 0.8, {}),
    (VoiceIntent.SERVER_CHECK, r"\bwho\s+serves\?\b", 0.9, {}),
    (VoiceIntent.SERVER_CHECK, r"\bserver\?\b", 0.9, {}),
    (VoiceIntent.CONFIRM, r"\bconfirm\b", 0.9, {}),
    (VoiceIntent.CONFIRM, r"\byes\b", 0.8, {}),
    (VoiceIntent.CONFIRM, r"\baccept\b", 0.85, {}),
    (VoiceIntent.CANCEL, r"\bcancel\b", 0.9, {}),
    (VoiceIntent.CANCEL, r"\bno\b", 0.7, {}),
    (VoiceIntent.CANCEL, r"\babort\b", 0.85, {}),
]


def _extract_player(text: str) -> Optional[str]:
    lower = text.lower()
    if re.search(r"\b(player\s+)?(one|1|a)\b", lower):
        return "A"
    if re.search(r"\b(player\s+)?(two|2|b)\b", lower):
        return "B"
    return None


_COLOR_ALIAS_PATTERNS = [
    (r"\b(blue|teal|green)\b", "A"),
    (r"\b(red|orange|read)\b", "B"),
]


class VoiceCommandGrammar:
    """Parses transcripts into VoiceParseResult using intent patterns."""

    def parse(
        self,
        transcript: str,
        current_score_a: int = 0,
        current_score_b: int = 0,
    ) -> VoiceParseResult:
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult

        if not transcript or not transcript.strip():
            return VoiceParseResult(
                intent=VoiceIntent.UNKNOWN,
                confidence=0.0,
                raw_transcript=transcript or "",
            )

        raw = transcript.strip()
        text = raw.lower()
        normalized = _normalize_number_words(text)

        # Control intents first
        for intent, pattern, confidence, _ in _COMMAND_PATTERNS:
            if re.search(pattern, text):
                slots: Dict[str, Any] = {}
                if intent == VoiceIntent.SET_SCORE:
                    score_text = re.search(r"\bset\s+score\s+(.+)", normalized)
                    if score_text:
                        pair = _extract_score_pair(score_text.group(1))
                        if pair:
                            slots["score_a"] = pair[0]
                            slots["score_b"] = pair[1]
                elif intent == VoiceIntent.SET_SERVER:
                    player = _extract_player(text)
                    if player:
                        slots["player"] = player
                elif intent in (VoiceIntent.PAUSE_MATCH, VoiceIntent.TIMEOUT_START):
                    player = _extract_player(text)
                    if player:
                        slots["side"] = player
                return VoiceParseResult(
                    intent=intent,
                    slots=slots,
                    confidence=confidence,
                    safety_level=_SAFETY_MAP.get(intent, "unknown"),
                    raw_transcript=raw,
                    normalized_text=normalized,
                )

        # Color aliases
        for pattern, player in _COLOR_ALIAS_PATTERNS:
            if re.search(pattern, text):
                return VoiceParseResult(
                    intent=VoiceIntent.SCORE_POINT,
                    slots={"player": player},
                    confidence=0.85,
                    safety_level=_SAFETY_MAP[VoiceIntent.SCORE_POINT],
                    raw_transcript=raw,
                    normalized_text=normalized,
                )

        # Point/increment patterns
        _POINT_PATTERNS = [
            (r"\bpoint\s+to\s+player\s+(one|1|a)\b", "A"),
            (r"\bpoint\s+to\s+player\s+(two|2|b)\b", "B"),
            (r"\blast\s+point\s+to\s+player\s+(one|1|a)\b", "A"),
            (r"\blast\s+point\s+to\s+player\s+(two|2|b)\b", "B"),
            (r"\bpoint\s+player\s+(one|1|a)\b", "A"),
            (r"\bpoint\s+player\s+(two|2|b)\b", "B"),
            (r"\blast\s+point\s+player\s+(one|1|a)\b", "A"),
            (r"\blast\s+point\s+player\s+(two|2|b)\b", "B"),
            (r"\bplayer\s+(one|1|a)\s+scores?\b", "A"),
            (r"\bplayer\s+(two|2|b)\s+scores?\b", "B"),
            (r"\bplayer\s+(one|1|a)\b", "A"),
            (r"\bplayer\s+(two|2|b)\b", "B"),
        ]
        for pattern, player in _POINT_PATTERNS:
            if re.search(pattern, text):
                return VoiceParseResult(
                    intent=VoiceIntent.SCORE_POINT,
                    slots={"player": player},
                    confidence=0.8,
                    safety_level=_SAFETY_MAP[VoiceIntent.SCORE_POINT],
                    raw_transcript=raw,
                    normalized_text=normalized,
                )

        # Explicit set score
        _SET_SCORE_PATTERNS = [
            r"\bset\s+score\s+(.+)",
            r"\bset\s+the\s+score\s+(.+)",
        ]
        for pattern in _SET_SCORE_PATTERNS:
            match = re.search(pattern, normalized)
            if match:
                pair = _extract_score_pair(match.group(1))
                if pair:
                    return VoiceParseResult(
                        intent=VoiceIntent.SET_SCORE,
                        slots={"score_a": pair[0], "score_b": pair[1]},
                        confidence=0.9,
                        safety_level=_SAFETY_MAP[VoiceIntent.SET_SCORE],
                        raw_transcript=raw,
                        normalized_text=normalized,
                        requires_confirmation=True,
                    )

        # Deuce
        if re.search(r"\bdeuce\b", text):
            if _is_deuce_allowed(current_score_a, current_score_b):
                return VoiceParseResult(
                    intent=VoiceIntent.SET_SCORE,
                    slots={"score_a": current_score_a, "score_b": current_score_b},
                    confidence=0.8,
                    safety_level=_SAFETY_MAP[VoiceIntent.SET_SCORE],
                    raw_transcript=raw,
                    normalized_text=normalized,
                    requires_confirmation=True,
                )
            return VoiceParseResult(
                intent=VoiceIntent.UNKNOWN,
                confidence=0.3,
                disposition="deuce_not_allowed",
                raw_transcript=raw,
                normalized_text=normalized,
            )

        # "all"
        if "all" in text.split():
            tokens = text.split()
            for i, token in enumerate(tokens):
                if token == "all" and i > 0:
                    prev = tokens[i - 1]
                    score = None
                    if prev in _NUMBER_WORDS:
                        score = _NUMBER_WORDS[prev]
                    elif prev.isdigit():
                        score = int(prev)
                    if score is not None:
                        return VoiceParseResult(
                            intent=VoiceIntent.SET_SCORE,
                            slots={"score_a": score, "score_b": score},
                            confidence=0.85,
                            safety_level=_SAFETY_MAP[VoiceIntent.SET_SCORE],
                            raw_transcript=raw,
                            normalized_text=normalized,
                            requires_confirmation=True,
                        )

        # Direct score pair
        pair = _extract_score_pair(normalized)
        if pair:
            return VoiceParseResult(
                intent=VoiceIntent.SET_SCORE,
                slots={"score_a": pair[0], "score_b": pair[1]},
                confidence=0.8,
                safety_level=_SAFETY_MAP[VoiceIntent.SET_SCORE],
                raw_transcript=raw,
                normalized_text=normalized,
                requires_confirmation=True,
            )

        return VoiceParseResult(
            intent=VoiceIntent.UNKNOWN,
            confidence=0.0,
            raw_transcript=raw,
            normalized_text=normalized,
        )


# Canonical parser instance
_grammar = VoiceCommandGrammar()


def parse(
    transcript: str,
    current_score_a: int = 0,
    current_score_b: int = 0,
) -> VoiceParseResult:
    return _grammar.parse(transcript, current_score_a, current_score_b)


def intents() -> List[VoiceIntent]:
    return list(VoiceIntent)


def intent_display_name(intent: VoiceIntent) -> str:
    return intent.value.replace("_", " ").title()


def cheat_sheet() -> List[Dict[str, Any]]:
    rows = [
        (VoiceIntent.SCORE_POINT, '"point to player one"', "Player A scores"),
        (VoiceIntent.SET_SCORE, '"set score five four"', "Set score to 5-4"),
        (VoiceIntent.UNDO, '"undo"', "Undo last point"),
        (VoiceIntent.REPEAT_SCORE, '"what\'s the score?"', "Read score"),
        (VoiceIntent.START_MATCH, '"start match"', "Begin match"),
        (VoiceIntent.PAUSE_MATCH, '"pause"', "Pause / timeout"),
        (VoiceIntent.RESUME_MATCH, '"resume"', "Resume play"),
        (VoiceIntent.START_NEXT_GAME, '"next game"', "Start next game"),
        (VoiceIntent.END_GAME, '"end game"', "End current game"),
        (VoiceIntent.TIMEOUT_START, '"timeout"', "Start timeout"),
        (VoiceIntent.TIMEOUT_END, '"end timeout"', "End timeout"),
        (VoiceIntent.SERVER_CHECK, '"who serves?"', "Check server"),
        (VoiceIntent.SET_SERVER, '"player one serves"', "Set server"),
        (VoiceIntent.CONFIRM, '"confirm"', "Confirm pending"),
        (VoiceIntent.CANCEL, '"cancel"', "Cancel pending"),
    ]
    return [
        {
            "intent": intent.value,
            "example": example,
            "description": description,
        }
        for intent, example, description in rows
    ]
