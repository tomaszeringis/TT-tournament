"""
Voice Parse Result

Dataclass bridging the grammar output (VoiceIntent + slots + confidence)
to the existing wire type (VoiceScoreEvent) consumed by MatchManager.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class VoiceParseResult:
    """Parsed voice command with intent, slots, and safety metadata."""

    intent: str
    slots: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    safety_level: str = "simple"
    requires_confirmation: bool = False
    raw_transcript: str = ""
    normalized_text: str = ""
    source: str = "asr"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    asr_latency_ms: Optional[float] = None
    noise_rms: Optional[float] = None
    speaker_label: Optional[str] = None
    language: str = "en"
    disposition: Optional[str] = None

    def to_score_event(self) -> "VoiceScoreEvent":
        """Convert to the legacy wire type used by MatchManager."""
        from tournament_platform.app.services.voice_parser import VoiceScoreEvent

        intent = self.intent
        score_a = self.slots.get("score_a")
        score_b = self.slots.get("score_b")
        player = self.slots.get("player")

        if intent == "score_point":
            event_type = "increment"
        elif intent == "set_score":
            event_type = "set_score"
        elif intent == "undo":
            event_type = "undo"
        elif intent == "repeat_score":
            event_type = "repeat"
        elif intent == "start_match":
            event_type = "start_match"
        elif intent == "pause_match":
            event_type = "pause_match"
        elif intent == "resume_match":
            event_type = "resume_match"
        elif intent == "start_next_game":
            event_type = "start_next_game"
        elif intent == "end_game":
            event_type = "end_game"
        elif intent == "timeout_start":
            event_type = "timeout_start"
        elif intent == "timeout_end":
            event_type = "timeout_end"
        elif intent == "server_check":
            event_type = "server_check"
        elif intent == "set_server":
            event_type = "set_server"
        elif intent == "confirm":
            event_type = "confirm"
        elif intent == "cancel":
            event_type = "cancel"
        else:
            event_type = "unknown"

        return VoiceScoreEvent(
            type=event_type,
            score_a=score_a,
            score_b=score_b,
            player=player,
            raw_text=self.raw_transcript,
            confidence=self.confidence,
            event_id=self.event_id,
            timestamp=self.timestamp,
            source=self.source,
            speaker_label=self.speaker_label,
            language=self.language,
            requires_confirmation=self.requires_confirmation,
            asr_latency_ms=self.asr_latency_ms,
            noise_rms=self.noise_rms,
        )


# Avoid circular import at module load time
from tournament_platform.app.services.voice_parser import VoiceScoreEvent  # noqa: E402
