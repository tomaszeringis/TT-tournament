"""
Commentary voice system — voice profiles, catalog, settings, browser integration, and local Piper TTS.
"""

from tournament_platform.app.services.commentary_voice.voice_profile import VoiceProfile
from tournament_platform.app.services.commentary_voice.voice_catalog import (
    BUILTIN_PROFILES,
    get_profile,
    list_profiles,
    list_local_piper_voices,
    get_all_profiles,
    profile_choices,
)
from tournament_platform.app.services.commentary_voice.voice_settings import (
    VoiceSettings,
    get_voice_settings,
    init_voice_session_state,
)
from tournament_platform.app.services.commentary_voice.browser_voice import (
    build_voice_picker_html,
)
from tournament_platform.app.services.commentary_voice.piper_voice import (
    PiperTTSEngine,
    get_piper_engine,
    PiperTTSError,
    AudioResult,
)
from tournament_platform.app.services.commentary_voice.piper_runtime import (
    is_piper_available,
    find_piper_voices,
    PiperVoice,
    get_piper_binary,
)

__all__ = [
    "VoiceProfile",
    "BUILTIN_PROFILES",
    "get_profile",
    "list_profiles",
    "list_local_piper_voices",
    "get_all_profiles",
    "profile_choices",
    "VoiceSettings",
    "get_voice_settings",
    "init_voice_session_state",
    "build_voice_picker_html",
    "PiperTTSEngine",
    "get_piper_engine",
    "PiperTTSError",
    "AudioResult",
    "is_piper_available",
    "find_piper_voices",
    "PiperVoice",
    "get_piper_binary",
]
