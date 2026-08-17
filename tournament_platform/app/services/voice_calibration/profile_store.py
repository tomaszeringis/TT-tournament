"""
Phase 12 — Calibration profile persistence adapters.

Provides a session-only in-memory store for contract tests and a
storage abstraction for future browser-local or database persistence.
"""

from __future__ import annotations

from typing import Optional

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationProfileIdentity,
    CalibrationProfileStore,
    VoiceCalibrationProfile,
)


class InMemoryCalibrationProfileStore(CalibrationProfileStore):
    """Session-only in-memory profile store for testing."""

    def __init__(self) -> None:
        self._profiles: dict[str, VoiceCalibrationProfile] = {}

    def load(self, owner_id: str, identity: CalibrationProfileIdentity) -> Optional[VoiceCalibrationProfile]:
        for profile in self._profiles.values():
            if profile.owner_id == owner_id and profile.identity == identity:
                return profile
        return None

    def save(self, owner_id: str, profile: VoiceCalibrationProfile) -> None:
        if profile.owner_id != owner_id:
            raise ValueError("owner_id mismatch")
        self._profiles[profile.profile_id] = profile

    def delete(self, owner_id: str, profile_id: str) -> None:
        profile = self._profiles.get(profile_id)
        if profile is not None and profile.owner_id != owner_id:
            raise ValueError("owner_id mismatch")
        self._profiles.pop(profile_id, None)

    def clear(self) -> None:
        self._profiles.clear()
