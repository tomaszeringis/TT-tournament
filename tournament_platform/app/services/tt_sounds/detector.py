"""Lightweight impact detector for table-tennis audio rally analysis.

Operates on short (~5 ms) normalized windows. No Torch dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .schemas import TTAudioEvent

logger = logging.getLogger(__name__)


@dataclass
class ImpactDetector:
    abs_min_energy: float = 0.03
    threshold_multiplier: float = 4.0
    noise_floor_decay: float = 0.95
    cooldown_ms: float = 80.0
    window_ms: float = 5.0
    event_window_ms: float = 15.0
    sample_rate: int = 48000

    def __post_init__(self) -> None:
        self._noise_floor: float = 0.0
        self._last_impact_ts: float = -float("inf")
        self._last_energy: float = 0.0
        self._impact_count: int = 0

    def _compute_window_samples(self) -> int:
        return max(1, int(self.sample_rate * self.window_ms / 1000.0))

    def _update_noise_floor(self, rms: float) -> None:
        if self._noise_floor == 0.0:
            self._noise_floor = rms
        else:
            self._noise_floor = (
                self._noise_floor * self.noise_floor_decay + rms * (1.0 - self.noise_floor_decay)
            )

    def process_window(self, window: np.ndarray, timestamp: float) -> Optional[TTAudioEvent]:
        if window is None or window.size == 0:
            return None

        arr = np.asarray(window, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr.mean(axis=0)
        max_val = float(np.max(np.abs(arr))) if arr.size else 0.0
        if max_val > 1.0:
            arr = arr / max_val
        rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2))) if arr.size else 0.0

        threshold = self._noise_floor * self.threshold_multiplier

        if rms < self.abs_min_energy or rms < threshold:
            self._update_noise_floor(rms)
            return None

        if timestamp - self._last_impact_ts < (self.cooldown_ms / 1000.0):
            return None

        confidence = min(1.0, rms / (max(threshold, self.abs_min_energy) * 2.0)) if threshold > 0 or self.abs_min_energy > 0 else min(1.0, rms)
        self._last_impact_ts = timestamp
        self._last_energy = rms
        self._impact_count += 1

        return TTAudioEvent(
            timestamp=timestamp,
            event_type="impact",
            energy=rms,
            confidence=confidence,
            source="tt_sounds_detector",
            sample_rate=self.sample_rate,
            channels=1,
        )
