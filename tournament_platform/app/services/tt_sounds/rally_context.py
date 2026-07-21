"""Rally context manager for TT Sounds.

Tracks the current in-progress rally and completed summaries.
"""

from __future__ import annotations

from typing import List, Optional

from .schemas import AudioRallySummary, RallyContext, TTAudioEvent


class RallyManager:
    def __init__(self, rally_gap_threshold: float = 2.0, max_events: int = 500) -> None:
        self._current: Optional[RallyContext] = None
        self._summaries: List[AudioRallySummary] = []
        self._rally_gap_threshold = rally_gap_threshold
        self._max_events = max_events

    def add_event(self, event: TTAudioEvent) -> Optional[AudioRallySummary]:
        if self._current is None or not self._current.is_active:
            self._current = RallyContext(rally_start_ts=event.timestamp, impacts=[event])
            return None

        impacts = self._current.impacts
        if impacts and event.timestamp - impacts[-1].timestamp > self._rally_gap_threshold:
            summary = self._finalize_locked(last_action="gap")
            self._current = RallyContext(rally_start_ts=event.timestamp, impacts=[event])
            return summary

        impacts.append(event)
        if len(impacts) > self._max_events:
            impacts[:] = impacts[-self._max_events :]
        return None

    def finalize_current_rally(self, last_action: str = "gap") -> Optional[AudioRallySummary]:
        if self._current is None or not self._current.is_active:
            return None
        return self._finalize_locked(last_action=last_action)

    def current_context(self) -> Optional[RallyContext]:
        return self._current

    def summaries(self) -> List[AudioRallySummary]:
        return list(self._summaries)

    def _finalize_locked(self, last_action: str) -> Optional[AudioRallySummary]:
        if self._current is None or not self._current.impacts:
            return None

        impacts = self._current.impacts
        start_ts = self._current.rally_start_ts
        end_ts = impacts[-1].timestamp
        count = len(impacts)

        intervals = [
            impacts[i + 1].timestamp - impacts[i].timestamp for i in range(len(impacts) - 1)
        ]
        avg_interval = sum(intervals) / len(intervals) if intervals else 0.0
        strongest = max(e.energy for e in impacts) if impacts else 0.0
        conf = sum(e.confidence for e in impacts) / count if count else 0.0

        summary = AudioRallySummary(
            rally_id=f"rally_{int(start_ts * 1000)}",
            start_ts=start_ts,
            end_ts=end_ts,
            impact_count=count,
            avg_interval_ms=avg_interval * 1000.0,
            strongest_impact_energy=strongest,
            confidence=conf,
            last_action=last_action,
        )
        self._summaries.append(summary)
        self._current = None
        return summary
