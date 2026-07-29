"""
Voice runtime ownership module (Phase 4).

Owns the WebRTC audio processor, audio-frame conversion utilities, and the
stable / tracked processor factories. Streamlit session_state is accessed only
through explicit parameters — this module is import-safe for unit tests.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

from tournament_platform.app.services.voice_audio import (
    AudioChunk,
    SAMPLE_FORMAT_FLOAT32,
    SAMPLE_FORMAT_INT16,
    VoiceAudioBuffer,
)

# streamlit-webrtc processor base. Voice scoring degrades gracefully to
# push-to-talk if the package is unavailable, so fall back to ``object``.
try:
    from streamlit_webrtc import AudioProcessorBase
except Exception:  # pragma: no cover - optional dependency
    AudioProcessorBase = object  # type: ignore

from tournament_platform.app.services.voice.vad import VoiceActivityDetector, create_vad
from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_parser import VoiceParser, VoiceScoreEvent
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Module-level factory/processor diagnostics                                    #
# --------------------------------------------------------------------------- #
_factory_diag_lock = threading.Lock()
_factory_diag: Dict[str, Any] = {
    "call_count": 0,
    "last_error": None,
    "last_processor_id": None,
    "last_processor_class": None,
    "callback_count": 0,
    "last_exception": None,
}

# --------------------------------------------------------------------------- #
# Module-level audio frame callback diagnostics (fallback path)                 #
# --------------------------------------------------------------------------- #
_audio_callback_lock = threading.Lock()
_audio_callback_count = 0
_last_audio_frame_timestamp = 0.0
_last_audio_frame_rms = 0.0
_last_audio_frame_shape = ""
_last_audio_frame_sample_rate = 0
_last_audio_frame_method = ""
_last_main_thread_frame_audit_count = 0


def _audio_frame_callback_func(frame):
    """Fallback audio_frame_callback for streamlit-webrtc.

    Receives each ``av.AudioFrame``, increments counters, updates metadata,
    and returns the frame unchanged so the stream continues.
    Does NOT access st.session_state or any UI APIs.
    """
    global _audio_callback_count, _last_audio_frame_timestamp
    global _last_audio_frame_rms, _last_audio_frame_shape
    global _last_audio_frame_sample_rate, _last_audio_frame_method

    with _audio_callback_lock:
        _audio_callback_count += 1
        _last_audio_frame_timestamp = getattr(frame, 'pts', time.time())
        _last_audio_frame_method = "audio_frame_callback"

    try:
        if hasattr(frame, 'to_ndarray'):
            arr = np.asarray(frame.to_ndarray())
            if arr.size > 0:
                _last_audio_frame_shape = f"{arr.shape}"
                if arr.dtype in (np.float32, np.float64):
                    rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
                else:
                    rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2))) / 32768.0
                with _audio_callback_lock:
                    _last_audio_frame_rms = rms
    except Exception:
        pass

    try:
        with _audio_callback_lock:
            _last_audio_frame_sample_rate = getattr(frame, 'sample_rate', 0)
    except Exception:
        pass

    return frame


# --------------------------------------------------------------------------- #
# Audio frame conversion helpers                                               #
# --------------------------------------------------------------------------- #

def _frame_to_ndarray(frame: Any) -> Optional[np.ndarray]:
    """Extract a numpy array from a WebRTC audio frame."""
    if frame is None:
        return None
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
        return arr
    except Exception as exc:
        logger.debug("Skipping invalid audio frame: %s", exc)
        return None


def _audio_input_to_pcm(audio_file: Any) -> bytes:
    """Convert st.audio_input audio to mono PCM 16kHz int16 bytes."""
    if audio_file is None:
        logger.debug("No audio input provided")
        return b""

    if isinstance(audio_file, np.ndarray):
        return _pcm_float32_to_int16(_audio_frame_to_mono_float32(audio_file))

    if isinstance(audio_file, (list, tuple)):
        if not audio_file:
            return b""
        chunks = []
        for f in audio_file:
            arr = _frame_to_ndarray(f)
            if arr is None:
                continue
            chunks.append(_audio_frame_to_mono_float32(arr))
        if not chunks:
            logger.debug("No decodable audio frames in input list")
            return b""
        return _pcm_float32_to_int16(np.concatenate(chunks).astype(np.float32, copy=False))

    if hasattr(audio_file, "to_ndarray") and not hasattr(audio_file, "demux"):
        arr = _frame_to_ndarray(audio_file)
        if arr is None:
            return b""
        return _pcm_float32_to_int16(_audio_frame_to_mono_float32(arr))

    try:
        import av

        container = av.open(audio_file)
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=16000,
        )
        pcm_frames = []
        for packet in container.demux(stream):
            for frame in packet.decode():
                resampled = resampler.resample(frame)
                pcm_frames.append(resampled.to_ndarray().tobytes())
        return b"".join(pcm_frames)
    except Exception as exc:
        logger.debug("Failed to convert audio input to PCM: %s", exc)
        return b""


def _audio_frame_to_mono_float32(arr: np.ndarray) -> np.ndarray:
    """Convert an audio ndarray to mono float32 in ``[-1, 1]``."""
    from tournament_platform.app.services.voice.vad import normalize_audio

    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr.mean(axis=0)
    elif arr.ndim > 2:
        arr = arr.reshape(-1)
    return normalize_audio(arr)


def _pcm_float32_to_int16(arr: np.ndarray) -> bytes:
    """Convert mono float32 PCM in ``[-1, 1]`` to mono int16 16kHz bytes."""
    int16_audio = np.clip(arr * 32767, -32768, 32767).astype(np.int16)
    return int16_audio.tobytes()


# --------------------------------------------------------------------------- #
# VoiceAudioProcessor                                                         #
# --------------------------------------------------------------------------- #

class VoiceAudioProcessor(AudioProcessorBase):
    """
    Audio processor for streamlit-webrtc voice scoring.

    Receives audio frames, buffers them into chunks, and queues them for
    background transcription. A single worker thread handles all transcription
    to avoid thread explosion. The worker emits plain data tuples into
    ``event_queue``; the main Streamlit loop consumes and mutates session state.

    Inherits from ``AudioProcessorBase`` so streamlit-webrtc actually invokes
    ``recv`` / ``recv_queued`` (it never calls a custom ``recv_audio`` method).
    """

    _worker_started: bool = False

    def __init__(
        self,
        noise_gate_rms: float = 0.0,
        sample_format: str = SAMPLE_FORMAT_FLOAT32,
        voice_strict_mode: bool = False,
        vad: Optional[VoiceActivityDetector] = None,
        asr: object = None,
        tt_sounds_processor: object = None,
    ):
        """Initialize the audio processor.

        Args:
            noise_gate_rms: Minimum speech-energy floor. 0.0 disables the gate.
            sample_format: Audio sample format ("float32" or "int16").
            voice_strict_mode: If True, flag score events for confirmation.
            vad: Optional VoiceActivityDetector for improved speech detection.
            asr: Optional pre-built ASR backend. When ``None`` (default), the
                backend is lazily loaded via ``_get_asr()`` and the processor
                degrades gracefully if ASR is unavailable.
            tt_sounds_processor: Optional TTRallyProcessor for impact detection.
        """
        self._sample_format = getattr(self, '_sample_format', sample_format)
        self.audio_buffer = VoiceAudioBuffer(
            noise_gate_rms=noise_gate_rms,
            sample_format=self._sample_format,
            vad=vad,
        )
        self.vocabulary = VoiceVocabulary.load()
        self.parser = VoiceParser()
        self.post_processor = TranscriptPostProcessor(self.vocabulary)
        self.event_queue: queue.Queue = queue.Queue(maxsize=50)
        self._processing = False
        self._lock = threading.Lock()
        self._voice_strict_mode = voice_strict_mode
        self._worker_thread: Optional[threading.Thread] = None
        self._chunk_queue: queue.Queue = queue.Queue(maxsize=20)
        self._stop_worker = threading.Event()
        self._dropped_chunks = 0
        self._audio_frames_received = 0
        self._chunks_created = 0
        self._asr_events_enqueued = 0
        self._last_frame_timestamp: float = 0.0
        self._last_chunk_timestamp: float = 0.0
        self._asr = asr
        self._asr_ready = asr is not None
        self._asr_error: Optional[str] = None
        self._status: str = "idle"
        self._last_audio_error_log_ts: float = 0.0
        self._audio_error_count: int = 0
        self._callback_count: int = 0
        self.tt_sounds_processor = tt_sounds_processor
        if tt_sounds_processor is not None:
            tt_sounds_processor.start()

    def _get_asr(self):
        """Lazy-load the ASR backend."""
        if getattr(self, "_asr", None) is not None:
            return self._asr
        try:
            backend = ASRBackendFactory.create(vocabulary=self.vocabulary)
        except Exception as exc:
            self._asr_error = str(exc)
            self._asr_ready = False
            self._set_status("ASR unavailable")
            return None
        self._asr = backend
        self._asr_ready = bool(getattr(backend, "is_available", lambda: False)())
        if not self._asr_ready:
            self._asr_error = (
                getattr(backend.get_status(), "load_error", None)
                if hasattr(backend, "get_status")
                else None
            )
            self._set_status("ASR unavailable")
        else:
            self._set_status("ASR ready")
        return self._asr

    def _set_status(self, status: str) -> None:
        """Update the processor status visible in the UI diagnostics panel."""
        self._status = status

    def _log_rate_limited(self, message: str, exc: Optional[Exception] = None) -> None:
        """Log repeated audio/transcription errors at most once per 30 seconds."""
        now = time.time()
        self._audio_error_count += 1
        if now - self._last_audio_error_log_ts >= 30.0:
            last_err = str(exc) if exc else ""
            logger.warning(
                "%s: %d failures in last 30s. Last error: %s",
                message,
                self._audio_error_count,
                last_err,
            )
            self._last_audio_error_log_ts = now
            self._audio_error_count = 0

    def _start_worker(self) -> None:
        """Start the single background transcription worker if not already running."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        def _worker_loop() -> None:
            """Consume chunks from _chunk_queue and transcribe them safely."""
            while not self._stop_worker.is_set():
                asr = self._get_asr()
                if asr is None:
                    self._set_status("ASR unavailable")
                    break

                try:
                    chunk = self._chunk_queue.get(timeout=0.25)
                except queue.Empty:
                    continue

                if chunk is None:
                    continue

                self._transcribe_chunk(chunk)

        self._worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        self._worker_thread.start()

    def _ingest_frame(self, frame) -> None:
        """Process a single WebRTC audio frame and queue it for transcription."""
        import numpy as np

        fmt_name = getattr(getattr(frame, 'format', None), 'name', None)
        sample_rate = getattr(frame, 'sample_rate', None)
        channels = getattr(frame, 'channels', None)

        detected_format = None
        if fmt_name in ('s16', 's16p'):
            detected_format = SAMPLE_FORMAT_INT16
        elif fmt_name in ('flt', 'fltp', 'f32', 'f32p'):
            detected_format = SAMPLE_FORMAT_FLOAT32

        needs_flush = False
        if detected_format is not None and detected_format != self._sample_format:
            needs_flush = True
        if sample_rate is not None and sample_rate != self.audio_buffer.sample_rate:
            needs_flush = True
        if channels is not None and channels != self.audio_buffer.channels:
            needs_flush = True

        if needs_flush:
            with self.audio_buffer._lock:
                buffered = len(self.audio_buffer._buffer)
            if buffered > 0:
                flushed = self.audio_buffer.flush()
                if flushed:
                    logger.debug(
                        "VoiceAudioProcessor: flushed chunk on format change "
                        "(old_format=%s, new_format=%s, old_rate=%d, new_rate=%s, old_channels=%d, new_channels=%s)",
                        self._sample_format, detected_format or self._sample_format,
                        self.audio_buffer.sample_rate, sample_rate,
                        self.audio_buffer.channels, channels,
                    )
                    self._enqueue_chunk(flushed)

        if detected_format is not None and detected_format != self._sample_format:
            self._sample_format = detected_format
            if self.audio_buffer.sample_format != self._sample_format:
                self.audio_buffer.update_format(sample_format=self._sample_format)

        if sample_rate is not None and sample_rate != self.audio_buffer.sample_rate:
            self.audio_buffer.update_format(sample_rate=sample_rate)

        if channels is not None and channels != self.audio_buffer.channels:
            self.audio_buffer.update_format(channels=channels)

        if detected_format is None:
            try:
                array = _frame_to_ndarray(frame)
                if array is None:
                    return
                if array.dtype == np.int16:
                    fallback_format = SAMPLE_FORMAT_INT16
                else:
                    fallback_format = SAMPLE_FORMAT_FLOAT32
                if fallback_format != self._sample_format:
                    needs_flush = True
                    with self.audio_buffer._lock:
                        buffered = len(self.audio_buffer._buffer)
                    if buffered > 0:
                        flushed = self.audio_buffer.flush()
                        if flushed:
                            logger.debug(
                                "VoiceAudioProcessor: flushed chunk on fallback format change "
                                "(old_format=%s, new_format=%s)",
                                self._sample_format, fallback_format,
                            )
                            self._enqueue_chunk(flushed)
                    self._sample_format = fallback_format
                    if self.audio_buffer.sample_format != self._sample_format:
                        self.audio_buffer.update_format(sample_format=self._sample_format)
            except Exception:
                pass

        try:
            frame_bytes = _frame_to_ndarray(frame)
        except Exception as exc:
            logger.debug("Skipping invalid audio frame: %s", exc)
            return
        if frame_bytes is None:
            return
        frame_bytes = frame_bytes.tobytes()
        chunk = self.audio_buffer.push_frame(frame_bytes)

        if chunk is not None:
            logger.debug(
                "VoiceAudioProcessor: emitted chunk %.1f ms, RMS=%.4f, frames=%d, "
                "format=%s, sample_rate=%d, channels=%d",
                chunk.duration_ms, chunk.rms, len(chunk.frames),
                chunk.sample_format, chunk.sample_rate, chunk.channels,
            )
            self._enqueue_chunk(chunk)

        if self.tt_sounds_processor is not None:
            try:
                self.tt_sounds_processor.ingest_frame(frame)
            except Exception:
                pass

    def _enqueue_chunk(self, chunk: AudioChunk) -> None:
        """Enqueue a chunk with bounded queue and drop-oldest policy."""
        self._start_worker()
        self._chunks_created += 1
        self._last_chunk_timestamp = time.time()
        try:
            self._chunk_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._chunk_queue.get_nowait()
                self._dropped_chunks += 1
            except queue.Empty:
                pass
            try:
                self._chunk_queue.put_nowait(chunk)
            except queue.Full:
                pass

    def recv(self, frame):
        """streamlit-webrtc callback (sync / non-async mode)."""
        self._audio_frames_received += 1
        self._last_frame_timestamp = getattr(frame, 'pts', time.time())
        self._ingest_frame(frame)
        self._maybe_log_first_frame()
        self._callback_count += 1
        with _factory_diag_lock:
            _factory_diag["callback_count"] = self._callback_count
        return frame

    async def recv_queued(self, frames):
        """streamlit-webrtc callback (async mode — the default)."""
        for frame in frames:
            self._audio_frames_received += 1
            self._last_frame_timestamp = getattr(frame, 'pts', time.time())
            self._ingest_frame(frame)
        self._maybe_log_first_frame()
        self._callback_count += 1
        with _factory_diag_lock:
            _factory_diag["callback_count"] = self._callback_count
        return frames

    def _maybe_log_first_frame(self) -> None:
        """No-op in callback threads."""
        return

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return processor diagnostics for the UI panel."""
        return {
            "audio_frames_received": self._audio_frames_received,
            "chunks_created": self._chunks_created,
            "asr_events_enqueued": self._asr_events_enqueued,
            "dropped_chunks": self._dropped_chunks,
            "last_frame_timestamp": self._last_frame_timestamp,
            "last_chunk_timestamp": self._last_chunk_timestamp,
            "asr_ready": self._asr_ready,
            "asr_error": self._asr_error,
            "status": self._status,
            "processor_class": type(self).__name__,
            "processor_id": id(self),
            "callback_count": self._callback_count,
        }

    def _transcribe_chunk(self, chunk: AudioChunk) -> None:
        """Transcribe an audio chunk in the background worker thread."""
        try:
            asr = self._get_asr()
            if asr is None:
                self._set_status("ASR unavailable")
                logger.debug("Skipping transcription: ASR unavailable")
                return

            pcm_bytes = chunk.to_pcm_bytes()
            if not pcm_bytes:
                logger.debug("Empty PCM bytes, skipping transcription")
                return

            if chunk.rms < 0.01:
                logger.debug(
                    "Chunk RMS %.4f below floor, skipping transcription",
                    chunk.rms,
                )
                return

            logger.debug(
                "Transcribing chunk: pcm_len=%d, chunk_format=%s, chunk_rate=%d, "
                "chunk_channels=%d, chunk_rms=%.4f",
                len(pcm_bytes), chunk.sample_format, chunk.sample_rate,
                chunk.channels, chunk.rms,
            )

            start = time.time()
            raw_text = asr.transcribe_pcm(pcm_bytes)
            latency_ms = (time.time() - start) * 1000.0
            logger.debug("ASR raw result: '%s' (latency: %.1f ms)", raw_text, latency_ms)
            if not raw_text:
                return

            text = self.post_processor.process(raw_text)
            logger.debug("Post-processed text: '%s'", text)

            event = self.parser.parse(text)
            event.noise_rms = chunk.rms
            event.asr_latency_ms = latency_ms
            event.session_id = getattr(self, '_session_id', None)
            if getattr(self, '_voice_strict_mode', False) and event.type != "unknown":
                event.requires_confirmation = True

            try:
                self.event_queue.put_nowait((raw_text, text, event))
            except queue.Full:
                pass
            logger.debug("Voice event queued: type=%s, text='%s'", event.type, text)

        except Exception as e:
            self._log_rate_limited("Error in voice transcription thread", e)

    def get_events(self) -> List[Tuple[str, str, VoiceScoreEvent]]:
        """Drain all pending events from the queue."""
        events = []
        while not self.event_queue.empty():
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def has_pending_events(self) -> bool:
        """Return True if the event queue has pending events."""
        with self._lock:
            return not self.event_queue.empty()

    def peek_events(self, max_items: int = 5) -> List[Tuple[str, str, Any]]:
        """Return a snapshot of pending events without draining."""
        items = []
        with self._lock:
            q = list(self.event_queue.queue)[:max_items]
            for raw_text, text, event in q:
                items.append((
                    raw_text[:80],
                    text[:80],
                    getattr(event, 'event_id', '')[:16],
                ))
        return items

    def peek_chunks(self, max_items: int = 5) -> List[Dict[str, Any]]:
        """Return a snapshot of queued chunks without draining."""
        items = []
        with self._lock:
            q = list(self._chunk_queue.queue)[:max_items]
            for chunk in q:
                items.append({
                    "duration_ms": getattr(chunk, 'duration_ms', 0.0),
                    "frames": len(getattr(chunk, 'frames', [])),
                    "rms": getattr(chunk, 'rms', 0.0),
                    "timestamp": getattr(chunk, 'timestamp', 0.0),
                })
        return items

    def stop(self) -> None:
        """Stop processing and flush remaining audio."""
        self._stop_worker.set()
        self._set_status("stopped")
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self.audio_buffer.reset()
        with self._lock:
            while not self._chunk_queue.empty():
                try:
                    self._chunk_queue.get_nowait()
                except queue.Empty:
                    break
            while not self.event_queue.empty():
                try:
                    self.event_queue.get_nowait()
                except queue.Empty:
                    break


# --------------------------------------------------------------------------- #
# Factory helpers                                                              #
# --------------------------------------------------------------------------- #

def build_audio_processor_factory(
    filtering: bool,
    threshold: float,
    strict: bool,
    vad: Optional[VoiceActivityDetector],
    tt_sounds_enabled: bool = False,
) -> Any:
    """Build a factory that creates a configured VoiceAudioProcessor.

    The returned factory is a zero-argument callable compatible with
    ``webrtc_streamer(audio_processor_factory=...)``.
    """
    def factory():
        _tt_proc = None
        if tt_sounds_enabled:
            try:
                from tournament_platform.app.services.tt_sounds import (
                    ImpactDetector,
                    TTRallyProcessor,
                    TT_SOUNDS_ABS_MIN_ENERGY,
                    TT_SOUNDS_THRESHOLD_MULTIPLIER,
                    TT_SOUNDS_NOISE_FLOOR_DECAY,
                    TT_SOUNDS_COOLDOWN_MS,
                    TT_SOUNDS_WINDOW_MS,
                )
                _detector = ImpactDetector(
                    abs_min_energy=TT_SOUNDS_ABS_MIN_ENERGY,
                    threshold_multiplier=TT_SOUNDS_THRESHOLD_MULTIPLIER,
                    noise_floor_decay=TT_SOUNDS_NOISE_FLOOR_DECAY,
                    cooldown_ms=TT_SOUNDS_COOLDOWN_MS,
                    window_ms=TT_SOUNDS_WINDOW_MS,
                    sample_rate=48000,
                )
                _tt_proc = TTRallyProcessor(detector=_detector, sample_rate=48000)
            except Exception:
                _tt_proc = None
        try:
            return VoiceAudioProcessor(
                noise_gate_rms=threshold if filtering else 0.01,
                sample_format=SAMPLE_FORMAT_FLOAT32,
                voice_strict_mode=strict,
                vad=vad,
                tt_sounds_processor=_tt_proc,
            )
        except Exception as exc:
            raise

    return factory


def tracked_audio_processor_factory(
    raw_factory: Any,
    diag_lock: threading.Lock,
    diag: Dict[str, Any],
    session_state: Any,
) -> Any:
    """Wrap ``raw_factory`` with call-count and error tracking.

    Writes metrics into ``session_state`` so they survive Streamlit reruns.
    """
    def factory():
        with diag_lock:
            diag["call_count"] += 1
            session_state._voice_factory_call_count = diag["call_count"]
        try:
            processor = raw_factory()
            with diag_lock:
                diag["last_error"] = None
                diag["last_processor_id"] = id(processor)
                diag["last_processor_class"] = type(processor).__name__
                session_state._voice_last_processor_id = diag["last_processor_id"]
                session_state._voice_last_processor_class = diag["last_processor_class"]
            return processor
        except Exception as exc:
            with diag_lock:
                diag["last_error"] = f"{type(exc).__name__}: {exc}"
                diag["last_exception"] = exc
                session_state._voice_factory_last_error = diag["last_error"]
                session_state._voice_last_processor_exception = diag["last_exception"]
            raise

    return factory
