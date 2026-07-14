"""
Voice profile data model for the commentary voice system.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    label: str
    engine: str = "browser"
    language: str = "en"
    voice_id: str | None = None
    voice_name: str | None = None
    gender_label: str | None = None
    style: str = "neutral"
    rate: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    is_local: bool = False
    requires_network: bool = False
    description: str = ""
