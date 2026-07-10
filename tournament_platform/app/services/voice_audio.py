"""
Voice Audio Buffer

Buffers incoming WebRTC audio frames into utterance chunks for transcription.
Uses simple amplitude-based VAD and silence detection.
"""

import threading
import time
import logging
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

import numpy as np

# Audio format constants
SAMPLE_FORMAT_FLOAT32 = "float32"
SAMPLE_FORMAT_INT16 = "int16"

if TYPE_CHECKING:
    from tournament_platform.app.services.voice.vad import VoiceActivityDetector

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A chunk of audio data ready for transcription."""
    frames: List[bytes]
    duration_ms: float
    timestamp: float
    sample_rate: int
    channels: int
    rms: float = 0.0  # mean RMS energy of the chunk (Phase 5 observability)
    sample_format: str = SAMPLE_FORMAT_FLOAT32  # "float32" or "int16"

    def to_pcm_bytes(self) -> bytes:
        """
        Convert accumulated frames to mono PCM 16kHz int16 bytes.

        Decodes all frames, mixes stereo to mono, resamples to 16 kHz if
        needed, and produces int16 output suitable for faster-whisper.
        Falls back to numpy interp if av resampling is unavailable.
        """
        if not self.frames:
            return b""

        # Decode all frames to float32 arrays, handling both int16 and float32
        arrays = []
        for frame_bytes in self.frames:
            if not frame_bytes:
                continue
            if self.sample_format == SAMPLE_FORMAT_INT16:
                audio = np.frombuffer(frame_bytes, dtype=np.int16)
                if len(audio) == 0:
                    continue
                audio = audio.astype(np.float32) / 32768.0
            else:
                audio = np.frombuffer(frame_bytes, dtype=np.float32)
                if len(audio) == 0:
                    continue
            arrays.append(audio)

        if not arrays:
            return b""

        combined = np.concatenate(arrays)

        # Convert to mono if stereo
        if self.channels == 2 and len(combined) % 2 == 0:
            combined = combined.reshape(-1, 2).mean(axis=1)

        # Resample to 16 kHz if needed; prefer av for quality/parity with
        # the push-to-talk path, fall back to numpy if av is unavailable.
        if self.sample_rate != 16000 and len(combined) > 0:
            try:
                import av

                ndarray = combined.reshape(1, -1).astype(np.float32)
                frame = av.AudioFrame.from_ndarray(ndarray, format="flt", layout="mono")
                frame.rate = self.sample_rate
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
                resampled = resampler.resample(frame)
                out = b"".join(f.to_ndarray().tobytes() for f in resampled)
                if out:
                    return out
            except Exception:
                pass

            duration = len(combined) / self.sample_rate
            target_len = int(duration * 16000)
            if target_len > 0:
                indices = np.linspace(0, len(combined) - 1, target_len)
                combined = np.interp(indices, np.arange(len(combined)), combined)

        # Convert float32 [-1, 1] to int16 [-32768, 32767]
        int16_audio = np.clip(combined * 32767, -32768, 32767).astype(np.int16)
        return int16_audio.tobytes()


class VoiceAudioBuffer:
    """
    Buffers WebRTC audio frames into utterance chunks.
    
    Uses amplitude-based silence detection to split utterances.
    Thread-safe for use with WebRTC audio callbacks.
    """
    
    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        silence_threshold: float = 0.01,
        min_speech_duration_ms: float = 300.0,
        max_chunk_duration_ms: float = 2000.0,
        silence_duration_ms: float = 400.0,
        noise_gate_rms: float = 0.0,
        sample_format: str = SAMPLE_FORMAT_FLOAT32,
        vad: Optional["VoiceActivityDetector"] = None,
    ):
        """
        Initialize the audio buffer.
        
        Args:
            sample_rate: Expected input sample rate (WebRTC default 48kHz)
            channels: Expected input channels (WebRTC default 2 for stereo)
            silence_threshold: RMS threshold below which audio is considered silent
            min_speech_duration_ms: Minimum speech duration before emitting a chunk
            max_chunk_duration_ms: Maximum chunk duration before forced emission
            silence_duration_ms: Duration of silence that triggers chunk emission
            noise_gate_rms: Minimum speech-energy floor (RMS). Frames below this
                are not treated as speech. 0.0 disables the gate (Phase 5).
            sample_format: Audio sample format - "float32" or "int16".
                WebRTC typically delivers int16; faster-whisper expects int16 PCM.
            vad: Optional VoiceActivityDetector. When provided, its is_speech()
                result takes precedence over the amplitude-only decision.
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.silence_threshold = silence_threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_chunk_duration_ms = max_chunk_duration_ms
        self.silence_duration_ms = silence_duration_ms
        self.noise_gate_rms = noise_gate_rms
        self.sample_format = sample_format
        self.vad = vad

        self._lock = threading.Lock()
        self._buffer: List[bytes] = []
        self._buffer_start_time: Optional[float] = None
        self._last_speech_time: Optional[float] = None
        self._total_samples: int = 0
        self._rms_sum: float = 0.0  # accumulated frame RMS for current chunk
        self._rms_frames: int = 0  # frame count for current chunk
        
        # Calculate samples per duration
        self._samples_per_ms = self.sample_rate / 1000.0
        self._min_speech_samples = int(self.min_speech_duration_ms * self._samples_per_ms)
        self._max_chunk_samples = int(self.max_chunk_duration_ms * self._samples_per_ms)
        self._silence_samples = int(self.silence_duration_ms * self._samples_per_ms)
    
    def _compute_rms(self, frame_bytes: bytes) -> float:
        """Compute RMS amplitude of an audio frame."""
        if not frame_bytes:
            return 0.0
        try:
            if self.sample_format == SAMPLE_FORMAT_INT16:
                # int16 audio: values range from -32768 to 32767
                audio = np.frombuffer(frame_bytes, dtype=np.int16)
                if len(audio) == 0:
                    return 0.0
                # Normalize to [-1, 1] for consistent RMS calculation
                float_audio = audio.astype(np.float32) / 32768.0
                return float(np.sqrt(np.mean(float_audio ** 2)))
            else:
                # float32 audio: values range from -1.0 to 1.0
                audio = np.frombuffer(frame_bytes, dtype=np.float32)
                if len(audio) == 0:
                    return 0.0
                return float(np.sqrt(np.mean(audio ** 2)))
        except Exception:
            return 0.0
    
    def _get_frame_duration_ms(self, frame_bytes: bytes) -> float:
        """Get duration of a frame in milliseconds."""
        if not frame_bytes:
            return 0.0
        # bytes per sample depends on format
        if self.sample_format == SAMPLE_FORMAT_INT16:
            bytes_per_sample = 2
        else:
            bytes_per_sample = 4  # float32
        num_samples = len(frame_bytes) / (bytes_per_sample * self.channels)
        return (num_samples / self.sample_rate) * 1000.0
    
    def push_frame(self, frame_bytes: bytes) -> Optional[AudioChunk]:
        """
        Push an audio frame into the buffer.
        
        Args:
            frame_bytes: Raw audio frame bytes from WebRTC (float32 interleaved)
            
        Returns:
            AudioChunk if a complete utterance was detected, None otherwise.
        """
        if not frame_bytes:
            return None
        
        with self._lock:
            now = time.time()
            frame_duration_ms = self._get_frame_duration_ms(frame_bytes)
            rms = self._compute_rms(frame_bytes)
            # Noise gate: a frame must exceed the minimum speech-energy floor
            # to count as speech (Phase 5).
            passes_noise_gate = self.noise_gate_rms <= 0.0 or rms >= self.noise_gate_rms
            # VAD (Phase 3): if a VAD is configured, let it decide speech first.
            vad_speech = False
            if passes_noise_gate and self.vad is not None:
                vad_speech = self.vad.is_speech(frame_bytes, self.sample_rate)
            is_speech = vad_speech or (passes_noise_gate and rms > self.silence_threshold)
            # Accumulate RMS for per-chunk mean energy reporting.
            self._rms_sum += rms
            self._rms_frames += 1
            
            # Initialize buffer start time
            if self._buffer_start_time is None:
                self._buffer_start_time = now
                self._last_speech_time = now if is_speech else None
            
            # Add frame to buffer
            self._buffer.append(frame_bytes)
            
            # Estimate total samples (approximate from frame size)
            if self.sample_format == SAMPLE_FORMAT_INT16:
                bytes_per_sample = 2
            else:
                bytes_per_sample = 4  # float32
            self._total_samples += len(frame_bytes) // (bytes_per_sample * self.channels)
            
            # Update last speech time if this frame contains speech
            if is_speech:
                self._last_speech_time = now
            
            # Check if we should emit a chunk
            chunk = self._check_emit(now, is_speech)
            if chunk:
                return chunk
            
            return None
    
    def _check_emit(self, now: float, is_speech: bool) -> Optional[AudioChunk]:
        """
        Check if buffer should be emitted as a chunk.
        
        Returns:
            AudioChunk if conditions are met, None otherwise.
        """
        if not self._buffer:
            return None
        
        # Calculate buffer duration
        if self._buffer_start_time is None:
            return None
        
        buffer_duration_ms = (now - self._buffer_start_time) * 1000.0
        
        # Condition 1: Max chunk duration exceeded
        if buffer_duration_ms >= self.max_chunk_duration_ms:
            logger.debug("Emitting chunk: max duration exceeded (%.1f ms)", buffer_duration_ms)
            return self._emit_chunk(now)
        
        # Condition 2: Silence after speech
        if self._last_speech_time is not None and not is_speech:
            silence_duration_ms = (now - self._last_speech_time) * 1000.0
            if silence_duration_ms >= self.silence_duration_ms:
                # Only emit if we have enough speech
                if buffer_duration_ms >= self.min_speech_duration_ms:
                    logger.debug(
                        "Emitting chunk: silence after speech (%.1f ms silence, %.1f ms total)",
                        silence_duration_ms, buffer_duration_ms,
                    )
                    return self._emit_chunk(now)
                else:
                    logger.debug(
                        "Not emitting: speech too short (%.1f ms < %.1f ms min)",
                        buffer_duration_ms, self.min_speech_duration_ms,
                    )
        
        return None
    
    def _emit_chunk(self, end_time: float) -> AudioChunk:
        """Create and return an AudioChunk from the current buffer."""
        # Mean RMS energy across frames in this chunk (0.0 if no frames).
        mean_rms = (self._rms_sum / self._rms_frames) if self._rms_frames else 0.0
        chunk = AudioChunk(
            frames=self._buffer.copy(),
            duration_ms=(end_time - self._buffer_start_time) * 1000.0 if self._buffer_start_time else 0.0,
            timestamp=self._buffer_start_time or end_time,
            sample_rate=self.sample_rate,
            channels=self.channels,
            rms=mean_rms,
            sample_format=self.sample_format,
        )

        # Reset buffer and RMS accumulators
        self._buffer = []
        self._buffer_start_time = None
        self._last_speech_time = None
        self._total_samples = 0
        self._rms_sum = 0.0
        self._rms_frames = 0
        
        logger.debug(
            "Emitted audio chunk: %.1f ms, %d frames",
            chunk.duration_ms,
            len(chunk.frames),
        )
        
        return chunk
    
    def flush(self) -> Optional[AudioChunk]:
        """
        Flush any remaining audio in the buffer.
        
        Returns:
            AudioChunk if buffer has data, None otherwise.
        """
        with self._lock:
            if not self._buffer:
                return None
            
            now = time.time()
            return self._emit_chunk(now)
    
    def reset(self) -> None:
        """Reset the buffer, discarding any accumulated audio."""
        with self._lock:
            self._buffer = []
            self._buffer_start_time = None
            self._last_speech_time = None
            self._total_samples = 0
            self._rms_sum = 0.0
            self._rms_frames = 0
    
    def get_buffer_duration_ms(self) -> float:
        """Get current buffer duration in milliseconds."""
        with self._lock:
            if self._buffer_start_time is None:
                return 0.0
            return (time.time() - self._buffer_start_time) * 1000.0

    def update_format(self, sample_rate: Optional[int] = None, channels: Optional[int] = None, sample_format: Optional[str] = None) -> None:
        """
        Update buffer format parameters dynamically.

        Thread-safe. Used when incoming frames have different format than
        the buffer was initialized with.
        """
        with self._lock:
            if sample_rate is not None:
                self.sample_rate = sample_rate
                self._samples_per_ms = self.sample_rate / 1000.0
                self._min_speech_samples = int(self.min_speech_duration_ms * self._samples_per_ms)
                self._max_chunk_samples = int(self.max_chunk_duration_ms * self._samples_per_ms)
                self._silence_samples = int(self.silence_duration_ms * self._samples_per_ms)
            if channels is not None:
                self.channels = channels
            if sample_format is not None:
                self.sample_format = sample_format
