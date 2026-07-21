"""Dataclasses for the TT Sounds / Audio Rally Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class TTAudioEvent:
    timestamp: float
    event_type: str
    energy: float
    confidence: float
    source: str
    sample_rate: int
    channels: int

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RallyContext:
    rally_start_ts: float
    impacts: List[TTAudioEvent] = field(default_factory=list)
    is_active: bool = True


@dataclass
class AudioRallySummary:
    rally_id: str
    start_ts: float
    end_ts: float
    impact_count: int
    avg_interval_ms: float
    strongest_impact_energy: float
    confidence: float
    last_action: str = "gap"
    source: str = "tt_sounds_detector"

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AudioImpactEvent:
    timestamp: float
    energy: float
    confidence: float
