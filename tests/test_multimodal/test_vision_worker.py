"""
Tests for VisionWorker lifecycle and frame processing.
"""

from __future__ import annotations

import time
import threading
import pytest

from tournament_platform.app.services.vision_worker import VisionWorker, VisionWorkerHealth


class TestVisionWorkerLifecycle:
    """Tests for VisionWorker start/stop lifecycle."""

    def test_start_sets_alive_and_healthy(self):
        worker = VisionWorker(processing_callback=lambda frame: None)
        worker.start()
        health = worker.get_health()
        assert health.alive is True
        assert health.healthy is True
        assert health.error is None
        worker.stop()

    def test_stop_clears_alive(self):
        worker = VisionWorker(processing_callback=lambda frame: None)
        worker.start()
        worker.stop(timeout=2.0)
        health = worker.get_health()
        assert health.alive is False

    def test_double_start_is_idempotent(self):
        worker = VisionWorker(processing_callback=lambda frame: None)
        worker.start()
        worker.start()  # should not create a second thread
        health = worker.get_health()
        assert health.alive is True
        worker.stop()

    def test_stop_without_start_is_safe(self):
        worker = VisionWorker(processing_callback=lambda frame: None)
        worker.stop(timeout=1.0)  # should not raise
        health = worker.get_health()
        assert health.alive is False


class TestVisionWorkerFrameProcessing:
    """Tests for frame enqueue and processing."""

    def test_enqueue_and_process_frame(self):
        processed = []

        def callback(frame):
            processed.append(frame)
            return None

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        worker.stop(timeout=2.0)
        assert processed == ["frame-1"]

    def test_drop_oldest_when_queue_full(self):
        processed = []

        def callback(frame):
            processed.append(frame)
            time.sleep(0.05)
            return None

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        worker.enqueue_frame("frame-2")
        worker.enqueue_frame("frame-3")  # should drop frame-1
        time.sleep(0.2)
        worker.stop(timeout=2.0)
        assert "frame-1" not in processed
        assert "frame-2" in processed
        assert "frame-3" in processed

    def test_enqueue_never_blocks_caller(self):
        worker = VisionWorker(processing_callback=lambda frame: time.sleep(10), max_queue_size=2)
        worker.start()
        for i in range(5):
            worker.enqueue_frame(f"frame-{i}")
        health = worker.get_health()
        assert health.frames_dropped > 0
        worker.stop(timeout=2.0)


class TestVisionWorkerHealth:
    """Tests for health and metrics."""

    def test_metrics_increment_on_processing(self):
        def callback(frame):
            return None

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        health = worker.get_health()
        assert health.frames_received == 1
        assert health.frames_processed == 1
        worker.stop(timeout=2.0)

    def test_inference_latency_recorded(self):
        def callback(frame):
            time.sleep(0.05)
            return None

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.15)
        health = worker.get_health()
        assert health.inference_latency_ms >= 40.0
        worker.stop(timeout=2.0)

    def test_crash_isolation_sets_error_state(self):
        def callback(frame):
            raise RuntimeError("inference boom")

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        health = worker.get_health()
        assert health.healthy is False
        assert health.error is not None
        assert "inference boom" in health.error
        # Worker should still be alive after error (fail-open)
        assert health.alive is True
        worker.stop(timeout=2.0)

    def test_error_does_not_crash_worker_thread(self):
        call_count = 0

        def callback(frame):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first boom")
            return None

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        health = worker.get_health()
        assert health.healthy is False

        worker.enqueue_frame("frame-2")
        time.sleep(0.1)
        assert call_count == 2
        worker.stop(timeout=2.0)


class TestVisionWorkerEvents:
    """Tests for event output queue."""

    def test_events_emitted_to_output_queue(self):
        def callback(frame):
            return ["event-1", "event-2"]

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        events = worker.drain_events()
        assert "event-1" in events
        assert "event-2" in events
        worker.stop(timeout=2.0)

    def test_drain_events_clears_buffer(self):
        def callback(frame):
            return ["event-1"]

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        worker.drain_events()
        assert worker.drain_events() == []
        worker.stop(timeout=2.0)
