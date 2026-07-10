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
    NAVIGATE_DASHBOARD = "navigate_dashboard"
    NAVIGATE_BRACKET = "navigate_bracket"
    NAVIGATE_RANKINGS = "navigate_rankings"
    NAVIGATE_PUBLIC_BOARD = "navigate_public_board"
    NAVIGATE_CURRENT_MATCH = "navigate_current_match"
    NAVIGATE_SCORING = "navigate_scoring"
    NAVIGATE_HELP = "navigate_help"
    ADMIN_CALL_NEXT = "admin_call_next"
    ADMIN_TABLE_READY = "admin_table_ready"
    ADMIN_ASSIGN_TABLE = "admin_assign_table"
    ADMIN_MARK_UNAVAILABLE = "admin_mark_unavailable"
    ADMIN_PUBLISH_RESULT = "admin_publish_result"
    ADMIN_MARK_NO_SHOW = "admin_mark_no_show"
    ADMIN_DROP_PLAYER = "admin_drop_player"
    ADMIN_START_NEXT_ROUND = "admin_start_next_round"
    RULES_QUERY = "rules_query"
    ACCESS_REPEAT = "access_repeat"
    ACCESS_ANNOUNCE_SCORE = "access_announce_score"
    ACCESS_LOUDER = "access_louder"
    ACCESS_QUIETER = "access_quieter"
    ACCESS_MUTE = "access_mute"
    ACCESS_UNMUTE = "access_unmute"
    ACCESS_SLOWER = "access_slower"
    ACCESS_FASTER = "access_faster"
    ACCESS_LARGE_TEXT = "access_large_text"
    ACCESS_HIGH_CONTRAST = "access_high_contrast"
    ACCESS_HELP = "access_help"


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
    VoiceIntent.NAVIGATE_DASHBOARD: "safe",
    VoiceIntent.NAVIGATE_BRACKET: "safe",
    VoiceIntent.NAVIGATE_RANKINGS: "safe",
    VoiceIntent.NAVIGATE_PUBLIC_BOARD: "safe",
    VoiceIntent.NAVIGATE_CURRENT_MATCH: "safe",
    VoiceIntent.NAVIGATE_SCORING: "safe",
    VoiceIntent.NAVIGATE_HELP: "safe",
    VoiceIntent.ADMIN_CALL_NEXT: "medium",
    VoiceIntent.ADMIN_TABLE_READY: "medium",
    VoiceIntent.ADMIN_ASSIGN_TABLE: "medium",
    VoiceIntent.ADMIN_MARK_UNAVAILABLE: "high",
    VoiceIntent.ADMIN_PUBLISH_RESULT: "high",
    VoiceIntent.ADMIN_MARK_NO_SHOW: "high",
    VoiceIntent.ADMIN_DROP_PLAYER: "high",
    VoiceIntent.ADMIN_START_NEXT_ROUND: "medium",
    VoiceIntent.RULES_QUERY: "read_only",
    VoiceIntent.ACCESS_REPEAT: "safe",
    VoiceIntent.ACCESS_ANNOUNCE_SCORE: "safe",
    VoiceIntent.ACCESS_LOUDER: "safe",
    VoiceIntent.ACCESS_QUIETER: "safe",
    VoiceIntent.ACCESS_MUTE: "safe",
    VoiceIntent.ACCESS_UNMUTE: "safe",
    VoiceIntent.ACCESS_SLOWER: "safe",
    VoiceIntent.ACCESS_FASTER: "safe",
    VoiceIntent.ACCESS_LARGE_TEXT: "safe",
    VoiceIntent.ACCESS_HIGH_CONTRAST: "safe",
    VoiceIntent.ACCESS_HELP: "safe",
}


