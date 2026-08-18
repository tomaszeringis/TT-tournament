"""
Tests for vision benchmark harness and AUTO mode gating.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tournament_platform.app.services.vision_benchmark import (
    AutoModeContext,
    AutoModeGate,
    BenchmarkRunner,
    VisionBenchmarkResult,
)
from tournament_platform.services.settings import (
    VISION_BENCHMARK_PRECISION,
    VISION_CONFIDENCE_THRESHOLD,
)


class TestVisionBenchmarkResult:
    def test_is_approved_above_threshold(self):
        result = VisionBenchmarkResult(
            model_version="mvp",
            detector_backend="heuristic",
            algorithm_version="v1",
            dataset_version="ds1",
            sample_count=100,
            precision=0.95,
            recall=0.90,
            wrong_award_count=5,
            wrong_award_rate=0.05,
        )
        assert result.is_approved() is True

    def test_is_not_approved_below_threshold(self):
        result = VisionBenchmarkResult(
            model_version="mvp",
            detector_backend="heuristic",
            algorithm_version="v1",
            dataset_version="ds1",
            sample_count=100,
            precision=0.80,
            recall=0.90,
            wrong_award_count=20,
            wrong_award_rate=0.20,
        )
        assert result.is_approved() is False


class TestBenchmarkRunner:
    def test_run_produces_metrics(self):
        runner = BenchmarkRunner(detector_backend="heuristic", algorithm_version="v1")
        samples = [
            {"frame": None, "expected_winner": "player_a", "width": 640},
            {"frame": None, "expected_winner": "player_b", "width": 640},
        ]
        result = runner.run(dataset_version="test-ds", samples=samples)
        assert result.sample_count == 2
        assert isinstance(result.precision, float)
        assert isinstance(result.recall, float)

    def test_run_empty_samples(self):
        runner = BenchmarkRunner(detector_backend="heuristic", algorithm_version="v1")
        result = runner.run(dataset_version="empty", samples=[])
        assert result.sample_count == 0
        assert result.precision == 0.0
        assert result.recall == 0.0


class TestAutoModeGate:
    def test_all_conditions_met(self):
        ctx = AutoModeContext(
            vision_mode="auto",
            vision_enabled=True,
            operator_enabled_auto=True,
            approved_benchmark=VisionBenchmarkResult(
                model_version="mvp",
                detector_backend="heuristic",
                algorithm_version="v1",
                dataset_version="ds1",
                sample_count=100,
                precision=0.95,
                recall=0.90,
                wrong_award_count=5,
                wrong_award_rate=0.05,
            ),
            confidence=0.9,
            calibration_valid=True,
            tracker_healthy=True,
            trajectory_adequate=True,
            multimodal_agreement=True,
            rally_id="rally-1",
            unresolved_candidate=False,
            arbitration_decision="acceptable",
        )
        assert AutoModeGate.is_auto_enabled(ctx) is True

    def test_fails_when_mode_is_assisted(self):
        ctx = AutoModeContext(
            vision_mode="assisted",
            vision_enabled=True,
            operator_enabled_auto=True,
            approved_benchmark=VisionBenchmarkResult(
                model_version="mvp",
                detector_backend="heuristic",
                algorithm_version="v1",
                dataset_version="ds1",
                sample_count=100,
                precision=0.95,
                recall=0.90,
                wrong_award_count=5,
                wrong_award_rate=0.05,
            ),
            confidence=0.9,
            calibration_valid=True,
            tracker_healthy=True,
            trajectory_adequate=True,
            multimodal_agreement=True,
            rally_id="rally-1",
            unresolved_candidate=False,
            arbitration_decision="acceptable",
        )
        assert AutoModeGate.is_auto_enabled(ctx) is False

    def test_fails_when_operator_has_not_enabled_auto(self):
        ctx = AutoModeContext(
            vision_mode="auto",
            vision_enabled=True,
            operator_enabled_auto=False,
            approved_benchmark=VisionBenchmarkResult(
                model_version="mvp",
                detector_backend="heuristic",
                algorithm_version="v1",
                dataset_version="ds1",
                sample_count=100,
                precision=0.95,
                recall=0.90,
                wrong_award_count=5,
                wrong_award_rate=0.05,
            ),
            confidence=0.9,
            calibration_valid=True,
            tracker_healthy=True,
            trajectory_adequate=True,
            multimodal_agreement=True,
            rally_id="rally-1",
            unresolved_candidate=False,
            arbitration_decision="acceptable",
        )
        assert AutoModeGate.is_auto_enabled(ctx) is False

    def test_failure_reasons_returns_list(self):
        ctx = AutoModeContext(
            vision_mode="assisted",
            vision_enabled=True,
            operator_enabled_auto=False,
            approved_benchmark=None,
            confidence=0.5,
            calibration_valid=False,
            tracker_healthy=False,
            trajectory_adequate=False,
            multimodal_agreement=False,
            rally_id=None,
            unresolved_candidate=True,
            arbitration_decision="confirm_required",
        )
        reasons = AutoModeGate.failure_reasons(ctx)
        assert len(reasons) > 0
        assert "mode=assisted" in reasons
        assert "operator_auto_not_enabled" in reasons
        assert "no_approved_benchmark" in reasons
