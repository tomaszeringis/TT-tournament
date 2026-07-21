"""Tests for TT Sounds classifier import safety."""

import pytest

from tournament_platform.app.services.tt_sounds.classifier import TTClassifier


class TestTTClassifier:
    def test_missing_torch_returns_unavailable(self):
        clf = TTClassifier(model_dir="")
        assert clf.available is False
        result = clf.classify(None)
        assert result["available"] is False
        assert result["surface"] == "unknown"

    def test_empty_model_dir(self):
        clf = TTClassifier(model_dir="")
        assert clf.available is False
