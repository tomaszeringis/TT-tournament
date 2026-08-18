"""
Tests for PointCandidateGenerator.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.vision_candidate import PointCandidateGenerator
from tournament_platform.app.services.vision_events import BallObservation, CandidateStatus
from datetime import datetime, timezone


def _obs(x, y, ts):
    return BallObservation(
        monotonic_timestamp=ts,
        utc_timestamp=datetime.now(timezone.utc),
        x=x,
        y=y,
        confidence=0.9,
    )


class TestPointCandidateGenerator:
    def test_one_candidate_per_rally(self):
        gen = PointCandidateGenerator(match_id=1, algorithm_version="mvp")
        observations = [
            _obs(300, 100, 1000.0),
            _obs(290, 150, 1000.033),
            _obs(280, 200, 1000.066),
            _obs(270, 250, 1000.099),
            _obs(260, 300, 1000.132),
            _obs(250, 280, 1000.165),
            _obs(240, 260, 1000.198),
            _obs(230, 240, 1000.231),
        ]
        candidates = []
        for obs in observations:
            r = gen.process_observation(obs)
            if r.candidate is not None:
                candidates.append(r.candidate)
        assert len(candidates) == 1

    def test_candidate_has_metadata(self):
        gen = PointCandidateGenerator(match_id=1, algorithm_version="mvp")
        observations = [
            _obs(300, 100, 1000.0),
            _obs(290, 150, 1000.033),
            _obs(280, 200, 1000.066),
            _obs(270, 250, 1000.099),
            _obs(260, 300, 1000.132),
            _obs(250, 280, 1000.165),
            _obs(240, 260, 1000.198),
            _obs(230, 240, 1000.231),
        ]
        candidate = None
        for obs in observations:
            r = gen.process_observation(obs)
            if r.candidate is not None:
                candidate = r.candidate
                break
        assert candidate is not None
        assert candidate.match_id == 1
        assert candidate.detector_backend == "heuristic"
        assert candidate.algorithm_version == "mvp"
        assert candidate.status == CandidateStatus.PROPOSED

    def test_reset_clears_state(self):
        gen = PointCandidateGenerator(match_id=1, algorithm_version="mvp")
        observations = [
            _obs(300, 100, 1000.0),
            _obs(290, 150, 1000.033),
            _obs(280, 200, 1000.066),
            _obs(270, 250, 1000.099),
            _obs(260, 300, 1000.132),
            _obs(250, 280, 1000.165),
            _obs(240, 260, 1000.198),
            _obs(230, 240, 1000.231),
        ]
        for obs in observations:
            gen.process_observation(obs)
        gen.reset()
        assert gen._active_rally is None
        assert gen._last_candidate_id is None
