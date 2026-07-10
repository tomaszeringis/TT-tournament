"""
Tests for voice audio processing (AudioChunk, VoiceAudioBuffer).
"""

import time
import pytest
import numpy as np

from tournament_platform.app.services.voice_audio import (
    AudioChunk,
    VoiceAudioBuffer,
    SAMPLE_FORMAT_FLOAT32,
    SAMPLE_FORMAT_INT16,
)


class TestAudioChunkToPcmBytes:
    """Tests for AudioChunk.to_pcm_bytes conversion."""

    def test_float32_silence_returns_empty(self):
        chunk = AudioChunk(
            frames=[b""],
            duration_ms=0.0,
            timestamp=0.0,
            sample_rate=16000,
            channels=1,
        )
        assert chunk.to_pcm_bytes() == b""

    def test_float32_mono_16k_passthrough(self):
        # Generate 0.1s of 1kHz sine wave in float32
        sr = 16000
        t = np.linspace(0, 0.1, int(sr * 0.1), endpoint=False)
        audio = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        frame_bytes = audio.tobytes()
        chunk = AudioChunk(
            frames=[frame_bytes],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=1,
        )
        result = chunk.to_pcm_bytes()
        # Should be non-empty int16 bytes
        assert len(result) > 0
        # float32 is 4 bytes/sample, int16 is 2 bytes/sample, so result is half the size
        assert len(result) == len(frame_bytes) // 2

    def test_int16_mono_16k_passthrough(self):
        sr = 16000
        audio = np.array([100, -100, 200, -200], dtype=np.int16)
        frame_bytes = audio.tobytes()
        chunk = AudioChunk(
            frames=[frame_bytes],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=1,
            sample_format=SAMPLE_FORMAT_INT16,
        )
        result = chunk.to_pcm_bytes()
        # Should be non-empty int16 bytes
        assert len(result) > 0
        assert len(result) == len(frame_bytes)

    def test_stereo_to_mono_conversion(self):
        sr = 16000
        # Stereo: left = 100, right = 200
        audio = np.array([100, 200, -100, -200], dtype=np.int16)
        frame_bytes = audio.tobytes()
        chunk = AudioChunk(
            frames=[frame_bytes],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=2,
            sample_format=SAMPLE_FORMAT_INT16,
        )
        result = chunk.to_pcm_bytes()
        # Stereo 4 bytes -> mono 2 bytes (2 samples)
        assert len(result) == 4

    def test_resample_48k_to_16k(self):
        # 48000 Hz -> 16000 Hz: 3:1 ratio
        sr = 48000
        audio = np.array([100, -100, 200, -200, 300, -300], dtype=np.int16)
        frame_bytes = audio.tobytes()
        chunk = AudioChunk(
            frames=[frame_bytes],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=1,
            sample_format=SAMPLE_FORMAT_INT16,
        )
        result = chunk.to_pcm_bytes()
        # 6 samples at 48kHz -> 2 samples at 16kHz (100ms)
        assert len(result) == 4  # 2 int16 samples

    def test_multiple_frames_concatenated(self):
        sr = 16000
        audio1 = np.array([100, -100], dtype=np.int16)
        audio2 = np.array([200, -200], dtype=np.int16)
        chunk = AudioChunk(
            frames=[audio1.tobytes(), audio2.tobytes()],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=1,
            sample_format=SAMPLE_FORMAT_INT16,
        )
        result = chunk.to_pcm_bytes()
        assert len(result) == 8  # 4 int16 samples

    def test_float32_output_range(self):
        # Ensure float32 input is properly scaled to int16 range
        sr = 16000
        # Max float32 value: 1.0 -> should map to 32767
        audio = np.array([1.0, -1.0, 0.5, -0.5], dtype=np.float32)
        frame_bytes = audio.tobytes()
        chunk = AudioChunk(
            frames=[frame_bytes],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=1,
        )
        result = chunk.to_pcm_bytes()
        # Convert back to int16 to check values
        int16_result = np.frombuffer(result, dtype=np.int16)
        assert int16_result[0] == 32767 or int16_result[0] == 32766  # 1.0 * 32767
        assert int16_result[1] == -32768 or int16_result[1] == -32767  # -1.0 * 32767

    def test_float32_stereo_48k_resamples_to_16k_mono_int16(self):
        sr = 48000
        t = np.linspace(0, 0.1, int(sr * 0.1), endpoint=False)
        left = np.sin(2 * np.pi * 1000 * t)
        right = np.cos(2 * np.pi * 1000 * t)
        stereo = np.stack([left, right], axis=-1).astype(np.float32)
        frame_bytes = stereo.tobytes()
        chunk = AudioChunk(
            frames=[frame_bytes],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=2,
        )
        result = chunk.to_pcm_bytes()
        assert len(result) > 0
        # 0.1s of 16kHz mono int16 is ~3200 bytes; resampler padding
        # may produce a slightly smaller frame, so check a loose bound.
        assert 3000 <= len(result) <= 3300

    def test_empty_frames_are_skipped(self):
        sr = 16000
        audio = np.array([100.0, -100.0], dtype=np.float32).tobytes()
        chunk = AudioChunk(
            frames=[b"", audio, b""],
            duration_ms=100.0,
            timestamp=0.0,
            sample_rate=sr,
            channels=1,
        )
        result = chunk.to_pcm_bytes()
        # Should only contain the valid frame
        assert len(result) == 4


