"""
Voice Noise Robustness (Phase 5)

Utilities for measuring ambient noise, recommending a speech-energy threshold,
and deciding whether a transcribed chunk should be accepted, rejected, or
routed to confirmation in noisy venues.

These are pure, dependency-free helpers so they can be unit-tested without
audio hardware or the ASR model.
"""

import statistics
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NoiseStats:
    """Summary statistics for a set of RMS energy samples."""
    count: int = 0
    mean: float = 0.0
    median: float = 0.0
    stdev: float = 0.0
    min: float = 0.0
    max: float = 0.0

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "min": self.min,
            "max": self.max,
        }


class NoiseProfiler:
    """Collects RMS energy samples and recommends a speech-energy gate.

    Calibration flow:
      1. Sample ambient noise (crowd, HVAC) for a few seconds.
      2. Optionally sample a spoken test phrase to learn typical speech energy.
      3. ``recommend_threshold()`` returns a floor above ambient so that
         quiet non-speech is rejected while normal speech passes.
    """

    def __init__(self, ambient_samples: Optional[List[float]] = None,
                 speech_samples: Optional[List[float]] = None):
        self.ambient: List[float] = list(ambient_samples or [])
        self.speech: List[float] = list(speech_samples or [])

    def add_ambient(self, rms: float) -> None:
        if rms >= 0:
            self.ambient.append(rms)

    def add_speech(self, rms: float) -> None:
        if rms >= 0:
            self.speech.append(rms)

    def ambient_stats(self) -> NoiseStats:
        return self._stats(self.ambient)

    def speech_stats(self) -> NoiseStats:
        return self._stats(self.speech)

    @staticmethod
    def _stats(samples: List[float]) -> NoiseStats:
        if not samples:
            return NoiseStats()
        return NoiseStats(
            count=len(samples),
            mean=statistics.fmean(samples),
            median=statistics.median(samples),
            stdev=statistics.pstdev(samples) if len(samples) > 1 else 0.0,
            min=min(samples),
            max=max(samples),
        )

    def recommend_threshold(self, margin: float = 2.0) -> float:
        """Recommend a speech-energy floor (RMS) above ambient noise.

        Args:
            margin: Multiplier applied to the ambient mean. A value of 2.0
                suggests a gate roughly twice the average ambient energy.

        Returns:
            Recommended RMS threshold (0.0 if no ambient samples collected).
        """
        if not self.ambient:
            return 0.0
        mean_ambient = statistics.fmean(self.ambient)
        return round(mean_ambient * margin, 4)


class NoiseFilter:
    """Decides how to handle a chunk based on its RMS energy.

    Classification:
      - ``"reject"``  : RMS below the gate -> treat as non-speech, drop it.
      - ``"review"``  : strict mode and RMS below the speech floor -> require
                         confirmation before applying the score.
      - ``"accept"``  : otherwise.
    """

    def __init__(self, gate_rms: float = 0.0, strict: bool = False,
                 min_speech_rms: float = 0.0):
        # gate_rms: minimum energy to count as speech at all (reject below).
        # min_speech_rms: in strict mode, energy below this -> require confirmation.
        self.gate_rms = gate_rms
        self.strict = strict
        self.min_speech_rms = min_speech_rms

    def classify(self, rms: float) -> str:
        if self.gate_rms > 0.0 and rms < self.gate_rms:
            return "reject"
        if self.strict and self.min_speech_rms > 0.0 and rms < self.min_speech_rms:
            return "review"
        return "accept"

    def should_reject(self, rms: float) -> bool:
        return self.classify(rms) == "reject"

    def requires_confirmation(self, rms: float) -> bool:
        return self.classify(rms) == "review"
