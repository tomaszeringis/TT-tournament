"""Unit tests for the Deepgram keyterm builder.

Covers plan §2.2, §5, §9.2 (test_deepgram_keyterms.py).
"""
from __future__ import annotations

import hashlib
import pytest

from tournament_platform.app.services.asr_backends.deepgram_adapter import (
    build_deepgram_keyterms,
    KeytermResult,
)


class TestKeytermPriority:
    def test_player_names_first(self):
        result = build_deepgram_keyterms(
            player_names=["Tomas Žeringis", "Juozas Petraitis"],
            language="lt",
        )
        assert result.terms[0] == "Tomas Žeringis"
        assert result.terms[1] == "Juozas Petraitis"

    def test_player_names_before_commands(self):
        result = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
        )
        # "Alice" must appear before any command word
        alice_idx = list(result.terms).index("Alice")
        point_idx = list(result.terms).index("point red")
        assert alice_idx < point_idx

    def test_numbers_after_commands(self):
        result = build_deepgram_keyterms(
            player_names=[],
            language="en",
        )
        terms = list(result.terms)
        # Find the last core command and first number
        numbers = ["zero", "one", "two", "three"]
        undo_idx = terms.index("undo")
        zero_idx = terms.index("zero")
        assert zero_idx > undo_idx


class TestKeytermDedup:
    def test_duplicate_player_names(self):
        result = build_deepgram_keyterms(
            player_names=["Alice", "Alice", "alice"],
        )
        alice_count = sum(1 for t in result.terms if t.lower() == "alice")
        assert alice_count == 1

    def test_duplicate_commands(self):
        result = build_deepgram_keyterms(
            player_names=[],
            language="en",
        )
        undo_count = sum(1 for t in result.terms if t == "undo")
        assert undo_count == 1

    def test_casefold_dedup(self):
        result = build_deepgram_keyterms(
            player_names=["Point Red", "point red"],
        )
        matches = [t for t in result.terms if t.lower() == "point red"]
        assert len(matches) == 1


class TestKeytermTruncation:
    def test_hard_cap_at_100(self):
        result = build_deepgram_keyterms(
            player_names=["p1", "p2", "p3"],
            language="lt",
            custom_terms=[f"custom_term_{i}" for i in range(200)],
            max_terms=100,
        )
        assert result.count == 100
        assert result.truncated > 0

    def test_truncated_terms_recorded(self):
        result = build_deepgram_keyterms(
            player_names=[],
            language="lt",
            custom_terms=[f"extra{i}" for i in range(200)],
            max_terms=50,
        )
        assert len(result.truncated_terms) > 0
        assert result.truncated == len(result.truncated_terms)

    def test_player_names_preserved_on_truncation(self):
        result = build_deepgram_keyterms(
            player_names=["ImportantPlayer"],
            language="lt",
            custom_terms=[f"extra{i}" for i in range(200)],
            max_terms=50,
        )
        assert "ImportantPlayer" in result.terms

    def test_no_truncation_below_cap(self):
        result = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
            max_terms=500,
        )
        assert result.truncated == 0


class TestKeytermSerialization:
    def test_serialize_produces_repeated_params(self):
        result = build_deepgram_keyterms(
            player_names=["Alice", "Bob"],
            language="en",
            custom_terms=["custom1"],
            max_terms=5,
        )
        serialized = result.serialize()
        keyterm_params = [k for k, _ in serialized]
        assert all(k == "keyterm" for k in keyterm_params)
        assert len(serialized) == result.count

    def test_no_comma_separation(self):
        terms = ["Tomas Žeringis", "Juozas Petraitis", "taškas"]
        result = build_deepgram_keyterms(
            player_names=terms,
            language="lt",
            max_terms=500,
        )
        serialized = result.serialize()
        # Player names must each be a separate tuple (not comma-joined)
        player_serialized = [v for k, v in serialized if v in terms]
        assert len(player_serialized) == len(terms)
        for v in player_serialized:
            assert "," not in v
        assert all(k == "keyterm" for k, _ in serialized)

    def test_unicode_preserved(self):
        result = build_deepgram_keyterms(
            player_names=["Tomas Žeringis"],
            language="lt",
        )
        assert "Tomas Žeringis" in result.terms


class TestKeytermVersionHash:
    def test_hash_stability(self):
        r1 = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
        )
        r2 = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
        )
        assert r1.version_hash == r2.version_hash

    def test_hash_changes_with_different_players(self):
        r1 = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
        )
        r2 = build_deepgram_keyterms(
            player_names=["Bob"],
            language="en",
        )
        assert r1.version_hash != r2.version_hash

    def test_hash_changes_with_language(self):
        r1 = build_deepgram_keyterms(
            player_names=["Alice"],
            language="lt",
        )
        r2 = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
        )
        assert r1.version_hash != r2.version_hash


class TestKeytermEmptyConfig:
    def test_empty_player_names(self):
        result = build_deepgram_keyterms(
            player_names=[],
            language="en",
            max_terms=500,
        )
        assert result.count > 0  # commands + numbers still present
        assert result.truncated == 0

    def test_empty_custom_terms(self):
        result = build_deepgram_keyterms(
            player_names=["Alice"],
            language="en",
            custom_terms=[],
        )
        assert "Alice" in result.terms
