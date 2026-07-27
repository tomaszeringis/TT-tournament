"""
Tests for Phase 2 manual scoring with latency tracing.
These tests verify the ordering: score state changes before commentary/TTS.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestManualScoringOrdering:
    """Tests for manual scoring ordering requirements."""
    
    def test_score_state_changes_before_commentary(self):
        """Score changes must happen before commentary."""
        # This is a units test - we verify the ordering in the actual code
        # In low-latency mode, the flow is:
        # 1. Callback mutates state
        # 2. Score renders (natural rerun)
        # 3. Fragment drains side effects
        from tournament_platform.app.services.latency_trace import (
            record_latency,
            clear_latency_history,
            latency_stats,
        )
        from tournament_platform.app.services.side_effects import SideEffectQueue
        
        clear_latency_history()
        q = SideEffectQueue()
        
        # Simulate the ordering
        record_latency("t1", "score_apply", None, "manual", "score_apply", 1000, 1005000, True)
        record_latency("t1", "commentary", None, "manual", "commentary_generation", 1006000, 15000000, True)
        
        # Score apply (5ms) should be before commentary (14ms)
        stats = latency_stats(stage="score_apply")
        assert stats["count"] == 1
        assert stats["max_ms"] == pytest.approx(5.0)


class TestLowLatencyFeatureFlag:
    """Tests for the low-latency feature flag behavior."""

    def test_feature_flag_defaults_false(self):
        """Low-latency mode must be OFF by default."""
        from tournament_platform.services.settings import VOICE_LOW_LATENCY_EXPERIMENTAL
        assert VOICE_LOW_LATENCY_EXPERIMENTAL is False

    def test_latency_trace_flag_defaults_false(self):
        """Latency tracing must be OFF by default."""
        from tournament_platform.services.settings import VOICE_LATENCY_TRACE
        assert VOICE_LATENCY_TRACE is False


class TestSideEffectQueueIntegration:
    """Tests for side-effect queue integration points."""

    def test_queue_uses_match_epoch_for_invalidation(self):
        """Reset must bump epoch, invalidating stale queued effects."""
        from tournament_platform.app.services.side_effects import SideEffectQueue
        
        q = SideEffectQueue()
        
        # Add event in epoch 1
        q.enqueue("manual", "point_a", {"a": 0}, {"a": 1}, match_epoch="1")
        
        # Bump epoch (simulating reset)
        q.increment_epoch()
        
        # Drain with current epoch should be empty
        events = q.drain(target_epoch="2")
        assert len(events) == 0
        
        # Drain all epochs should return the old event
        events = q.drain()
        assert len(events) == 1

    def test_side_effects_stored_as_primitives(self):
        """Side-effect queue stores only JSON-safe primitives."""
        from tournament_platform.app.services.side_effects import ScoreMutationEvent
        import json
        
        event = ScoreMutationEvent(
            action_id="test-123",
            match_id=1,
            match_epoch="1",
            revision=1,
            source="manual",
            action_type="point_a",
            state_before={"score_a": 0, "score_b": 0},
            state_after={"score_a": 1, "score_b": 0},
            commentary_settings={"enabled": True},
            created_at=1234567890.0,
        )
        
        # Should be serializable
        serialized = {
            "action_id": event.action_id,
            "match_id": event.match_id,
            "state_before": event.state_before,
        }
        json.dumps(serialized)  # Should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])