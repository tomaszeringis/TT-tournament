"""
Tests for the noise robustness utilities (Phase 5): NoiseProfiler and NoiseFilter.
"""

from tournament_platform.app.services.voice_noise import NoiseFilter, NoiseProfiler


class TestNoiseProfiler:
    """Calibration statistics and threshold recommendation."""

    def test_recommend_without_samples_is_zero(self):
        profiler = NoiseProfiler()
        assert profiler.recommend_threshold() == 0.0

    def test_recommend_scales_ambient_by_margin(self):
        profiler = NoiseProfiler(ambient_samples=[0.01, 0.02, 0.03])
        # mean = 0.02, margin default 2.0 -> 0.04
        assert profiler.recommend_threshold() == 0.04

    def test_recommend_respects_custom_margin(self):
        profiler = NoiseProfiler(ambient_samples=[0.10])
        assert profiler.recommend_threshold(margin=1.5) == 0.15

    def test_ambient_stats(self):
        profiler = NoiseProfiler(ambient_samples=[0.01, 0.02, 0.03])
        stats = profiler.ambient_stats()
        assert stats.count == 3
        assert abs(stats.mean - 0.02) < 1e-9
        assert stats.min == 0.01
        assert stats.max == 0.03

    def test_add_ambient_ignores_negative(self):
        profiler = NoiseProfiler()
        profiler.add_ambient(-1.0)
        profiler.add_ambient(0.05)
        assert profiler.ambient == [0.05]


class TestNoiseFilter:
    """Chunk classification based on RMS energy and strict mode."""

    def test_accept_when_gate_disabled(self):
        f = NoiseFilter(gate_rms=0.0, strict=False)
        assert f.classify(0.001) == "accept"

    def test_reject_below_gate(self):
        f = NoiseFilter(gate_rms=0.05, strict=False)
        assert f.classify(0.01) == "reject"
        assert f.classify(0.10) == "accept"

    def test_strict_mode_reviews_low_energy(self):
        # gate 0.02 (reject below), strict with speech floor 0.05 (review below).
        f = NoiseFilter(gate_rms=0.02, strict=True, min_speech_rms=0.05)
        assert f.classify(0.01) == "reject"   # below gate
        assert f.classify(0.03) == "review"   # above gate, below speech floor
        assert f.classify(0.10) == "accept"   # above speech floor

    def test_should_reject_and_requires_confirmation(self):
        f = NoiseFilter(gate_rms=0.02, strict=True, min_speech_rms=0.05)
        assert f.should_reject(0.01) is True
        assert f.should_reject(0.10) is False
        assert f.requires_confirmation(0.03) is True
        assert f.requires_confirmation(0.10) is False
