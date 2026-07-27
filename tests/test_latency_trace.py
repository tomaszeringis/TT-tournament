"""Tests for Phase 1 latency event tracing."""

import pytest
import time
from tournament_platform.app.services.latency_trace import (
    LatencyEvent,
    record_latency,
    latency_stats,
    recent_events,
    clear_latency_history,
)


class TestLatencyEventDataclass:
    def test_event_is_immutable(self):
        """LatencyEvent must be frozen/immutable."""
        event = LatencyEvent(
            trace_id="abc123",
            action_id="action1",
            match_id=1,
            source="manual",
            stage="score_apply",
            started_ns=time.time_ns(),
            finished_ns=time.time_ns() + 10_000_000,
            success=True,
        )
        # Dataclass should be frozen - cannot modify fields
        with pytest.raises(Exception):  # FrozenInstanceError
            event.success = False

    def test_event_fields(self):
        """All fields should be accessible."""
        event = LatencyEvent(
            trace_id="trace1",
            action_id="action1",
            match_id=None,
            source="voice",
            stage="db_persist",
            started_ns=1000,
            finished_ns=2000,
            success=False,
        )
        assert event.trace_id == "trace1"
        assert event.action_id == "action1"
        assert event.match_id is None
        assert event.source == "voice"
        assert event.stage == "db_persist"
        assert event.duration_ms == pytest.approx(0.001)


class TestLatencyRecording:
    def test_record_latency_appends_events(self):
        clear_latency_history()
        record_latency(
            trace_id="t1",
            action_id="a1",
            match_id=1,
            source="manual",
            stage="button_click",
            started_ns=1000,
            finished_ns=2000,
            success=True,
        )
        events = recent_events()
        assert len(events) == 1
        assert events[0]["trace_id"] == "t1"

    def test_latency_history_is_bounded(self):
        clear_latency_history()
        for i in range(300):
            record_latency(
                trace_id=f"t{i}",
                action_id=f"a{i}",
                match_id=i,
                source="manual",
                stage="score_apply",
                started_ns=1000,
                finished_ns=2000,
                success=True,
            )
        # Should be bounded to 200
        events = recent_events()
        assert len(events) == 200

    def test_clear_latency_history(self):
        clear_latency_history()
        record_latency("t1", "a1", None, "manual", "score_apply", 1000, 2000, True)
        clear_latency_history()
        assert len(recent_events()) == 0


class TestLatencyStats:
    def test_latency_stats_empty(self):
        clear_latency_history()
        stats = latency_stats()
        assert stats["count"] == 0
        assert stats["p50_ms"] == 0.0
        assert stats["p95_ms"] == 0.0
        assert stats["max_ms"] == 0.0

    def test_latency_stats_calculates_percentiles(self):
        clear_latency_history()
        # Add 10 events with varying durations
        for i in range(10):
            record_latency(
                trace_id=f"t{i}",
                action_id=f"a{i}",
                match_id=i,
                source="manual",
                stage="score_apply",
                started_ns=i * 10_000_000,
                finished_ns=(i + 1) * 10_000_000,
                success=True,
            )
        stats = latency_stats()
        assert stats["count"] == 10
        assert stats["p50_ms"] == pytest.approx(5.0)
        assert stats["p95_ms"] > 0
        assert stats["max_ms"] == pytest.approx(90.0)

    def test_latency_stats_filters_by_source(self):
        clear_latency_history()
        record_latency("t1", "a1", None, "manual", "score_apply", 1000, 11_000_000, True)
        record_latency("t2", "a2", None, "voice", "score_apply", 1000, 20_000_000, True)
        stats = latency_stats(source="manual")
        assert stats["count"] == 1

    def test_latency_stats_filters_by_stage(self):
        clear_latency_history()
        record_latency("t1", "a1", None, "manual", "button_click", 1000, 5_000_000, True)
        record_latency("t2", "a2", None, "manual", "score_apply", 1000, 15_000_000, True)
        stats = latency_stats(stage="score_apply")
        assert stats["count"] == 1
        assert stats["p50_ms"] == pytest.approx(15.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])