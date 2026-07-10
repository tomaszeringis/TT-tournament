"""
Tests for Voice Alias Expansion (Phase 3).
"""

import pytest

from tournament_platform.app.services.voice.aliases import AliasExpander


class TestAliasExpander:
    def setup_method(self):
        aliases = {
            "en": {
                "point red": ["point red", "red point"],
                "undo": ["undo", "take back"],
            },
            "lt": {
                "point red": ["taškas raudona", "raudona taškas"],
            },
        }
        self.expander = AliasExpander(aliases=aliases)

    def test_lithuanian_alias_expands_to_english(self):
        result = self.expander.expand("taškas raudona", language="lt")
        assert "point red" in result

    def test_unknown_alias_ignored(self):
        result = self.expander.expand("random text", language="en")
        assert result == "random text"

    def test_alias_does_not_break_existing_commands(self):
        result = self.expander.expand("point to player one", language="en")
        assert "point to player one" in result

    def test_english_alias_expands(self):
        result = self.expander.expand("red point", language="en")
        assert "point red" in result
