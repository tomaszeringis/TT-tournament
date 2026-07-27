"""Tests for Phase 2 side-effect queue."""

import pytest
from tournament_platform.app.services.side_effects import ScoreMutationEvent, SideEffectQueue


class TestScoreMutationEventDataclass:
    def test_event_is_immutable(self):
        """ScoreMutationEvent must be frozen/immutable."""
        event = ScoreMutationEvent(
            action_id="test-id",
            match_id=1,
            match_epoch="1",
            revision=1,
            source="manual",
            action_type="point_a",
            state_before={"score_a": 0, "score_b": 0},
            state_after={"score_a": 1, "score_b": 0},
            commentary_settings={},
            created_at=0.0,
        )
        # Dataclass should be frozen - cannot modify fields
        with pytest.raises(Exception):  # FrozenInstanceError
            event.success = False

    def test_event_fields(self):
        """All fields should be accessible."""
        event = ScoreMutationEvent(
            action_id="action-123",
            match_id=42,
            match_epoch="3",
            revision=5,
            source="voice",
            action_type="point",
            state_before={"a": 1},
            state_after={"a": 2},
            commentary_settings={"enabled": True},
            created_at=123.45,
        )
        assert event.action_id == "action-123"
        assert event.match_id == 42
        assert event.match_epoch == "3"
        assert event.revision == 5
        assert event.source == "voice"
        assert event.action_type == "point"


class TestSideEffectQueue:
    def test_enqueue_adds_events(self):
        q = SideEffectQueue()
        action_id = q.enqueue(
            source="manual",
            action_type="point_a",
            state_before={"score": "0-0"},
            state_after={"score": "1-0"},
        )
        assert action_id is not None
        assert len(action_id) > 0
        assert q.size == 1

    def test_drain_returns_events(self):
        q = SideEffectQueue()
        q.enqueue("manual", "point_a", {"a": 0}, {"a": 1}, match_id=1, match_epoch="1", revision=1)
        events = q.drain()
        assert len(events) == 1
        assert events[0].source == "manual"
        assert q.size == 0

    def test_drain_filters_by_epoch(self):
        q = SideEffectQueue()
        q._epoch = "1"
        q.enqueue("manual", "point_a", {"a": 0}, {"a": 1}, match_epoch="1")
        q.enqueue("manual", "point_b", {"b": 0}, {"b": 1}, match_epoch="2")
        events = q.drain(target_epoch="1")
        assert len(events) == 1
        assert events[0].action_type == "point_a"

    def test_clear_removes_all_events(self):
        q = SideEffectQueue()
        q.enqueue("manual", "point_a", {"a": 0}, {"a": 1})
        q.enqueue("manual", "point_b", {"b": 0}, {"b": 1})
        q.clear()
        assert q.size == 0

    def test_queue_is_bounded(self):
        q = SideEffectQueue(maxlen=5)
        for i in range(10):
            q.enqueue("manual", f"point_{i}", {}, {})
        assert q.size <= 5

    def test_increment_epoch(self):
        q = SideEffectQueue()
        assert q._epoch == "1"
        q.increment_epoch()
        assert q._epoch == "2"
        q.increment_epoch()
        assert q._epoch == "3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])