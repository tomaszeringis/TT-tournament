"""
Tests for voice metrics (Phase 2).
"""

import time

import pytest

from tournament_platform.app.services.voice.metrics import VoiceMetrics, LatencySample


class TestVoiceMetrics:
    def test_empty_summarize(self):
        vm = VoiceMetrics()
        assert vm.summarize() == {"count": 0}

    def test_record_and_summarize(self):
        vm = VoiceMetrics()
        vm.record_latency(100.0, stage="asr")
        vm.record_latency(200.0, stage="asr")
        vm.record_latency(50.0, stage="asr")
        summary = vm.summarize()
        assert summary["count"] == 3
        assert summary["min_ms"] == 50.0
        assert summary["max_ms"] == 200.0
        assert summary["median_ms"] == 100.0

    def test_clear(self):
        vm = VoiceMetrics()
        vm.record_latency(100.0)
        vm.clear()
        assert vm.summarize() == {"count": 0}

    def test_bounded_samples(self):
        vm = VoiceMetrics(max_samples=10)
        for i in range(20):
            vm.record_latency(float(i))
        assert len(vm._samples) == 10
        assert vm.summarize()["count"] == 10