class TestVoiceAudioBufferTotalSamples:
    """Tests for _total_samples accumulation correctness."""

    def test_int16_frames_count_correctly(self):
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
            sample_format=SAMPLE_FORMAT_INT16,
            silence_threshold=0.0,
        )
        # 4 int16 samples = 8 bytes
        frame = np.array([100, -100, 200, -200], dtype=np.int16).tobytes()
        buf.push_frame(frame)
        chunk = buf.flush()
        assert chunk is not None
        assert chunk.rms > 0
        # After flush, internal accumulators are reset
        assert buf._total_samples == 0


class TestVoiceAudioBuffer:
    """Tests for VoiceAudioBuffer chunking behavior."""

    def test_silence_after_speech_emits_chunk(self):
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
            silence_threshold=0.0001,  # low threshold
            min_speech_duration_ms=50.0,
            max_chunk_duration_ms=3000.0,
            silence_duration_ms=200.0,
            sample_format=SAMPLE_FORMAT_INT16,
        )
        # Push a speech frame (use high amplitude to exceed threshold)
        # int16 max is 32767, so 0.5 * 32768 = 16384
        speech = np.array([16384, -16384], dtype=np.int16).tobytes()
        assert buf.push_frame(speech) is None  # not enough silence yet

        # Push silence for >200ms with small delays to simulate real-time
        silent = b"\x00\x00" * 160
        result = None
        for _ in range(25):  # 25 * 10ms = 250ms of silence
            time.sleep(0.01)  # 10ms delay between frames
            result = buf.push_frame(silent)
            if result is not None:
                break

        # Should have emitted a chunk after enough silence
        assert result is not None
        assert isinstance(result, AudioChunk)
        assert result.duration_ms >= 50.0  # min speech duration

    def test_max_duration_emits_chunk(self):
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
            silence_threshold=0.0,  # disable silence detection
            min_speech_duration_ms=0.0,
            max_chunk_duration_ms=100.0,
            silence_duration_ms=500.0,
            sample_format=SAMPLE_FORMAT_INT16,
        )
        # Push frames totaling >100ms with small delays
        frame = np.array([16384, -16384], dtype=np.int16).tobytes()  # 10ms
        result = None
        for i in range(15):  # 150ms total
            time.sleep(0.01)  # 10ms delay between frames
            result = buf.push_frame(frame)
            if result is not None:
                break

        assert result is not None
        assert isinstance(result, AudioChunk)
        assert result.duration_ms >= 100.0

    def test_empty_frame_returns_none(self):
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
        )
        assert buf.push_frame(b"") is None

    def test_flush_returns_remaining(self):
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
            silence_threshold=0.0,
            min_speech_duration_ms=0.0,
        )
        frame = np.array([100, -100], dtype=np.int16).tobytes()
        buf.push_frame(frame)
        result = buf.flush()
        assert result is not None
        assert isinstance(result, AudioChunk)

    def test_update_format_sample_rate(self):
        buf = VoiceAudioBuffer(sample_rate=48000, channels=2, sample_format=SAMPLE_FORMAT_FLOAT32)
        assert buf.sample_rate == 48000
        buf.update_format(sample_rate=16000)
        assert buf.sample_rate == 16000

    def test_update_format_channels(self):
        buf = VoiceAudioBuffer(channels=2)
        assert buf.channels == 2
        buf.update_format(channels=1)
        assert buf.channels == 1

    def test_update_format_sample_format(self):
        buf = VoiceAudioBuffer(sample_format=SAMPLE_FORMAT_FLOAT32)
        assert buf.sample_format == SAMPLE_FORMAT_FLOAT32
        buf.update_format(sample_format=SAMPLE_FORMAT_INT16)
        assert buf.sample_format == SAMPLE_FORMAT_INT16

    def test_update_format_recalculates_durations(self):
        buf = VoiceAudioBuffer(sample_rate=48000, min_speech_duration_ms=300.0, silence_duration_ms=500.0)
        original_min = buf._min_speech_samples
        buf.update_format(sample_rate=16000)
        assert buf._min_speech_samples == int(300.0 * 16000 / 1000.0)
        assert buf._silence_samples == int(500.0 * 16000 / 1000.0)

    def test_stereo_to_mono_pcm_after_format_update(self):
        buf = VoiceAudioBuffer(
            sample_rate=48000,
            channels=2,
            sample_format=SAMPLE_FORMAT_INT16,
            silence_threshold=0.0,
            min_speech_duration_ms=0.0,
        )
        buf.update_format(sample_rate=16000, channels=1)
        audio = np.array([100, 200, -100, -200], dtype=np.int16).tobytes()
        buf.push_frame(audio)
        chunk = buf.flush()
        assert chunk is not None
        pcm = chunk.to_pcm_bytes()
        # mono int16: 4 samples -> 8 bytes
        assert len(pcm) == 8