# Command patterns: (intent, regex_pattern, confidence, slot_extractors)
# Slot extractors map slot name -> callable(match) -> value
_NAVIGATION_PATTERNS = [
    (VoiceIntent.NAVIGATE_DASHBOARD, r"\b(open\s+)?dashboard\b", 0.9),
    (VoiceIntent.NAVIGATE_BRACKET, r"\b(show\s+)?bracket\b", 0.9),
    (VoiceIntent.NAVIGATE_RANKINGS, r"\b(show\s+)?rankings?\b", 0.9),
    (VoiceIntent.NAVIGATE_PUBLIC_BOARD, r"\b(show\s+)?public\s+board\b", 0.9),
    (VoiceIntent.NAVIGATE_CURRENT_MATCH, r"\b(show\s+)?current\s+match\b", 0.9),
    (VoiceIntent.NAVIGATE_SCORING, r"\b(back\s+to\s+)?scoring\b", 0.9),
    (VoiceIntent.NAVIGATE_HELP, r"\b(show\s+)?(voice\s+)?help\b", 0.9),
]

_ADMIN_PATTERNS = [
    (VoiceIntent.ADMIN_CALL_NEXT, r"\bcall\s+next\s+match\b", 0.9),
    (VoiceIntent.ADMIN_TABLE_READY, r"\btable\s+ready\b", 0.9),
    (VoiceIntent.ADMIN_ASSIGN_TABLE, r"\bassign\s+table\b", 0.85),
    (VoiceIntent.ADMIN_MARK_UNAVAILABLE, r"\bmark\s+unavailable\b", 0.85),
    (VoiceIntent.ADMIN_PUBLISH_RESULT, r"\bpublish\s+result\b", 0.9),
    (VoiceIntent.ADMIN_MARK_NO_SHOW, r"\bmark\s+no\s+show\b", 0.85),
    (VoiceIntent.ADMIN_DROP_PLAYER, r"\bdrop\s+player\b", 0.85),
    (VoiceIntent.ADMIN_START_NEXT_ROUND, r"\bstart\s+next\s+round\b", 0.9),
]

_RULES_PATTERNS = [
    (VoiceIntent.RULES_QUERY, r"\b(ask\s+)?(rules|rule|umpire|question)\b", 0.7),
]

