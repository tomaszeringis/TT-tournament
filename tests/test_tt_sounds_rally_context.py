"""Tests for TT Sounds rally context manager."""

import pytest

from tournament_platform.app.services.tt_sounds.rally_context import RallyManager
from tournament_platform.app.services.tt_sounds.schemas import TTAudioEvent


class TestRallyManager:
    def test_rally_start_and_end(self):
        mgr = RallyManager(rally_gap_threshold=2.0)
        e1 = TTAudioEvent(timestamp=0.0, event_type="impact", energy=0.1, confidence=0.5, source="tt", sample_rate=48000, channels=1)
        e2 = TTAudioEvent(timestamp=1.0, event_type="impact", energy=0.2, confidence=0.6, source="tt", sample_rate=48000, channels=1)
        assert mgr.add_event(e1) is None
        assert mgr.add_event(e2) is None
        summary = mgr.finalize_current_rally(last_action="point_scored")
        assert summary is not None
        assert summary.impact_count == 2
        assert summary.last_action == "point_scored"

    def test_gap_ends_rally(self):
        mgr = RallyManager(rally_gap_threshold=2.0)
        e1 = TTAudioEvent(timestamp=0.0, event_type="impact", energy=0.1, confidence=0.5, source="tt", sample_rate=48000, channels=1)
        e2 = TTAudioEvent(timestamp=3.0, event_type="impact", energy=0.2, confidence=0.6, source="tt", sample_rate=48000, channels=1)
        mgr.add_event(e1)
        summary = mgr.add_event(e2)
        assert summary is not None
        assert summary.impact_count == 1

    def test_max_event_cap(self):
        mgr = RallyManager(max_events=5)
        for i in range(10):
            e = TTAudioEvent(timestamp=float(i), event_type="impact", energy=0.1, confidence=0.5, source="tt", sample_rate=48000, channels=1)
            mgr.add_event(e)
        ctx = mgr.current_context()
        assert len(ctx.impacts) == 5

    def test_empty_input_finalize_returns_none(self):
        mgr = RallyManager()
        assert mgr.finalize_current_rally() is None

    def test_finalize_on_point_scored(self):
        mgr = RallyManager()
        e1 = TTAudioEvent(timestamp=0.0, event_type="impact", energy=0.1, confidence=0.5, source="tt", sample_rate=48000, channels=1)
        mgr.add_event(e1)
        summary = mgr.finalize_current_rally(last_action="point_scored")
        assert summary is not None
        assert len(mgr.summaries()) == 1
