"""Tests for TT Sounds processor thread safety and queue behavior."""

import queue
import threading
import time

import numpy as np

from tournament_platform.app.services.tt_sounds.processor import TTRallyProcessor
from tournament_platform.app.services.tt_sounds.detector import ImpactDetector


class TestTTRallyProcessor:
    def test_start_stop_thread_safety(self):
        det = ImpactDetector(sample_rate=48000)
        proc = TTRallyProcessor(detector=det, sample_rate=48000)
        proc.start()
        assert proc._worker_thread is not None
        assert proc._worker_thread.is_alive()
        proc.stop()
        assert not proc._worker_thread.is_alive()

    def test_queue_drop_oldest_on_full(self):
        det = ImpactDetector(sample_rate=48000)
        proc = TTRallyProcessor(detector=det, max_queue=2, sample_rate=48000)
        proc.start()
        try:
            frame = np.zeros(240, dtype=np.float32)
            proc.ingest_frame(frame)
            proc.ingest_frame(frame)
            proc.ingest_frame(frame)
            assert proc._chunk_queue.qsize() <= 2
        finally:
            proc.stop()

    def test_raw_frame_to_window_conversion(self):
        det = ImpactDetector(abs_min_energy=0.0, threshold_multiplier=1.0, cooldown_ms=0.0, sample_rate=48000)
        proc = TTRallyProcessor(detector=det, sample_rate=48000)
        proc.start()
        try:
            frame = np.zeros(240, dtype=np.float32)
            frame[120] = 1.0
            proc.ingest_frame(frame)
            time.sleep(0.2)
            events = proc.get_events()
            assert len(events) > 0
            assert events[0].event_type == "impact"
        finally:
            proc.stop()

    def test_event_emission(self):
        det = ImpactDetector(abs_min_energy=0.0, threshold_multiplier=1.0, cooldown_ms=0.0, sample_rate=48000)
        proc = TTRallyProcessor(detector=det, sample_rate=48000)
        proc.start()
        try:
            window = np.zeros(240, dtype=np.float32)
            window[120] = 1.0
            proc.ingest_window(window, timestamp=0.0)
            time.sleep(0.2)
            events = proc.get_events()
            assert len(events) == 1
        finally:
            proc.stop()

    def test_graceful_stop(self):
        det = ImpactDetector(sample_rate=48000)
        proc = TTRallyProcessor(detector=det, sample_rate=48000)
        proc.start()
        proc.stop()
        assert proc._chunk_queue.empty()
        assert proc._event_queue.empty()
