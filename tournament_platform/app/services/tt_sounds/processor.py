"""Queue-based worker thread for TT Sounds impact detection.

Consumes raw WebRTC frames or short normalized windows and emits TTAudioEvent
objects. Frame-to-window conversion happens inside the worker thread.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, List, Optional, Tuple

import numpy as np

from .detector import ImpactDetector
from .schemas import TTAudioEvent

logger = logging.getLogger(__name__)


class TTRallyProcessor:
    def __init__(
        self,
        detector: ImpactDetector,
        max_queue: int = 50,
        max_event_queue: int = 200,
        sample_rate: int = 48000,
    ) -> None:
        self._detector = detector
        self._chunk_queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._event_queue: queue.Queue = queue.Queue(maxsize=max_event_queue)
        self._worker_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._sample_rate = sample_rate
        self._window_samples = self._detector._compute_window_samples()

    def ingest_frame(self, frame: Any) -> None:
        try:
            self._chunk_queue.put_nowait(frame)
        except queue.Full:
            try:
                self._chunk_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._chunk_queue.put_nowait(frame)
            except queue.Full:
                pass

    def ingest_window(self, window: np.ndarray, timestamp: float) -> None:
        try:
            self._chunk_queue.put_nowait((window, timestamp))
        except queue.Full:
            try:
                self._chunk_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._chunk_queue.put_nowait((window, timestamp))
            except queue.Full:
                pass

    def _frame_to_window(self, frame: Any) -> Optional[Tuple[np.ndarray, float]]:
        try:
            if hasattr(frame, "to_ndarray"):
                arr = frame.to_ndarray()
            elif isinstance(frame, np.ndarray):
                arr = frame
            else:
                return None
            arr = np.asarray(arr)
            if arr.size == 0:
                return None
            if arr.ndim == 2:
                arr = arr.mean(axis=0)
            elif arr.ndim > 1:
                arr = arr.reshape(-1)
            max_val = float(np.max(np.abs(arr))) if arr.size else 0.0
            if max_val > 1.0:
                arr = arr / max_val
            if arr.dtype != np.float32:
                arr = arr.astype(np.float32)
            ts = time.time()
            return arr, ts
        except Exception:
            return None

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._chunk_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is None:
                continue

            try:
                if isinstance(item, tuple) and len(item) == 2:
                    window, ts = item
                    if not isinstance(window, np.ndarray):
                        continue
                else:
                    converted = self._frame_to_window(item)
                    if converted is None:
                        continue
                    window, ts = converted

                if window.size < self._window_samples:
                    continue

                start_idx = 0
                while start_idx + self._window_samples <= window.size:
                    sub = window[start_idx : start_idx + self._window_samples]
                    event = self._detector.process_window(sub, ts)
                    if event:
                        try:
                            self._event_queue.put_nowait(event)
                        except queue.Full:
                            pass
                    start_idx += self._window_samples
            except Exception as exc:
                logger.debug("TTRallyProcessor worker error: %s", exc)

    def get_events(self) -> List[TTAudioEvent]:
        events: List[TTAudioEvent] = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def start(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        while not self._chunk_queue.empty():
            try:
                self._chunk_queue.get_nowait()
            except queue.Empty:
                break
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                break
