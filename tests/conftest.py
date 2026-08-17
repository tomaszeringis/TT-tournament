"""Shared test isolation for voice-runtime state."""

from __future__ import annotations

import time
from typing import Any

import pytest

from tournament_platform.app.services.voice_scorekeeper.event_drain import (
    clear_calibration_processed_ids,
    clear_processed_voice_event_ids,
    reset_drain_diagnostics,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    reset_voice_runtime_state,
)


def _is_voice_calibration_test(item: pytest.Function) -> bool:
    """Return True if the test item belongs to voice-calibration/event-drain."""
    nodeid = item.nodeid
    return (
        "voice_calibration" in nodeid
        or "test_calibration_blocker_regression" in nodeid
        or "test_continuous_voice_drain" in nodeid
    )


@pytest.fixture(autouse=True)
def _reset_voice_runtime_state(request: pytest.FixtureRequest) -> Any:
    """Reset mutable voice-runtime state before and after relevant tests."""
    if not _is_voice_calibration_test(request.node):
        yield
        return

    clear_processed_voice_event_ids()
    clear_calibration_processed_ids()
    reset_drain_diagnostics()
    reset_voice_runtime_state()

    yield

    clear_processed_voice_event_ids()
    clear_calibration_processed_ids()
    reset_drain_diagnostics()
    reset_voice_runtime_state()
