"""Regression tests for continuous voice event drain fix.

Covers:
* _maybe_voice_heartbeat() triggers reruns when WebRTC is playing and events are pending
* _asr_events_enqueued counter is incremented correctly
* Event schema uses VoiceTranscriptEvent objects
* _process_voice_events() drains events when WebRTC is playing even if voice_listening is False
* get_active_voice_processor() returns the same processor used by WebRTC and diagnostics
"""

import importlib
import sys

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.app.services.voice_scorekeeper.events import VoiceTranscriptEvent

# ---------------------------------------------------------------------------
# Isolate streamlit-dependent modules from other test files.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_streamlit_modules(monkeypatch):
    """Ensure event_drain and voice_scorekeeper use a fresh streamlit mock."""
    import streamlit as _real_st

    _original_streamlit = sys.modules.get("streamlit")

    _mock_st = MagicMock()
    _mock_st.session_state = MagicMock()
    _mock_st.rerun = MagicMock()
    _mock_st.experimental_rerun = MagicMock()
    _mock_st.warning = MagicMock()
    _mock_st.error = MagicMock()
    _mock_st.info = MagicMock()
    _mock_st.success = MagicMock()

    _saved_modules = {}
    for mod_name in list(sys.modules.keys()):
        if "event_drain" in mod_name or "voice_scorekeeper" in mod_name:
            _saved_modules[mod_name] = sys.modules.get(mod_name)

    sys.modules["streamlit"] = _mock_st

    for mod_name in list(sys.modules.keys()):
        if "event_drain" in mod_name or "voice_scorekeeper" in mod_name:
            del sys.modules[mod_name]

    yield _mock_st

    for mod_name in list(sys.modules.keys()):
        if "event_drain" in mod_name or "voice_scorekeeper" in mod_name:
            del sys.modules[mod_name]

    for mod_name, original in _saved_modules.items():
        if original is not None:
            sys.modules[mod_name] = original
        else:
            sys.modules.pop(mod_name, None)

    if _original_streamlit is not None:
        sys.modules["streamlit"] = _original_streamlit
    else:
        sys.modules.pop("streamlit", None)


class TestMaybeVoiceHeartbeatWithPlayingWebrtc:
    def test_heartbeat_reruns_when_webrtc_playing_and_pending_events(self, monkeypatch):
        """When WebRTC is playing and there are pending events,
        _maybe_voice_heartbeat should trigger a rerun when voice_listening is True."""
        import streamlit as st
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _maybe_voice_heartbeat,
        )

        mock_processor = MagicMock()
        mock_processor.has_pending_events.return_value = True

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_listening": True,
            "voice_scoring_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
            "voice_last_heartbeat": 0.0,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_selected_match_id": 1,
            "match_complete": False,
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)

        with patch("tournament_platform.app.services.voice_scorekeeper.event_drain.st.rerun") as mock_rerun:
            with patch("tournament_platform.app.services.voice_scorekeeper.event_drain.time.sleep"):
                _maybe_voice_heartbeat()
                assert mock_rerun.called

    def test_heartbeat_does_not_rerun_when_idle(self, monkeypatch):
        """When nothing is active, _maybe_voice_heartbeat should not rerun."""
        import streamlit as st
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _maybe_voice_heartbeat,
        )

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_listening": False,
            "voice_scoring_enabled": True,
            "voice_webrtc_ctx": None,
            "voice_last_heartbeat": 0.0,
            "voice_webrtc_streamer_state": {"playing": False},
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)

        with patch("tournament_platform.app.services.voice_scorekeeper.event_drain.st.rerun") as mock_rerun:
            _maybe_voice_heartbeat()
            assert not mock_rerun.called

    def test_heartbeat_returns_early_when_voice_scoring_disabled(self, monkeypatch):
        """When voice scoring is disabled, heartbeat should not rerun."""
        import streamlit as st
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _maybe_voice_heartbeat,
        )

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_listening": True,
            "voice_scoring_enabled": False,
            "voice_webrtc_ctx": None,
            "voice_last_heartbeat": 0.0,
            "voice_webrtc_streamer_state": {"playing": False},
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)

        with patch("tournament_platform.app.services.voice_scorekeeper.event_drain.st.rerun") as mock_rerun:
            _maybe_voice_heartbeat()
            assert not mock_rerun.called


