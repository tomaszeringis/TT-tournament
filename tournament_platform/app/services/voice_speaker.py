"""
Voice Speaker Identification (Phase 2)

Provides manual and (future) enrollment-based speaker tagging for voice events.
Speaker ID is additive and never blocks normal scoring unless VOICE_SPEAKER_REQUIRE
is explicitly configured.

Modes:
- "manual": user selects speaker from a dropdown in the UI.
- "enrollment": placeholder for future voice-embedding enrollment.
- "off": no speaker tagging; speaker_label stays None.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default speaker roles for table tennis scoring contexts.
DEFAULT_SPEAKERS = ["Referee", "Player A", "Player B", "Umpire"]


@dataclass
class SpeakerProfile:
    """A speaker identity for enrollment-based identification (future use)."""
    label: str
    enrolled_at: float = field(default_factory=time.time)
    embedding: Optional[bytes] = None  # placeholder for future voice embedding


class SpeakerTagger:
    """
    Attaches speaker labels to voice events.

    In manual mode, the UI supplies the current speaker label. In enrollment mode,
    a future embedding-based classifier would infer the speaker. In off mode, no
    label is attached.
    """

    def __init__(
        self,
        mode: str = "manual",
        allowed_speakers: Optional[List[str]] = None,
        require_speaker: bool = False,
    ):
        self.mode = mode
        self.allowed_speakers = allowed_speakers or list(DEFAULT_SPEAKERS)
        self.require_speaker = require_speaker
        self._current_label: Optional[str] = None
        self._profiles: dict[str, SpeakerProfile] = {}

    def set_current_speaker(self, label: Optional[str]) -> None:
        """Set the active speaker label (used in manual mode)."""
        if self.mode == "off":
            self._current_label = None
            return
        if label is None or label == "":
            self._current_label = None
        elif label in self.allowed_speakers:
            self._current_label = label
        else:
            logger.warning("Speaker label %r not in allowed list; ignoring.", label)

    def get_current_speaker(self) -> Optional[str]:
        """Return the currently active speaker label."""
        return self._current_label

    def is_allowed(self, label: Optional[str]) -> bool:
        """Check whether a speaker label is in the allowed list."""
        if not self.require_speaker:
            return True
        if not label:
            return False
        return label in self.allowed_speakers

    def attach_label(self, event) -> None:
        """
        Attach the current speaker label to a voice event (in-place).

        The event must have a `speaker_label` attribute. If the tagger is in off
        mode or no speaker is selected, the attribute is set to None.
        """
        if self.mode == "off" or self._current_label is None:
            event.speaker_label = None
        else:
            event.speaker_label = self._current_label

    def enroll(self, label: str, embedding: Optional[bytes] = None) -> SpeakerProfile:
        """
        Register a speaker profile for future enrollment-based identification.

        Args:
            label: Speaker name (must be in allowed_speakers).
            embedding: Optional voice embedding bytes (placeholder for future use).

        Returns:
            The created SpeakerProfile.
        """
        if label not in self.allowed_speakers:
            raise ValueError(f"Speaker {label!r} is not in the allowed list.")
        profile = SpeakerProfile(label=label, embedding=embedding)
        self._profiles[label] = profile
        return profile

    def list_profiles(self) -> List[SpeakerProfile]:
        """Return all enrolled speaker profiles."""
        return list(self._profiles.values())
