"""
Built-in voice profiles for the commentary voice system.
"""

from __future__ import annotations

from tournament_platform.app.services.commentary_voice.voice_profile import VoiceProfile
from tournament_platform.app.services.commentary_voice.piper_voice import get_piper_engine
from tournament_platform.app.services.commentary_voice.piper_runtime import find_piper_voices, PiperVoice


BUILTIN_PROFILES: list[VoiceProfile] = [
    VoiceProfile(
        id="browser_default",
        label="Browser default",
        engine="browser",
        language="en",
        voice_name="default",
        style="neutral",
        rate=1.0,
        pitch=1.0,
        volume=1.0,
        description="Default browser voice with neutral style.",
    ),
    VoiceProfile(
        id="browser_male",
        label="Male commentator",
        engine="browser",
        language="en",
        voice_name="male-sounding",
        gender_label="male",
        style="announcer",
        rate=0.95,
        pitch=0.95,
        volume=1.0,
        description="Male-style commentator voice with announcer delivery.",
    ),
    VoiceProfile(
        id="browser_female",
        label="Female commentator",
        engine="browser",
        language="en",
        voice_name="female-sounding",
        gender_label="female",
        style="announcer",
        rate=1.0,
        pitch=1.05,
        volume=1.0,
        description="Female-style commentator voice with announcer delivery.",
    ),
    VoiceProfile(
        id="sport_commentator",
        label="Sport commentator",
        engine="browser",
        language="en",
        voice_name="announcer",
        style="announcer",
        rate=1.08,
        pitch=0.95,
        volume=1.0,
        description="Energetic sport commentator with higher rate and lower pitch.",
    ),
    VoiceProfile(
        id="coach",
        label="Coach",
        engine="browser",
        language="en",
        voice_name="coach",
        style="coach",
        rate=1.0,
        pitch=1.0,
        volume=1.0,
        description="Instructional coach-style commentary.",
    ),
    VoiceProfile(
        id="umpire",
        label="Umpire",
        engine="browser",
        language="en",
        voice_name="default",
        style="neutral",
        rate=1.0,
        pitch=1.0,
        volume=1.0,
        description="Neutral umpire-style commentary.",
    ),
    VoiceProfile(
        id="lt_browser_default",
        label="Lithuanian default",
        engine="browser",
        language="lt",
        voice_name="default",
        style="neutral",
        rate=1.0,
        pitch=1.0,
        volume=1.0,
        description="Default browser voice for Lithuanian commentary.",
    ),
    VoiceProfile(
        id="en_browser_default",
        label="English default",
        engine="browser",
        language="en",
        voice_name="default",
        style="neutral",
        rate=1.0,
        pitch=1.0,
        volume=1.0,
        description="Default browser voice for English commentary.",
    ),
]

_PROFILE_MAP: dict[str, VoiceProfile] = {p.id: p for p in BUILTIN_PROFILES}


def get_profile(profile_id: str) -> VoiceProfile | None:
    return _PROFILE_MAP.get(profile_id)


def list_profiles() -> list[VoiceProfile]:
    return list(BUILTIN_PROFILES)


def list_local_piper_voices() -> list[VoiceProfile]:
    profiles: list[VoiceProfile] = []
    for voice in find_piper_voices():
        profile = VoiceProfile(
            id=voice.id,
            label=voice.label,
            engine="piper",
            language=voice.language or "en",
            voice_id=voice.id,
            voice_name=voice.label,
            style="neutral",
            rate=1.0,
            pitch=1.0,
            volume=1.0,
            is_local=True,
            requires_network=False,
            description=f"Local Piper voice: {voice.label}",
        )
        profiles.append(profile)
        _PROFILE_MAP[profile.id] = profile
    return profiles


def get_all_profiles() -> list[VoiceProfile]:
    profiles = list(BUILTIN_PROFILES)
    profiles.extend(list_local_piper_voices())
    return profiles


def profile_choices() -> list[tuple[str, str]]:
    return [(p.id, p.label) for p in get_all_profiles()]