_ACCESSIBILITY_PATTERNS = [
    (VoiceIntent.ACCESS_REPEAT, r"\brepeat\b", 0.9),
    (VoiceIntent.ACCESS_ANNOUNCE_SCORE, r"\bannounce\s+score\b", 0.9),
    (VoiceIntent.ACCESS_LOUDER, r"\blouder\b", 0.9),
    (VoiceIntent.ACCESS_QUIETER, r"\bquieter\b", 0.9),
    (VoiceIntent.ACCESS_MUTE, r"\bmute\b", 0.9),
    (VoiceIntent.ACCESS_UNMUTE, r"\bunmute\b", 0.9),
    (VoiceIntent.ACCESS_SLOWER, r"\bslower\b", 0.9),
    (VoiceIntent.ACCESS_FASTER, r"\bfaster\b", 0.9),
    (VoiceIntent.ACCESS_LARGE_TEXT, r"\blarge\s+text\b", 0.9),
    (VoiceIntent.ACCESS_HIGH_CONTRAST, r"\bhigh\s+contrast\b", 0.9),
    (VoiceIntent.ACCESS_HELP, r"\b(voice\s+)?accessibility\s+help\b", 0.9),
]

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
    (VoiceIntent.TIMEOUT_END, r"\bend\s+timeout\b", 0.85, {}),
    (VoiceIntent.TIMEOUT_END, r"\bresume\s+play\b", 0.8, {}),
    (VoiceIntent.TIMEOUT_START, r"\btimeout\b", 0.85, {}),
    (VoiceIntent.TIMEOUT_START, r"\btime\s+out\b", 0.85, {}),
    (VoiceIntent.SERVER_CHECK, r"\bwho\s+serves?\b", 0.9, {}),
    (VoiceIntent.SERVER_CHECK, r"\bserver\?\b", 0.9, {}),
    (VoiceIntent.CONFIRM, r"\bconfirm\b", 0.9, {}),
    (VoiceIntent.CONFIRM, r"\byes\b", 0.8, {}),
    (VoiceIntent.CONFIRM, r"\baccept\b", 0.85, {}),
    (VoiceIntent.CANCEL, r"\bcancel\b", 0.9, {}),
    (VoiceIntent.CANCEL, r"\bno\b", 0.7, {}),
    (VoiceIntent.CANCEL, r"\babort\b", 0.85, {}),
    (VoiceIntent.SET_SERVER, r"\bplayer\s+(one|1|a)\s+serves?\b", 0.85, {}),
    (VoiceIntent.SET_SERVER, r"\bplayer\s+(two|2|b)\s+serves?\b", 0.85, {}),
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

        # Navigation intents
        for intent, pattern, confidence in _NAVIGATION_PATTERNS:
            if re.search(pattern, text):
                return VoiceParseResult(
                    intent=intent,
                    confidence=confidence,
                    safety_level=_SAFETY_MAP.get(intent, "safe"),
                    raw_transcript=raw,
                    normalized_text=normalized,
                )

        # Admin intents
        for intent, pattern, confidence in _ADMIN_PATTERNS:
            if re.search(pattern, text):
                slots = {}
                if intent == VoiceIntent.ADMIN_ASSIGN_TABLE:
                    table_match = re.search(r"\btable\s+(\w+)\b", text)
                    if table_match:
                        slots["table"] = table_match.group(1)
                return VoiceParseResult(
                    intent=intent,
                    slots=slots,
                    confidence=confidence,
                    safety_level=_SAFETY_MAP.get(intent, "medium"),
                    raw_transcript=raw,
                    normalized_text=normalized,
                )

        # Rules query intents
        for intent, pattern, confidence in _RULES_PATTERNS:
            if re.search(pattern, text):
                slots = {"question": raw}
                return VoiceParseResult(
                    intent=intent,
                    slots=slots,
                    confidence=confidence,
                    safety_level=_SAFETY_MAP.get(intent, "read_only"),
                    raw_transcript=raw,
                    normalized_text=normalized,
                )

        # Accessibility intents
        for intent, pattern, confidence in _ACCESSIBILITY_PATTERNS:
            if re.search(pattern, text):
                return VoiceParseResult(
                    intent=intent,
                    confidence=confidence,
                    safety_level=_SAFETY_MAP.get(intent, "safe"),
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
        (VoiceIntent.NAVIGATE_DASHBOARD, '"open dashboard"', "Go to dashboard"),
        (VoiceIntent.NAVIGATE_BRACKET, '"show bracket"', "Show bracket"),
        (VoiceIntent.NAVIGATE_RANKINGS, '"show rankings"', "Show rankings"),
        (VoiceIntent.NAVIGATE_PUBLIC_BOARD, '"show public board"', "Show public board"),
        (VoiceIntent.NAVIGATE_CURRENT_MATCH, '"show current match"', "Show current match"),
        (VoiceIntent.NAVIGATE_SCORING, '"back to scoring"', "Back to scoring"),
        (VoiceIntent.NAVIGATE_HELP, '"show help"', "Show voice help"),
        (VoiceIntent.ADMIN_CALL_NEXT, '"call next match"', "Call next match"),
        (VoiceIntent.ADMIN_TABLE_READY, '"table ready"', "Mark table ready"),
        (VoiceIntent.ADMIN_PUBLISH_RESULT, '"publish result"', "Publish result"),
        (VoiceIntent.RULES_QUERY, '"ask rules"', "Ask rules question"),
        (VoiceIntent.ACCESS_REPEAT, '"repeat"', "Repeat last score"),
        (VoiceIntent.ACCESS_ANNOUNCE_SCORE, '"announce score"', "Announce score"),
        (VoiceIntent.ACCESS_LOUDER, '"louder"', "Increase volume"),
        (VoiceIntent.ACCESS_QUIETER, '"quieter"', "Decrease volume"),
        (VoiceIntent.ACCESS_MUTE, '"mute"', "Mute audio"),
        (VoiceIntent.ACCESS_UNMUTE, '"unmute"', "Unmute audio"),
        (VoiceIntent.ACCESS_SLOWER, '"slower"', "Slower speech"),
        (VoiceIntent.ACCESS_FASTER, '"faster"', "Faster speech"),
        (VoiceIntent.ACCESS_LARGE_TEXT, '"large text"', "Large text mode"),
        (VoiceIntent.ACCESS_HIGH_CONTRAST, '"high contrast"', "High contrast mode"),
        (VoiceIntent.ACCESS_HELP, '"accessibility help"', "Accessibility help"),
    ]
    return [
        {
            "intent": intent.value,
            "example": example,
            "description": description,
        }
        for intent, example, description in rows
    ]
