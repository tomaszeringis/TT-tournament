"""
Voice Metrics (Phase 2)

Tracks ASR latency, chunk RMS, confidence stats, and command-to-score latency
for observability and tournament hall testing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LatencySample:
    """Single latency measurement."""
    ts: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    stage: str = "asr"  # asr | pipeline | command_to_score
    metadata: dict = field(default_factory=dict)


class VoiceMetrics:
    """Collects and summarizes voice pipeline metrics."""

    def __init__(self, max_samples: int = 200):
        self.max_samples = max_samples
        self._samples: List[LatencySample] = []

    def record_latency(self, latency_ms: float, stage: str = "asr", **metadata) -> None:
        sample = LatencySample(
            ts=time.time(),
            latency_ms=latency_ms,
            stage=stage,
            metadata=metadata,
        )
        self._samples.append(sample)
        if len(self._samples) > self.max_samples:
            self._samples = self._samples[-self.max_samples :]

    def summarize(self) -> dict:
        if not self._samples:
            return {"count": 0}
        latencies = [s.latency_ms for s in self._samples]
        return {
            "count": len(latencies),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "median_ms": sorted(latencies)[len(latencies) // 2],
            "p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies),
            "latest_ms": latencies[-1],
        }

    def clear(self) -> None:
        self._samples.clear()
