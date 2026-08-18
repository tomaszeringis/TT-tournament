"""
Vision Worker — lifecycle-managed background frame processor.

Owns a single background thread that drains frames from a bounded input
queue, runs a user-supplied processing callback, and emits events to a
thread-safe output queue. No Streamlit APIs are called from the worker
thread, and st.session_state is never mutated directly.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Optional

logger = logging.getLogger(__name__)


@dataclass
class VisionWorkerHealth:
    """Thread-safe health snapshot exposed to the UI thread."""

    alive: bool = False
    healthy: bool = False
    error: Optional[str] = None
    frames_received: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    inference_latency_ms: float = 0.0
    started_at: float = 0.0
    last_frame_at: float = 0.0


class VisionWorker:
    """Lifecycle-managed worker for processing video frames off the WebRTC callback.

    Exactly one worker per active camera/session. The worker is started once,
    processes frames from an internal queue, and can be cleanly stopped.
    """

    def __init__(
        self,
        processing_callback: Callable[[Any], Optional[list[Any]]],
        max_queue_size: int = 2,
        name: str = "vision-worker",
    ) -> None:
        self._processing_callback = processing_callback
        self._max_queue_size = max_queue_size
        self._name = name

        self._frame_queue: Deque[Any] = deque(maxlen=max_queue_size)
        self._frame_lock = threading.Lock()
        self._frame_available = threading.Event()

        self._event_queue: Deque[Any] = deque()
        self._event_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._health = VisionWorkerHealth()
        self._health_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the worker thread once."""
        with self._health_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._health = VisionWorkerHealth(
                alive=True,
                healthy=True,
                started_at=time.monotonic(),
            )
            self._thread = threading.Thread(
                target=self._run,
                name=self._name,
                daemon=True,
            )
            self._thread.start()
            logger.debug("VisionWorker started")

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._stop_event.set()
        self._frame_available.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._health_lock:
            self._health.alive = False
            self._thread = None
        logger.debug("VisionWorker stopped")

    # ------------------------------------------------------------------
    # Input / Output
    # ------------------------------------------------------------------

    def enqueue_frame(self, frame: Any) -> None:
        """Enqueue a frame for processing.

        Drops the oldest frame if the queue is full. Never blocks the caller.
        """
        with self._frame_lock:
            if len(self._frame_queue) >= self._max_queue_size:
                self._frame_queue.popleft()
                self._increment_metric("frames_dropped")
            self._frame_queue.append(frame)
        self._frame_available.set()

    def drain_events(self) -> list[Any]:
        """Return all pending events and clear the output buffer."""
        with self._event_lock:
            events = list(self._event_queue)
            self._event_queue.clear()
        return events

    # ------------------------------------------------------------------
    # Health / Metrics
    # ------------------------------------------------------------------

    def get_health(self) -> VisionWorkerHealth:
        """Return a snapshot of current worker health."""
        with self._health_lock:
            return VisionWorkerHealth(
                alive=self._health.alive and (self._thread is not None and self._thread.is_alive()),
                healthy=self._health.healthy,
                error=self._health.error,
                frames_received=self._health.frames_received,
                frames_processed=self._health.frames_processed,
                frames_dropped=self._health.frames_dropped,
                inference_latency_ms=self._health.inference_latency_ms,
                started_at=self._health.started_at,
                last_frame_at=self._health.last_frame_at,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        logger.debug("VisionWorker loop started")
        while not self._stop_event.is_set():
            self._frame_available.wait(timeout=0.05)
            self._frame_available.clear()

            frame = None
            with self._frame_lock:
                if self._frame_queue:
                    frame = self._frame_queue.popleft()

            if frame is None:
                continue

            self._increment_metric("frames_received")
            self._update_metric("last_frame_at", time.monotonic())

            start = time.perf_counter()
            try:
                events = self._processing_callback(frame)
                if events:
                    with self._event_lock:
                        self._event_queue.extend(events)
            except Exception as exc:
                logger.exception("VisionWorker processing error")
                with self._health_lock:
                    self._health.healthy = False
                    self._health.error = str(exc)
                # Continue running rather than crashing so manual/voice survive.
            finally:
                latency = (time.perf_counter() - start) * 1000.0
                self._update_metric("inference_latency_ms", latency)
                self._increment_metric("frames_processed")

        logger.debug("VisionWorker loop exited")

    def _increment_metric(self, name: str) -> None:
        with self._health_lock:
            current = getattr(self._health, name, 0)
            setattr(self._health, name, current + 1)

    def _update_metric(self, name: str, value: float) -> None:
        with self._health_lock:
            setattr(self._health, name, value)
