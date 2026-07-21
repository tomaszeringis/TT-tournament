"""Tests for TT Sounds impact detector."""

import numpy as np

from tournament_platform.app.services.tt_sounds.detector import ImpactDetector
from tournament_platform.app.services.tt_sounds.schemas import TTAudioEvent


class TestImpactDetector:
    def test_silence_below_abs_min_returns_none(self):
        det = ImpactDetector(abs_min_energy=0.03, threshold_multiplier=4.0, sample_rate=48000)
        window = np.zeros(240, dtype=np.float32)
        assert det.process_window(window, timestamp=0.0) is None

    def test_impulse_detected(self):
        det = ImpactDetector(abs_min_energy=0.01, threshold_multiplier=2.0, cooldown_ms=0.0, sample_rate=48000)
        window = np.zeros(240, dtype=np.float32)
        window[120] = 1.0
        event = det.process_window(window, timestamp=0.0)
        assert event is not None
        assert event.event_type == "impact"
        assert event.confidence > 0.0

    def test_cooldown_prevents_duplicates(self):
        det = ImpactDetector(abs_min_energy=0.01, threshold_multiplier=2.0, cooldown_ms=1000.0, sample_rate=48000)
        window = np.zeros(240, dtype=np.float32)
        window[120] = 1.0
        assert det.process_window(window, timestamp=0.0) is not None
        assert det.process_window(window, timestamp=0.1) is None

    def test_sub_threshold_noise_ignored(self):
        det = ImpactDetector(abs_min_energy=0.5, threshold_multiplier=4.0, sample_rate=48000)
        window = np.full(240, 0.1, dtype=np.float32)
        assert det.process_window(window, timestamp=0.0) is None

    def test_adaptive_threshold_rises_with_signal(self):
        det = ImpactDetector(abs_min_energy=0.005, threshold_multiplier=2.0, cooldown_ms=0.0, noise_floor_decay=0.9, sample_rate=48000)
        quiet = np.full(240, 0.001, dtype=np.float32)
        loud = np.zeros(240, dtype=np.float32)
        loud[120] = 1.0
        det.process_window(quiet, timestamp=0.0)
        det.process_window(quiet, timestamp=0.01)
        event = det.process_window(loud, timestamp=0.02)
        assert event is not None
        assert det._noise_floor > 0.0

    def test_window_size_scales_with_sample_rate(self):
        det_48 = ImpactDetector(window_ms=5.0, sample_rate=48000)
        det_16 = ImpactDetector(window_ms=5.0, sample_rate=16000)
        assert det_48._compute_window_samples() == 240
        assert det_16._compute_window_samples() == 80

    def test_confidence_clamped_to_one(self):
        det = ImpactDetector(abs_min_energy=0.0, threshold_multiplier=1.0, cooldown_ms=0.0, sample_rate=48000)
        window = np.zeros(240, dtype=np.float32)
        window[120] = 10.0
        event = det.process_window(window, timestamp=0.0)
        assert event is not None
        assert event.confidence <= 1.0
