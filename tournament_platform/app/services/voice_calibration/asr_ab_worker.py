"""
Phase 11.3 — Same-audio A/B runtime worker.

Runs baseline and candidate transcriptions on the same audio bytes outside
the WebRTC callback thread. Results are drained by the main thread.
"""

from __future__ import annotations

import hashlib
import threading
import queue
from typing import Any, Callable, Optional

import logging

logger = logging.getLogger(__name__)

from tournament_platform.app.services.asr_backends.base import TranscriptionResult  # noqa: E402
from tournament_platform.app.services.voice_calibration.models import (  # noqa: E402
    AsrAbSampleResult,
    AsrAbWorkItem,
    AsrExperimentTranscript,
)


class AsrAbWorker:
    """Background worker for same-audio ASR A/B experiments."""

    def __init__(
        self,
        *,
        max_queue_size: int = 16,
        transcribe_fn: Optional[Callable[[bytes, Any], TranscriptionResult]] = None,
        parse_fn: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._queue: queue.Queue[AsrAbWorkItem] = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._results: dict[str, AsrAbSampleResult] = {}
        self._canceled: set[str] = set()
        self._transcribe_fn = transcribe_fn
        self._parse_fn = parse_fn
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._processed_count = 0

    def configure(
        self,
        *,
        transcribe_fn: Callable[[bytes, Any], TranscriptionResult],
        parse_fn: Callable[[str], Any],
    ) -> None:
        """Set the transcription and parse callbacks."""
        self._transcribe_fn = transcribe_fn
        self._parse_fn = parse_fn

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop after draining the queue."""
        self._running = False
        while not self._queue.empty():
            try:
                _item = self._queue.get_nowait()
                self._queue.task_done()
                try:
                    object.__setattr__(_item, "audio_bytes", b"")
                except (AttributeError, TypeError):
                    pass
            except queue.Empty:
                break
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def enqueue(self, work_item: AsrAbWorkItem) -> bool:
        """Enqueue a work item for background processing.

        Returns False if the queue is full.
        """
        if not self._running or self._transcribe_fn is None:
            return False
        try:
            self._queue.put_nowait(work_item)
            return True
        except queue.Full:
            return False

    def cancel(self, experiment_id: str) -> None:
        """Cancel all pending samples for an experiment."""
        self._canceled.add(experiment_id)

    def drain_results(self) -> list[AsrAbSampleResult]:
        """Return completed results and clear the internal buffer."""
        with self._lock:
            results = list(self._results.values())
            self._results.clear()
            return results

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def completed_count(self) -> int:
        return self._processed_count

    def _run(self) -> None:
        while self._running:
            try:
                work_item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if work_item.experiment_id in self._canceled:
                self._queue.task_done()
                continue

            try:
                result = self._process(work_item)
                with self._lock:
                    self._results[work_item.sample_id] = result
                    self._processed_count += 1
            except Exception as exc:
                logger.debug("A/B worker sample failed: %s", exc)
            finally:
                self._queue.task_done()
                # Release audio reference from the work item
                try:
                    object.__setattr__(work_item, "audio_bytes", b"")
                except (AttributeError, TypeError):
                    pass

    def reset(self) -> None:
        """Cancel all pending work and release audio references."""
        self._canceled.clear()
        with self._lock:
            self._results.clear()
        while not self._queue.empty():
            try:
                _item = self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def _build_experiment_transcript(
        self,
        transcript: TranscriptionResult,
        parsed: Any,
    ) -> AsrExperimentTranscript:
        command_id = getattr(parsed, "command_id", None)
        confidence = getattr(parsed, "confidence", None)
        would_accept = bool(command_id and command_id != "unknown")
        return AsrExperimentTranscript(
            config_id=transcript.metadata.get("config_id", ""),
            raw_transcript=transcript.text,
            normalized_transcript=transcript.text.strip().lower(),
            language=transcript.language,
            latency_ms=transcript.latency_ms,
            average_log_probability=transcript.average_log_probability,
            no_speech_probability=transcript.no_speech_probability,
            parser_command_id=command_id,
            parser_confidence=confidence,
            would_accept_live=would_accept,
        )

    def _process(self, work_item: AsrAbWorkItem) -> AsrAbSampleResult:
        assert self._transcribe_fn is not None
        assert self._parse_fn is not None

        sha = hashlib.sha256(work_item.sample_id.encode("utf-8")).digest()
        run_candidate_first = sha[0] % 2 == 1
        first_config = work_item.candidate_config if run_candidate_first else work_item.baseline_config
        second_config = work_item.baseline_config if run_candidate_first else work_item.candidate_config

        first_transcript = self._transcribe_fn(work_item.audio_bytes, first_config)
        second_transcript = self._transcribe_fn(work_item.audio_bytes, second_config)

        first_parsed = self._parse_fn(first_transcript.text)
        second_parsed = self._parse_fn(second_transcript.text)

        if run_candidate_first:
            baseline_result = self._build_experiment_transcript(second_transcript, second_parsed)
            candidate_result = self._build_experiment_transcript(first_transcript, first_parsed)
        else:
            baseline_result = self._build_experiment_transcript(first_transcript, first_parsed)
            candidate_result = self._build_experiment_transcript(second_transcript, second_parsed)

        return AsrAbSampleResult(
            experiment_id=work_item.experiment_id,
            sample_id=work_item.sample_id,
            calibration_session_id=work_item.calibration_session_id,
            capture_kind=work_item.capture_kind,
            expected_command_id=work_item.expected_command_id,
            expected_phrase=work_item.expected_phrase,
            baseline=baseline_result,
            candidate=candidate_result,
            experiment_identity=work_item.experiment_identity,
        )