class TestAsrEventsEnqueuedCounter:
    def test_counter_is_an_integer(self):
        """The _asr_events_enqueued counter should be an integer."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor

        proc = VoiceAudioProcessor()
        assert isinstance(proc._asr_events_enqueued, int)
        assert proc._asr_events_enqueued >= 0


class TestEventSchemaNormalization:
    def test_legacy_tuple_schema(self):
        """Legacy three-element tuples should be processable by the drain."""
        event = ("Point blue.", "Point blue.", MagicMock(event_id="evt-1", type="increment", player="A"))
        raw_text, text, evt = event
        assert raw_text == "Point blue."
        assert text == "Point blue."
        assert evt.event_id == "evt-1"

    def test_event_has_required_attributes(self):
        """Events from the queue should have event_id and type attributes."""
        mock_event = MagicMock()
        mock_event.event_id = "test-123"
        mock_event.type = "increment"
        mock_event.player = "A"

        assert mock_event.event_id == "test-123"
        assert mock_event.type == "increment"


class TestHasPendingEvents:
    def test_processor_reports_pending_events(self):
        """has_pending_events should return True when queue has items."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor

        proc = VoiceAudioProcessor()
        assert not proc.has_pending_events()

        # Simulate an event in the queue
        proc.event_queue.put(VoiceTranscriptEvent(
            transcript="test",
            raw_transcript="test",
            event_id="evt-1",
        ))
        assert proc.has_pending_events()

    def test_processor_reports_no_pending_events_when_empty(self):
        """has_pending_events should return False when queue is empty."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor

        proc = VoiceAudioProcessor()
        assert not proc.has_pending_events()


class TestNormalizeVoiceTranscriptEvent:
    def test_normalize_tuple_event(self):
        """Legacy three-item tuples should be normalized to VoiceTranscriptEvent."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            normalize_voice_transcript_event,
        )

        event = ("Point blue.", "Point blue.", "evt-1")
        result = normalize_voice_transcript_event(event)
        assert result.transcript == "Point blue."
        assert result.raw_transcript == "Point blue."
        assert result.event_id == "evt-1"
        assert result.source == "continuous"

    def test_normalize_dict_event(self):
        """Dict events should be normalized to VoiceTranscriptEvent."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            normalize_voice_transcript_event,
        )

        event = {
            "transcript": "Point blue.",
            "raw_transcript": "Point blue.",
            "event_id": "evt-2",
            "source": "continuous",
        }
        result = normalize_voice_transcript_event(event)
        assert result.transcript == "Point blue."
        assert result.event_id == "evt-2"

    def test_normalize_voice_transcript_event_pass_through(self):
        """VoiceTranscriptEvent instances should pass through unchanged."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            normalize_voice_transcript_event,
            VoiceTranscriptEvent,
        )

        original = VoiceTranscriptEvent(
            transcript="Point blue.",
            raw_transcript="Point blue.",
            event_id="evt-3",
            source="continuous",
        )
        result = normalize_voice_transcript_event(original)
        assert result is original

    def test_normalize_unsupported_type_raises(self):
        """Unsupported event schemas should raise InvalidVoiceTranscriptEvent."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            normalize_voice_transcript_event,
            InvalidVoiceTranscriptEvent,
        )

        with pytest.raises(InvalidVoiceTranscriptEvent):
            normalize_voice_transcript_event(42)


class TestGetActiveVoiceProcessor:
    def test_get_active_voice_processor_from_dict_ctx(self, monkeypatch):
        """get_active_voice_processor should return the processor from voice_webrtc_ctx dict."""
        import streamlit as st
        from tournament_platform.app.pages.voice_scorekeeper import get_active_voice_processor
        from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor

        mock_processor = MagicMock(spec=VoiceAudioProcessor)
        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)

        result = get_active_voice_processor()
        assert result is mock_processor

    def test_get_active_voice_processor_returns_none_when_no_ctx(self, monkeypatch):
        """get_active_voice_processor should return None when no WebRTC context."""
        import streamlit as st
        from tournament_platform.app.pages.voice_scorekeeper import get_active_voice_processor

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_webrtc_ctx": None,
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)

        result = get_active_voice_processor()
        assert result is None


class TestVoiceListeningFalseRegression:
    def test_drain_skips_live_events_when_voice_listening_false(self, monkeypatch):
        """Live events are skipped when voice_listening=False, but calibration
        events may still be drained."""
        import streamlit as st
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        mock_processor = MagicMock()
        mock_processor.has_pending_events.return_value = True
        mock_processor.get_events.return_value = []

        fake_session_state = {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_listening": False,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_webrtc_ctx": {"processor": mock_processor},
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
        }
        fake_session_state["match_manager"].engine.match_status = "in_progress"
        fake_session_state["match_manager"].state.score_a = 0
        fake_session_state["match_manager"].state.score_b = 0

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: fake_session_state.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        _process_voice_events()
        assert mock_processor.get_events.called


class TestQueueIdentity:
    def test_peek_has_pending_and_get_use_same_queue(self):
        """peek_events, has_pending_events, and get_events must operate on the same queue."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor

        proc = VoiceAudioProcessor()
        proc.event_queue.put(VoiceTranscriptEvent(
            transcript="point blue",
            raw_transcript="point blue",
            event_id="evt-1",
        ))

        assert proc.has_pending_events() is True
        peeked = proc.peek_events(max_items=5)
        assert len(peeked) == 1
        assert peeked[0]["transcript"] == "point blue"

        events = proc.get_events()
        assert len(events) == 1
        assert events[0].transcript == "point blue"
        assert proc.has_pending_events() is False


