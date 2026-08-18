"""
Vision Benchmark — offline precision/recall harness and AUTO mode gating.

Provides:
- VisionBenchmarkResult dataclass
- BenchmarkRunner for offline evaluation
- AutoModeGate for runtime AUTO enablement checks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from tournament_platform.services.settings import (
    VISION_CONFIDENCE_THRESHOLD,
    VISION_ENABLED,
    VISION_MODE,
    VISION_BENCHMARK_PRECISION,
)

logger = logging.getLogger(__name__)


@dataclass
class VisionBenchmarkResult:
    """Durable benchmark result for a vision detector backend."""

    model_version: str
    detector_backend: str
    algorithm_version: str
    dataset_version: str
    sample_count: int
    precision: float
    recall: float
    wrong_award_count: int
    wrong_award_rate: float
    tested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_approved(self, required_precision: float = VISION_BENCHMARK_PRECISION) -> bool:
        return self.precision >= required_precision


@dataclass
class DetectionMetrics:
    ball_localization_recall: float = 0.0
    false_positive_rate: float = 0.0
    localization_error: float = 0.0
    track_continuity: float = 0.0


@dataclass
class EventMetrics:
    bounce_precision: float = 0.0
    bounce_recall: float = 0.0
    rally_boundary_accuracy: float = 0.0


@dataclass
class ScoringMetrics:
    point_candidate_precision: float = 0.0
    point_candidate_recall: float = 0.0
    wrong_winner_count: int = 0
    wrong_winner_rate: float = 0.0
    auto_award_precision: float = 0.0


class BenchmarkRunner:
    """Offline benchmark runner for ball detector backends."""

    def __init__(self, detector_backend: str, algorithm_version: str) -> None:
        self.detector_backend = detector_backend
        self.algorithm_version = algorithm_version

    def run(self, dataset_version: str, samples: list) -> VisionBenchmarkResult:
        """Run benchmark on a labeled validation set.

        Args:
            dataset_version: Label of the evaluation dataset.
            samples: List of labeled samples. Each sample should provide
                frame data and expected winner.

        Returns:
            VisionBenchmarkResult with precision/recall metrics.
        """
        tp = 0
        fp = 0
        fn = 0
        wrong_awards = 0

        for sample in samples:
            expected = sample.get("expected_winner")
            predicted = self._predict(sample)
            if predicted is None:
                fn += 1
                continue
            if predicted == expected:
                tp += 1
            else:
                fp += 1
                wrong_awards += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        sample_count = len(samples)
        wrong_award_rate = wrong_awards / sample_count if sample_count > 0 else 0.0

        return VisionBenchmarkResult(
            model_version="mvp",
            detector_backend=self.detector_backend,
            algorithm_version=self.algorithm_version,
            dataset_version=dataset_version,
            sample_count=sample_count,
            precision=precision,
            recall=recall,
            wrong_award_count=wrong_awards,
            wrong_award_rate=wrong_award_rate,
        )

    def _predict(self, sample: dict) -> Optional[str]:
        """Run detector on a single sample and return predicted winner."""
        try:
            from tournament_platform.app.services.vision_backends import HeuristicBallDetector
            detector = HeuristicBallDetector()
            frame = sample.get("frame")
            if frame is None:
                return None
            obs = detector.detect(frame)
            if obs is None:
                return None
            if obs.confidence < VISION_CONFIDENCE_THRESHOLD:
                return None
            return "player_a" if obs.x < sample.get("width", 640) / 2 else "player_b"
        except Exception as exc:
            logger.debug("Benchmark prediction failed: %s", exc)
            return None


class ScoringBenchmarkRunner:
    """Benchmark runner for scoring-specific metrics.

    Only scoring metrics may unlock AUTO mode.
    """

    def __init__(self, detector_backend: str, algorithm_version: str) -> None:
        self.detector_backend = detector_backend
        self.algorithm_version = algorithm_version

    def run(self, dataset_version: str, samples: list) -> VisionBenchmarkResult:
        tp = 0
        fp = 0
        fn = 0
        wrong_awards = 0

        for sample in samples:
            expected = sample.get("expected_winner")
            predicted = self._predict(sample)
            if predicted is None:
                fn += 1
                continue
            if predicted == expected:
                tp += 1
            else:
                fp += 1
                wrong_awards += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        sample_count = len(samples)
        wrong_award_rate = wrong_awards / sample_count if sample_count > 0 else 0.0

        return VisionBenchmarkResult(
            model_version="mvp",
            detector_backend=self.detector_backend,
            algorithm_version=self.algorithm_version,
            dataset_version=dataset_version,
            sample_count=sample_count,
            precision=precision,
            recall=recall,
            wrong_award_count=wrong_awards,
            wrong_award_rate=wrong_award_rate,
        )

    def _predict(self, sample: dict) -> Optional[str]:
        try:
            from tournament_platform.app.services.vision_backends import HeuristicBallDetector
            detector = HeuristicBallDetector()
            frame = sample.get("frame")
            if frame is None:
                return None
            obs = detector.detect(frame)
            if obs is None:
                return None
            if obs.confidence < VISION_CONFIDENCE_THRESHOLD:
                return None
            return "player_a" if obs.x < sample.get("width", 640) / 2 else "player_b"
        except Exception as exc:
            logger.debug("Scoring benchmark prediction failed: %s", exc)
            return None


@dataclass
class AutoModeContext:
    """Runtime context for AUTO mode gating."""

    vision_mode: str = VISION_MODE
    vision_enabled: bool = VISION_ENABLED
    operator_enabled_auto: bool = False
    approved_benchmark: Optional[VisionBenchmarkResult] = None
    confidence: float = 0.0
    calibration_valid: bool = False
    tracker_healthy: bool = False
    trajectory_adequate: bool = False
    multimodal_agreement: bool = True
    rally_id: Optional[str] = None
    unresolved_candidate: bool = False
    arbitration_decision: Optional[str] = None
    benchmark_type: str = "scoring"


class AutoModeGate:
    """Gate for enabling AUTO scoring mode."""

    @staticmethod
    def is_auto_enabled(ctx: AutoModeContext) -> bool:
        """Return True only if every AUTO condition is satisfied."""
        if not ctx.vision_enabled:
            return False
        if ctx.vision_mode != "auto":
            return False
        if not ctx.operator_enabled_auto:
            return False
        if ctx.approved_benchmark is None:
            return False
        if ctx.benchmark_type != "scoring":
            return False
        if not ctx.approved_benchmark.is_approved():
            return False
        if ctx.confidence < VISION_CONFIDENCE_THRESHOLD:
            return False
        if not ctx.calibration_valid:
            return False
        if not ctx.tracker_healthy:
            return False
        if not ctx.trajectory_adequate:
            return False
        if not ctx.multimodal_agreement:
            return False
        if ctx.rally_id is None or ctx.unresolved_candidate:
            return False
        if ctx.arbitration_decision != "acceptable":
            return False
        return True

    @staticmethod
    def failure_reasons(ctx: AutoModeContext) -> List[str]:
        """Return list of unmet conditions for diagnostics."""
        reasons = []
        if not ctx.vision_enabled:
            reasons.append("vision_disabled")
        if ctx.vision_mode != "auto":
            reasons.append(f"mode={ctx.vision_mode}")
        if not ctx.operator_enabled_auto:
            reasons.append("operator_auto_not_enabled")
        if ctx.approved_benchmark is None:
            reasons.append("no_approved_benchmark")
        elif ctx.benchmark_type != "scoring":
            reasons.append(f"benchmark_type={ctx.benchmark_type}_not_scoring")
        elif not ctx.approved_benchmark.is_approved():
            reasons.append(f"precision={ctx.approved_benchmark.precision:.2f}_below_threshold")
        if ctx.confidence < VISION_CONFIDENCE_THRESHOLD:
            reasons.append(f"confidence={ctx.confidence:.2f}_below_threshold")
        if not ctx.calibration_valid:
            reasons.append("calibration_invalid")
        if not ctx.tracker_healthy:
            reasons.append("tracker_unhealthy")
        if not ctx.trajectory_adequate:
            reasons.append("trajectory_inadequate")
        if not ctx.multimodal_agreement:
            reasons.append("multimodal_conflict")
        if ctx.rally_id is None:
            reasons.append("no_rally_id")
        if ctx.unresolved_candidate:
            reasons.append("unresolved_candidate")
        if ctx.arbitration_decision != "acceptable":
            reasons.append(f"arbitration={ctx.arbitration_decision}")
        return reasons
