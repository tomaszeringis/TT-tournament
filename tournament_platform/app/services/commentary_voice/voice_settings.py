"""
Voice settings dataclass and session state helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from tournament_platform.app.services.commentary_voice.voice_catalog import get_profile


@dataclass
class VoiceSettings:
    profile_id: str = "browser_default"
    rate: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    browser_voice_name: str | None = None

    @property
    def profile(self):
        return get_profile(self.profile_id)

    def effective_style(self) -> str:
        if self.profile and self.profile.style:
            return self.profile.style
        return "neutral"

    def effective_language(self) -> str:
        if self.profile and self.profile.language:
            return self.profile.language
        return "en"

    def effective_rate(self) -> float:
        return self.rate

    def effective_pitch(self) -> float:
        return self.pitch

    def effective_volume(self) -> float:
        return self.volume


def init_voice_session_state() -> None:
    import streamlit as st

    if "commentary_voice_profile" not in st.session_state:
        st.session_state.commentary_voice_profile = "browser_default"
    if "commentary_rate" not in st.session_state:
        st.session_state.commentary_rate = 1.0
    if "commentary_pitch" not in st.session_state:
        st.session_state.commentary_pitch = 1.0
    if "commentary_volume" not in st.session_state:
        st.session_state.commentary_volume = 1.0
    if "commentary_browser_voice_name" not in st.session_state:
        st.session_state.commentary_browser_voice_name = None


def get_voice_settings() -> VoiceSettings:
    import streamlit as st

    init_voice_session_state()
    return VoiceSettings(
        profile_id=st.session_state.get("commentary_voice_profile", "browser_default"),
        rate=float(st.session_state.get("commentary_rate", 1.0)),
        pitch=float(st.session_state.get("commentary_pitch", 1.0)),
        volume=float(st.session_state.get("commentary_volume", 1.0)),
        browser_voice_name=st.session_state.get("commentary_browser_voice_name"),
    )
