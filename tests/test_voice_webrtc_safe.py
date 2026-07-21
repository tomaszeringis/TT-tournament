"""Regression tests for safe WebRTC/processor access helpers."""

import queue

from tournament_platform.app.pages.voice_scorekeeper import (
    _get_voice_webrtc_processor,
    _safe_queue_size,
    VoiceAudioProcessor,
)


def test_get_voice_webrtc_processor_none_safe():
    assert _get_voice_webrtc_processor(None) is None


def test_get_voice_webrtc_processor_from_dict():
    processor = object()
    assert _get_voice_webrtc_processor({"processor": processor}) is processor


def test_get_voice_webrtc_processor_from_object_attr():
    processor = object()

    class Ctx:
        audio_processor = processor

    assert _get_voice_webrtc_processor(Ctx()) is processor


def test_get_voice_webrtc_processor_unknown_object_safe():
    assert _get_voice_webrtc_processor(object()) is None


def test_safe_queue_size_none():
    assert _safe_queue_size(None) == 0


def test_safe_queue_size_valid_queue():
    q = queue.Queue()
    q.put(1)
    assert _safe_queue_size(q) == 1


def test_safe_queue_size_non_queue_object():
    assert _safe_queue_size("not a queue") == 0


def test_has_pending_events_true_when_events_queued():
    processor = VoiceAudioProcessor()
    processor.event_queue.put(("raw", "text", object()))
    assert processor.has_pending_events() is True


def test_has_pending_events_false_when_empty():
    processor = VoiceAudioProcessor()
    assert processor.has_pending_events() is False


def test_trace_event_not_accepted():
    from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace

    class _SessionStateProxy(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError:
                raise AttributeError(name)
        def __setattr__(self, name, value):
            self[name] = value
        def __delattr__(self, name):
            try:
                del self[name]
            except KeyError:
                raise AttributeError(name)

    import unittest.mock
    state = _SessionStateProxy({
        "voice_audit_events": [],
        "voice_event_logger": unittest.mock.MagicMock(),
    })

    with unittest.mock.patch(
        "tournament_platform.app.pages.voice_scorekeeper.st"
    ) as mock_st:
        mock_st.session_state = state
        mock_st.secrets = unittest.mock.MagicMock()
        mock_st.secrets.get = unittest.mock.MagicMock(return_value=None)
        _append_continuous_trace("test_stage", "test_note")

    events = state.get("voice_audit_events", [])
    assert len(events) == 1
    assert events[0]["accepted"] is False
