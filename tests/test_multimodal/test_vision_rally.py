"""
Tests for RallyStateMachine.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.vision_rally import RallyStateMachine, RallyState
from tournament_platform.app.services.vision_events import VisionEvent, VisionEventType
from datetime import datetime, timezone


def _make_event(event_type, ts=1000.0):
    return VisionEvent(
        event_type=event_type,
        monotonic_timestamp=ts,
        utc_timestamp=datetime.now(timezone.utc),
    )


class TestRallyStateMachine:
    def test_initial_state_idle(self):
        sm = RallyStateMachine(rally_id="r1")
        assert sm.context.state == RallyState.IDLE

    def test_transition_to_active_on_rally_started(self):
        sm = RallyStateMachine(rally_id="r1")
        sm.feed(_make_event(VisionEventType.RALLY_STARTED, ts=1000.0))
        assert sm.context.state == RallyState.ACTIVE

    def test_bounce_increments_point_count(self):
        sm = RallyStateMachine(rally_id="r1")
        sm.feed(_make_event(VisionEventType.RALLY_STARTED, ts=1000.0))
        sm.feed(_make_event(VisionEventType.BOUNCE, ts=1001.0))
        assert sm.context.point_count == 1

    def test_rally_ended_sets_end_state(self):
        sm = RallyStateMachine(rally_id="r1")
        sm.feed(_make_event(VisionEventType.RALLY_STARTED, ts=1000.0))
        sm.feed(_make_event(VisionEventType.RALLY_ENDED, ts=1002.0))
        assert sm.context.state == RallyState.ENDED

    def test_new_rally_started_after_ended_resets(self):
        sm = RallyStateMachine(rally_id="r1")
        sm.feed(_make_event(VisionEventType.RALLY_STARTED, ts=1000.0))
        sm.feed(_make_event(VisionEventType.RALLY_ENDED, ts=1002.0))
        sm.feed(_make_event(VisionEventType.RALLY_STARTED, ts=1003.0))
        assert sm.context.state == RallyState.ACTIVE
        assert sm.context.point_count == 0
