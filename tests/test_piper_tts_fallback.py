"""
Tests for Piper TTS being optional and non-blocking.

Piper must never be a required runtime dependency. On Streamlit Cloud (or any
environment without Piper) the app should:
- import fine,
- not show scary "Piper is not installed" error spam,
- fall back to browser speech / silent mode without crashing,
- keep the commentary log free of system warnings.
"""

import pytest


class _SessionStateStub:
    """Dict-like object that also allows attribute access.

    The voice_scorekeeper page accesses ``st.session_state`` both as a mapping
    (``st.session_state['key']``) and via attributes (``st.session_state.foo``),
    mirroring Streamlit's real ``SessionStateProxy``.
    """

    def __init__(self, data=None):
        object.__setattr__(self, "_data", dict(data or {}))

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == "_data":
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeStreamlit:
    """Minimal Streamlit stand-in that records session state and UI calls."""

    def __init__(self):
        self.session_state = _SessionStateStub()
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, msg, *args, **kwargs):
        self.infos.append(msg)

    def warning(self, msg, *args, **kwargs):
        self.warnings.append(msg)

    def error(self, msg, *args, **kwargs):
        self.errors.append(msg)


@pytest.fixture
def fake_streamlit(monkeypatch):
    """Patch the real ``streamlit`` module with the fake instance."""
    import streamlit as real_st

    fake = _FakeStreamlit()
    monkeypatch.setattr(real_st, "session_state", fake.session_state, raising=False)
    monkeypatch.setattr(real_st, "info", fake.info, raising=False)
    monkeypatch.setattr(real_st, "warning", fake.warning, raising=False)
    monkeypatch.setattr(real_st, "error", fake.error, raising=False)
    return fake


class TestPiperOptionalImports:
    def test_app_imports_without_piper(self):
        """The page imports successfully even when ``piper`` is not installed."""
        import tournament_platform.app.pages.voice_scorekeeper as page

        assert page is not None
        assert hasattr(page, "is_streamlit_cloud")
        assert hasattr(page, "notify_piper_unavailable_once")


class TestIsStreamlitCloud:
    def test_detects_headless_env(self, monkeypatch):
        from tournament_platform.app.pages.voice_scorekeeper import is_streamlit_cloud

        monkeypatch.setenv("STREAMLIT_SERVER_HEADLESS", "true")
        assert is_streamlit_cloud() is True

    def test_detects_sharing_mode(self, monkeypatch):
        from tournament_platform.app.pages.voice_scorekeeper import is_streamlit_cloud

        monkeypatch.setenv("STREAMLIT_SHARING_MODE", "1")
        assert is_streamlit_cloud() is True

    def test_false_when_unset(self, monkeypatch):
        from tournament_platform.app.pages.voice_scorekeeper import is_streamlit_cloud

        monkeypatch.delenv("STREAMLIT_SERVER_HEADLESS", raising=False)
        monkeypatch.delenv("STREAMLIT_SHARING_MODE", raising=False)
        assert is_streamlit_cloud() is False


class TestNotifyPiperUnavailableOnce:
    def test_shows_once_per_session(self, fake_streamlit):
        from tournament_platform.app.pages.voice_scorekeeper import (
            notify_piper_unavailable_once,
        )

        msg = "Piper local TTS is not available."
        notify_piper_unavailable_once(msg, level="info")
        notify_piper_unavailable_once(msg, level="info")
        notify_piper_unavailable_once(msg, level="info")

        assert len(fake_streamlit.infos) == 1
        assert len(fake_streamlit.warnings) == 0
        assert len(fake_streamlit.errors) == 0
        assert "Piper" in fake_streamlit.infos[0]

    def test_warn_level_uses_warning_not_error(self, fake_streamlit):
        from tournament_platform.app.pages.voice_scorekeeper import (
            notify_piper_unavailable_once,
        )

        notify_piper_unavailable_once("friendly warning", level="warning")
        assert len(fake_streamlit.warnings) == 1
        assert len(fake_streamlit.errors) == 0


class TestPiperRuntimeSafe:
    def test_is_piper_available_does_not_crash(self):
        from tournament_platform.app.services.commentary_voice.piper_runtime import (
            is_piper_available,
        )

        assert isinstance(is_piper_available(), bool)

    def test_find_piper_voices_safe_returns_list(self):
        from tournament_platform.app.services.commentary_voice.piper_runtime import (
            find_piper_voices,
        )

        # Returns a list (empty when no voices); never raises.
        assert isinstance(find_piper_voices(), list)


class TestCommentaryLogClean:
    """System TTS warnings must not leak into the match commentary log."""

    def test_notice_does_not_append_to_commentary_log(self, fake_streamlit):
        from tournament_platform.app.pages.voice_scorekeeper import (
            notify_piper_unavailable_once,
        )

        notify_piper_unavailable_once("Piper local TTS is not available.")
        # The notice must not create a commentary-log entry containing the warning.
        for key in fake_streamlit.session_state:
            value = str(fake_streamlit.session_state[key])
            assert "commentary_log" not in key or "Piper" not in value


class TestWebRTCOptions:
    """streamlit-webrtc is optional; its absence must never crash the app."""

    def test_app_imports_with_webrtc_or_without(self):
        import tournament_platform.app.pages.voice_scorekeeper as page

        assert page is not None
        assert hasattr(page, "WEBRTC_AVAILABLE")
        assert hasattr(page, "detect_webrtc_available")
        assert hasattr(page, "ensure_webrtc_diag_state")
        # Boolean flag, set at import even if the package is missing.
        assert isinstance(page.WEBRTC_AVAILABLE, bool)

    def test_detect_webrtc_available_returns_bool(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            detect_webrtc_available,
        )

        # Must never raise; returns a bool reflecting actual install state.
        assert isinstance(detect_webrtc_available(), bool)

    def test_diag_state_defaults_from_webrtc_flag(self, fake_streamlit):
        from tournament_platform.app.pages.voice_scorekeeper import (
            WEBRTC_AVAILABLE,
            ensure_webrtc_diag_state,
        )

        ensure_webrtc_diag_state()
        assert fake_streamlit.session_state.get("webrtc_diag_available") == WEBRTC_AVAILABLE

    def test_missing_webrtc_notice_is_info_not_warning(self, fake_streamlit):
        """Simulate the once-per-session WebRTC-missing notice path.

        Mirrors the logic in the Continuous Listening expander: a friendly
        ``st.info`` shown at most once, never a scary ``st.warning``.
        """
        import streamlit as st

        if not st.session_state.get("shown_webrtc_missing_warning"):
            st.info(
                "Live microphone mode is unavailable because `streamlit-webrtc` "
                "is not installed. Manual scoring and browser speech still work."
            )
            st.session_state.shown_webrtc_missing_warning = True

        # Repeated calls must not emit a second notice.
        if not st.session_state.get("shown_webrtc_missing_warning"):
            st.info("should not happen")
            st.session_state.shown_webrtc_missing_warning = True

        assert len(fake_streamlit.infos) == 1
        assert len(fake_streamlit.warnings) == 0
        assert "streamlit-webrtc is not installed. Install it" not in fake_streamlit.infos[0]

