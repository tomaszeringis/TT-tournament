"""
Quick Voice Scoring Engine

PingScore-style rapid live scoring with per-player cooldown protection.
Uses lightweight regex scanning instead of full VoiceCommandGrammar parsing.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_QUICK_COLOR_ALIAS_PATTERNS = [
    (r"\b(blue|teal|green)\b", "A"),
    (r"\b(red|orange|read)\b", "B"),
    (r"\b(melynas|mėlynas|zalia|žalia|zalias|žalias)\b", "A"),
    (r"\b(raudonas|raudona|oranzinis|oranžinis)\b", "B"),
]


@dataclass
class QuickVoiceScoreEvent:
    type: str = "increment"
    player: Optional[str] = None
    raw_text: str = ""
    confidence: float = 0.9
    source: str = "quick_voice"


class QuickVoiceScoringEngine:
    """Dedicated cooldown and routing for Quick Voice Scoring mode."""

    def __init__(
        self,
        cooldown_ms: float = 1200.0,
        global_min_interval_ms: float = 300.0,
    ):
        self.cooldown_ms = cooldown_ms
        self.global_min_interval_ms = global_min_interval_ms
        self.last_player: Optional[str] = None
        self.last_ts: float = 0.0
        self.last_phrase: str = ""
        self.last_status: str = "idle"  # idle | accepted | duplicate_ignored | rejected

    def process(
        self,
        transcript: str,
        current_score_a: int,
        current_score_b: int,
    ) -> Dict[str, Any]:
        """
        Returns dict with:
          - action: "accept" | "ignore" | "reject"
          - player: "A" | "B" | None
          - reason: str
          - event: QuickVoiceScoreEvent | None
        """
        now = time.time() * 1000.0

        text = transcript.lower().strip()
        if not text:
            return {
                "action": "reject",
                "player": None,
                "reason": "empty_transcript",
                "event": None,
            }

        player = self._scan_color_words(text)
        if player is None:
            self.last_status = "rejected"
            self.last_phrase = transcript
            return {
                "action": "reject",
                "player": None,
                "reason": "no_color_word",
                "event": None,
            }

        if self.last_player == player and (now - self.last_ts) < self.cooldown_ms:
            self.last_status = "duplicate_ignored"
            self.last_phrase = transcript
            return {
                "action": "ignore",
                "player": player,
                "reason": "duplicate",
                "event": None,
            }

        if (now - self.last_ts) < self.global_min_interval_ms:
            self.last_status = "rejected"
            self.last_phrase = transcript
            return {
                "action": "ignore",
                "player": player,
                "reason": "too_soon",
                "event": None,
            }

        self.last_player = player
        self.last_ts = now
        self.last_phrase = transcript
        self.last_status = "accepted"

        event = QuickVoiceScoreEvent(
            type="increment",
            player=player,
            raw_text=transcript,
            confidence=0.9,
            source="quick_voice",
        )
        return {
            "action": "accept",
            "player": player,
            "reason": "accepted",
            "event": event,
        }

    def _scan_color_words(self, text: str) -> Optional[str]:
        for pattern, player in _QUICK_COLOR_ALIAS_PATTERNS:
            if re.search(pattern, text):
                return player
        return None
