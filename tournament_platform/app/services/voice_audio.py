"""
Voice Audio Buffer

Buffers incoming WebRTC audio frames into utterance chunks for transcription.
Uses simple amplitude-based VAD and silence detection.
"""

import threading
import time
import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A chunk of audio data ready for transcription."""
    frames: List[bytes]
    duration_ms: float
    timestamp: float
    sample_rate: int
    channels: int

    def to_pcm_bytes(self) -> bytes:
        """
        Convert accumulated frames to mono PCM 16kHz int16 bytes.
        
        Returns:
            Mono PCM 16kHz audio as bytes suitable for faster-whisper.
        """
        if not self.frames:
            return b""

        # Decode all frames to numpy arrays
        arrays = []
        for frame_bytes in self.frames:
            # Assume float32 interleaved audio from WebRTC
            audio = np.frombuffer(frame_bytes, dtype=np.float32)
            arrays.append(audio)

        if not arrays:
            return b""

        # Concatenate all audio
        combined = np.concatenate(arrays)

        # Convert to mono if stereo
        if self.channels == 2:
            combined = combined.reshape(-1, 2).mean(axis=1)

        # Resample to 16kHz if needed
        target_rate = 16000
        if self.sample_rate != target_rate:
            # Simple linear interpolation resampling
            duration = len(combined) / self.sample_rate
            target_length = int(duration * target_rate)
            indices = np.linspace(0, len(combined) - 1, target_length)
            combined = np.interp(indices, np.arange(len(combined)), combined)

        # Convert float32 [-1, 1] to int16 [-32768, 32767]
        int16_audio = (combined * 32767).astype(np.int16)
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
        max_chunk_duration_ms: float = 3000.0,
        silence_duration_ms: float = 500.0,
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
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.silence_threshold = silence_threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_chunk_duration_ms = max_chunk_duration_ms
        self.silence_duration_ms = silence_duration_ms
        
        self._lock = threading.Lock()
        self._buffer: List[bytes] = []
        self._buffer_start_time: Optional[float] = None
        self._last_speech_time: Optional[float] = None
        self._total_samples: int = 0
        
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
        # float32 = 4 bytes per sample
        bytes_per_sample = 4
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
            is_speech = rms > self.silence_threshold
            
            # Initialize buffer start time
            if self._buffer_start_time is None:
                self._buffer_start_time = now
                self._last_speech_time = now if is_speech else None
            
            # Add frame to buffer
            self._buffer.append(frame_bytes)
            
            # Estimate total samples (approximate from frame size)
            self._total_samples += len(frame_bytes) // (4 * self.channels)
            
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
            return self._emit_chunk(now)
        
        # Condition 2: Silence after speech
        if self._last_speech_time is not None and not is_speech:
            silence_duration_ms = (now - self._last_speech_time) * 1000.0
            if silence_duration_ms >= self.silence_duration_ms:
                # Only emit if we have enough speech
                if buffer_duration_ms >= self.min_speech_duration_ms:
                    return self._emit_chunk(now)
        
        return None
    
    def _emit_chunk(self, end_time: float) -> AudioChunk:
        """Create and return an AudioChunk from the current buffer."""
        chunk = AudioChunk(
            frames=self._buffer.copy(),
            duration_ms=(end_time - self._buffer_start_time) * 1000.0 if self._buffer_start_time else 0.0,
            timestamp=self._buffer_start_time or end_time,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )
        
        # Reset buffer
        self._buffer = []
        self._buffer_start_time = None
        self._last_speech_time = None
        self._total_samples = 0
        
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
    
    def get_buffer_duration_ms(self) -> float:
        """Get current buffer duration in milliseconds."""
        with self._lock:
            if self._buffer_start_time is None:
                return 0.0
            return (time.time() - self._buffer_start_time) * 1000.0