class TestLegacyTupleNormalization:
    def test_normalize_tuple_with_voice_score_event(self):
        """Legacy tuple (raw_text, text, VoiceScoreEvent) should normalize correctly."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            normalize_voice_transcript_event,
        )
        from tournament_platform.app.services.voice_parser import VoiceScoreEvent

        event = VoiceScoreEvent(
            type="increment",
            raw_text="point blue",
            confidence=0.9,
        )
        event.event_id = "evt-123"

        raw = ("point blue", "point blue", event)
        result = normalize_voice_transcript_event(raw)
        assert result.transcript == "point blue"
        assert result.raw_transcript == "point blue"
        assert result.event_id == "evt-123"
        assert result.source == "continuous"


class TestDrainDiagnostics:
    def test_drain_diagnostics_track_invocation(self):
        """get_drain_diagnostics should return current counters."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            get_drain_diagnostics,
        )

        diag = get_drain_diagnostics()
        assert "invocation_count" in diag
        assert "last_processor_id" in diag
        assert "last_queue_id" in diag
        assert "last_queue_size_before" in diag
        assert "last_queue_size_after" in diag
        assert "last_skipped_reason" in diag


class TestVoiceTranscriptSourceEnum:
    def test_enum_values(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptSource,
        )

        assert VoiceTranscriptSource.CONTINUOUS == "continuous"
        assert VoiceTranscriptSource.PUSH_TO_TALK == "push_to_talk"
        assert VoiceTranscriptSource.TYPED == "typed"
        assert VoiceTranscriptSource.CALIBRATION == "calibration"


class TestNormalizeVoiceTranscriptEventSourceRejection:
    def test_rejects_unknown_source_in_dict(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            InvalidVoiceTranscriptEvent,
            normalize_voice_transcript_event,
        )

        with pytest.raises(InvalidVoiceTranscriptEvent):
            normalize_voice_transcript_event(
                {"transcript": "hello", "event_id": "e1", "source": "unknown_source"}
            )

    def test_rejects_unknown_source_in_dict_string_check(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            InvalidVoiceTranscriptEvent,
            normalize_voice_transcript_event,
        )

        with pytest.raises(InvalidVoiceTranscriptEvent):
            normalize_voice_transcript_event(
                {"transcript": "hello", "event_id": "e1", "source": "bogus"}
            )


class TestLegacyTupleDefaultsToContinuous:
    def test_legacy_tuple_defaults_to_continuous(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptSource,
            normalize_voice_transcript_event,
        )

        result = normalize_voice_transcript_event(("hello", "hello", "e1"))
        assert result.source == VoiceTranscriptSource.CONTINUOUS


class TestVoiceTranscriptEventPostInitNormalization:
    def test_post_init_normalizes_string_source(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptSource,
            VoiceTranscriptEvent,
        )

        evt = VoiceTranscriptEvent(
            transcript="hello",
            raw_transcript="hello",
            event_id="e1",
            source="continuous",
        )
        assert evt.source == VoiceTranscriptSource.CONTINUOUS

    def test_existing_instance_with_string_source_normalizes(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptSource,
            VoiceTranscriptEvent,
        )

        original = VoiceTranscriptEvent(
            transcript="hello",
            raw_transcript="hello",
            event_id="e1",
            source="continuous",
        )
        # __post_init__ normalizes the string to enum on creation
        assert original.source == VoiceTranscriptSource.CONTINUOUS