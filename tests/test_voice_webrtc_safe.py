"""Regression tests for safe WebRTC/processor access helpers."""

import queue

from tournament_platform.app.pages.voice_scorekeeper import (
    _get_voice_webrtc_processor,
    _safe_queue_size,
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
