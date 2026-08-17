"""Unit tests for the DeepgramAdapter transcript normalization.

Covers plan §9.2 (test_deepgram_adapter.py).
"""
from __future__ import annotations

import pytest

from tournament_platform.app.services.asr_backends.deepgram_adapter import (
    DeepgramAdapter,
)


class TestNFCNormalization:
    def test_lithuanian_diacritics_preserved(self):
        adapter = DeepgramAdapter()
        text = "aš tuščiai"
        result = adapter.normalize(text)
        assert "aš" in result
        assert "tuščiai" in result

    def test_mixed_composition_decomposed(self):
        adapter = DeepgramAdapter()
        # \u0105 (ą) decomposed as 'a' + combining ogonek
        decomposed = "a\u0328"  # a + combining ogonek = ą decomposed
        result = adapter.normalize(decomposed)
        assert "\u0105" in result  # should be NFC composed

    def test_whitespace_collapsed(self):
        adapter = DeepgramAdapter()
        result = adapter.normalize("hello    world")
        assert result == "hello world"

    def test_stripped(self):
        adapter = DeepgramAdapter()
        result = adapter.normalize("  test  ")
        assert result == "test"

    def test_empty_string(self):
        adapter = DeepgramAdapter()
        assert adapter.normalize("") == ""

    def test_none_like_empty(self):
        adapter = DeepgramAdapter()
        assert adapter.normalize("") == ""


class TestNumeralFormatting:
    def test_number_words_converted(self):
        adapter = DeepgramAdapter()
        result = adapter.process_transcript("point red five four", is_interim=False)
        assert "5" in result
        assert "4" in result

    def test_number_words_not_converted_from_interim(self):
        adapter = DeepgramAdapter()
        result = adapter.process_transcript("five four", is_interim=True)
        assert "five" in result
        assert "4" not in result

    def test_homophone_for_to(self):
        adapter = DeepgramAdapter()
        result = adapter.process_transcript("for", is_interim=False)
        assert "4" in result

    def test_unknown_words_preserved(self):
        adapter = DeepgramAdapter()
        result = adapter.process_transcript("hello world", is_interim=False)
        assert "hello" in result
        assert "world" in result


class TestInterimHandling:
    def test_interim_never_emits_numerals(self):
        adapter = DeepgramAdapter()
        for text in ["five", "one two", "ten"]:
            result = adapter.process_transcript(text, is_interim=True)
            for char in "0123456789":
                assert char not in result, f"Digit found in interim: {result}"

    def test_interim_still_normalized(self):
        adapter = DeepgramAdapter()
        result = adapter.process_transcript("  Tąškas  ", is_interim=True)
        assert result == "Tąškas"


class TestExtractTranscript:
    def test_extract_from_mock_message(self):
        adapter = DeepgramAdapter()

        class _MockAlt:
            transcript = "point red"

        class _MockChannel:
            alternatives = [_MockAlt()]

        class _MockMsg:
            channel = _MockChannel()

        assert adapter.extract_transcript(_MockMsg()) == "point red"

    def test_extract_missing_channel(self):
        adapter = DeepgramAdapter()
        assert adapter.extract_transcript(object()) == ""

    def test_extract_empty_alternatives(self):
        adapter = DeepgramAdapter()

        class _MockChannel:
            alternatives = []

        class _MockMsg:
            channel = _MockChannel()

        assert adapter.extract_transcript(_MockMsg()) == ""


class TestFinalFlags:
    def test_is_final_true(self):
        adapter = DeepgramAdapter()

        class _Msg:
            is_final = True

        assert adapter.is_final(_Msg()) is True

    def test_is_final_none(self):
        adapter = DeepgramAdapter()

        class _Msg:
            is_final = None

        assert adapter.is_final(_Msg()) is False

    def test_is_speech_final_true(self):
        adapter = DeepgramAdapter()

        class _Msg:
            speech_final = True

        assert adapter.is_speech_final(_Msg()) is True

    def test_is_speech_final_false(self):
        adapter = DeepgramAdapter()

        class _Msg:
            speech_final = False

        assert adapter.is_speech_final(_Msg()) is False
