"""
Tests for Operator Console lane partitioning (Phase 3).

Verifies the queue is split into the correct lanes without overlap.
"""

from tournament_platform.app.pages.operator_console import _partition_queue


def _match(mid, call_status, status="pending"):
    return {"id": mid, "call_status": call_status, "status": status}


class TestOperatorLanes:
    def test_partition_now_playing(self):
        queue = [
            _match(1, "active"),
            _match(2, "called"),
            _match(3, "not_called"),
            _match(4, "delayed"),
            _match(5, "completed", status="completed"),
        ]
        parts = _partition_queue(queue)
        assert {m["id"] for m in parts["now_playing"]} == {1, 2}
        assert {m["id"] for m in parts["up_next"]} == {3}
        assert {m["id"] for m in parts["delayed"]} == {4}
        assert {m["id"] for m in parts["completed"]} == {5}

    def test_partition_no_overlap(self):
        queue = [
            _match(1, "active"),
            _match(2, "not_called"),
            _match(3, "completed", status="completed"),
        ]
        parts = _partition_queue(queue)
        all_ids = (
            {m["id"] for m in parts["now_playing"]}
            | {m["id"] for m in parts["up_next"]}
            | {m["id"] for m in parts["delayed"]}
            | {m["id"] for m in parts["completed"]}
        )
        assert all_ids == {1, 2, 3}
        assert len(all_ids) == 3

    def test_empty_queue(self):
        parts = _partition_queue([])
        assert parts["now_playing"] == []
        assert parts["up_next"] == []
        assert parts["completed"] == []
