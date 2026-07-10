"""
Tests for voice audio pipeline (Phase 2).
"""

import numpy as np
import pytest

from tournament_platform.app.services.voice.audio_pipeline import (
    AudioPipeline,
    PipelineResult,
    _compute_rms,
    _apply_noise_gate,
    validate_pcm,
)


class TestComputeRms:
    def test_empty_bytes(self):
        assert _compute_rms(b"") == 0.0

    def test_silence(self):
        assert _compute_rms(b"\x00\x00") == 0.0

    def test_sine_wave(self):
        samples = np.int16(np.sin(np.linspace(0, 2 * np.pi, 16000)) * 32767).tobytes()
        rms = _compute_rms(samples)
        assert 0.0 < rms < 1.0

    def test_single_sample(self):
        assert _compute_rms(b"\x00\x00") == 0.0


class TestApplyNoiseGate:
    def test_disabled_gate(self):
        pcm = b"\x00" * 100
        out, gated = _apply_noise_gate(pcm, 0.0)
        assert out == pcm
        assert gated is False

    def test_enabled_gate_above_threshold(self):
        # 0x7FFF is max positive int16 (32767), well above threshold
        pcm = np.int16(32767).tobytes() * 10
        out, gated = _apply_noise_gate(pcm, 0.001)
        assert out == pcm
        assert gated is False

    def test_enabled_gate_below_threshold(self):
        pcm = b"\x00\x00"
        out, gated = _apply_noise_gate(pcm, 0.5)
        assert out == b""
        assert gated is True


class TestValidatePcm:
    def test_valid_pcm(self):
        assert validate_pcm(b"\x00\x00\x00\x00") is True

    def test_empty_pcm(self):
        assert validate_pcm(b"") is False

    def test_odd_length(self):
        assert validate_pcm(b"\x00\x00\x00") is False


class TestAudioPipeline:
    def test_process_push_to_talk_returns_pcm(self):
        pipeline = AudioPipeline(noise_threshold=0.0)
        # Generate 1 second of silence as float32 WAV-ish bytes
        silence = np.zeros(16000, dtype=np.float32).tobytes()
        result = pipeline.process_push_to_talk(silence, src_rate=16000, src_format="f32", src_channels=1)
        assert isinstance(result, PipelineResult)
        assert validate_pcm(result.pcm_bytes)
        assert result.sample_rate == 16000
        assert result.channels == 1

    def test_process_push_to_talk_noise_gate(self):
        pipeline = AudioPipeline(noise_threshold=0.5, enable_noise_filtering=True)
        silence = np.zeros(16000, dtype=np.float32).tobytes()
        result = pipeline.process_push_to_talk(silence, src_rate=16000, src_format="f32", src_channels=1)
        assert result.noise_gated or result.pcm_bytes == b""

    def test_process_push_to_talk_metadata(self):
        pipeline = AudioPipeline()
        silence = np.zeros(16000, dtype=np.float32).tobytes()
        result = pipeline.process_push_to_talk(silence, src_rate=16000, src_format="f32", src_channels=1)
        assert "pipeline_ms" in result.metadata
        assert result.metadata["pipeline_ms"] > 0
