"""
Unit tests for the interactive bracket data pipeline and defensive rendering.

These tests exercise ``build_bracket_data`` (a pure function) and the defensive
guards in ``render_bracket`` without needing a browser or the Streamlit runtime.
Streamlit and the custom component are replaced with mocks where needed.
"""

import sys
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tournament_platform.models import MatchStatus
from tournament_platform.app.pages import events_draws
from tournament_platform.app.pages.events_draws import (
    build_bracket_data,
    render_bracket,
    BRACKET_STATUS_COMPLETED,
    BRACKET_STATUS_READY,
)


def make_player(pid, name):
    return SimpleNamespace(id=pid, name=name)


def make_match(
    mid,
    player1,
    player2,
    status=MatchStatus.pending,
    score=None,
    round_number=1,
    bracket_index=0,
    player1_id=None,
    player2_id=None,
):
    return SimpleNamespace(
        id=mid,
        player1=player1,
        player2=player2,
        status=status,
        score=score,
        round_number=round_number,
        bracket_index=bracket_index,
        player1_id=player1_id,
        player2_id=player2_id,
    )


def make_tournament(tid, matches):
    return SimpleNamespace(id=tid, matches=matches)


class TestBuildBracketData:
    def test_valid_shape_single_elimination(self):
        players = [make_player(1, "Alice"), make_player(2, "Bob")]
        matches = [make_match(10, "Alice", "Bob", round_number=1, bracket_index=0)]
        tournament = make_tournament(1, matches)

        data = build_bracket_data(tournament, players)

        assert data is not None
        assert set(data.keys()) == {"stages", "matches", "participants"}
        assert len(data["stages"]) == 1
        assert data["stages"][0]["type"] == "single_elimination"
        assert len(data["matches"]) == 1
        m = data["matches"][0]
        assert m["id"] == 10
        assert m["roundId"] == 0  # round_number 1 -> roundId 0
        assert m["opponent1"]["id"] == 1
        assert m["opponent2"]["id"] == 2

    def test_returns_none_when_no_matches(self):
        tournament = make_tournament(1, [])
        assert build_bracket_data(tournament, [make_player(1, "Alice")]) is None

    def test_returns_none_when_tournament_none(self):
        assert build_bracket_data(None, []) is None

    def test_participants_derived_from_entrants_only(self):
        # DB has 10 players but only 2 are entrants -> bracket must not balloon.
        players = [make_player(i, f"P{i}") for i in range(1, 11)]
        matches = [make_match(10, "P1", "P2")]
        tournament = make_tournament(1, matches)

        data = build_bracket_data(tournament, players)

        assert len(data["participants"]) == 2
        names = {p["name"] for p in data["participants"]}
        assert names == {"P1", "P2"}
        # bracket_size for 2 participants is the minimum (4), not 16.
        assert data["stages"][0]["settings"]["size"] == 4

    def test_all_opponent_ids_present_in_participants(self):
        # Include a player unknown to the DB and a normal one.
        players = [make_player(1, "Alice")]
        matches = [
            make_match(10, "Alice", "Ghost"),  # Ghost not in players
            make_match(11, "Alice", "TBD"),  # bye
        ]
        tournament = make_tournament(1, matches)

        data = build_bracket_data(tournament, players)

        participant_ids = {p["id"] for p in data["participants"]}
        for m in data["matches"]:
            for op in (m["opponent1"], m["opponent2"]):
                if op["id"] is not None:
                    assert op["id"] in participant_ids

    def test_status_mapping_completed_and_pending(self):
        players = [make_player(1, "Alice"), make_player(2, "Bob")]
        matches = [
            make_match(10, "Alice", "Bob", status=MatchStatus.completed, score="11-3"),
            make_match(11, "Alice", "Bob", status=MatchStatus.pending),
        ]
        tournament = make_tournament(1, matches)

        data = build_bracket_data(tournament, players)

        completed = next(m for m in data["matches"] if m["id"] == 10)
        pending = next(m for m in data["matches"] if m["id"] == 11)
        assert completed["status"] == BRACKET_STATUS_COMPLETED == 4
        assert pending["status"] == BRACKET_STATUS_READY == 2
        assert completed["opponent1"]["score"] == 11
        assert completed["opponent2"]["score"] == 3

    def test_prefers_fk_ids_when_present(self):
        # No matching DB player names, but FK ids are provided.
        players = []
        matches = [
            make_match(10, "Alice", "Bob", player1_id=7, player2_id=8),
        ]
        tournament = make_tournament(1, matches)

        data = build_bracket_data(tournament, players)

        m = data["matches"][0]
        assert m["opponent1"]["id"] == 7
        assert m["opponent2"]["id"] == 8
        assert {p["id"] for p in data["participants"]} == {7, 8}

    def test_handles_missing_optional_fields(self):
        players = [make_player(1, "Alice")]
        matches = [
            make_match(
                10,
                "Alice",
                "TBD",
                status=MatchStatus.completed,
                score=None,  # completed but no score
                round_number=None,  # missing round
                bracket_index=None,
            ),
        ]
        tournament = make_tournament(1, matches)

        # Should not raise.
        data = build_bracket_data(tournament, players)
        m = data["matches"][0]
        assert m["roundId"] == 0  # None round_number -> default 1 -> roundId 0
        assert m["number"] == 0
        assert m["opponent2"]["id"] is None  # TBD -> no id
        assert m["opponent1"]["score"] is None  # no score parsed

    def test_bad_score_does_not_raise(self):
        players = [make_player(1, "Alice"), make_player(2, "Bob")]
        matches = [
            make_match(10, "Alice", "Bob", status=MatchStatus.completed, score="garbage"),
        ]
        tournament = make_tournament(1, matches)
        data = build_bracket_data(tournament, players)
        m = data["matches"][0]
        assert m["opponent1"]["score"] is None
        assert m["opponent2"]["score"] is None


class TestNormalizeBracketMatches:
    def test_normalizes_required_fields_with_defaults(self):
        matches = [
            make_match(10, None, None, round_number=None, bracket_index=None),
        ]
        result = events_draws.normalize_bracket_matches(matches)
        assert len(result) == 1
        m = result[0]
        assert m["id"] == 10
        assert m["round"] == 1  # None -> default 1
        assert m["player1"] == "TBD"
        assert m["player2"] == "TBD"
        assert m["status"] == "pending"
        # Two TBD players -> not a fully valid renderable match.
        assert m["valid"] is False

    def test_valid_when_at_least_one_real_player(self):
        matches = [make_match(10, "Alice", "TBD")]
        m = events_draws.normalize_bracket_matches(matches)[0]
        assert m["valid"] is True
        assert m["player2"] == "TBD"

    def test_status_enum_converted_to_string(self):
        matches = [make_match(10, "Alice", "Bob", status=MatchStatus.completed, score="11-3")]
        m = events_draws.normalize_bracket_matches(matches)[0]
        assert m["status"] == "completed"
        assert m["score"] == "11-3"

    def test_sorted_by_round_then_bracket_index(self):
        matches = [
            make_match(2, "C", "D", round_number=2, bracket_index=0),
            make_match(1, "A", "B", round_number=1, bracket_index=1),
            make_match(3, "E", "F", round_number=1, bracket_index=0),
        ]
        result = events_draws.normalize_bracket_matches(matches)
        assert [m["id"] for m in result] == [3, 1, 2]

    def test_empty_input(self):
        assert events_draws.normalize_bracket_matches([]) == []
        assert events_draws.normalize_bracket_matches(None) == []


class TestRenderBracketFallback:
    def _fake_st(self, monkeypatch):
        fake_st = MagicMock()
        # st.columns(n) must return an iterable of context-manager-capable mocks.
        fake_st.columns.side_effect = lambda n, *a, **k: [
            MagicMock() for _ in range(n if isinstance(n, int) else len(n))
        ]
        monkeypatch.setattr(events_draws, "st", fake_st)
        return fake_st

    def test_renders_a_card_per_match(self, monkeypatch):
        fake_st = self._fake_st(monkeypatch)
        normalized = events_draws.normalize_bracket_matches(
            [
                make_match(1, "A", "B", round_number=1),
                make_match(2, "C", "D", round_number=1),
                make_match(3, "W1", "W2", round_number=2),
            ]
        )
        events_draws.render_bracket_fallback(normalized)
        # One bordered container per match.
        assert fake_st.container.call_count == 3

    def test_empty_matches_shows_info_not_blank(self, monkeypatch):
        fake_st = self._fake_st(monkeypatch)
        events_draws.render_bracket_fallback([])
        assert fake_st.info.called
        assert fake_st.container.call_count == 0

    def test_many_rounds_stacks_without_error(self, monkeypatch):
        self._fake_st(monkeypatch)
        matches = [make_match(i, f"P{i}", f"Q{i}", round_number=i) for i in range(1, 9)]
        normalized = events_draws.normalize_bracket_matches(matches)
        # Should not raise even with > 6 rounds.
        events_draws.render_bracket_fallback(normalized)


class TestRenderBracket:
    def _fake_st(self, monkeypatch):
        fake_st = MagicMock()
        fake_st.columns.side_effect = lambda n, *a, **k: [
            MagicMock() for _ in range(n if isinstance(n, int) else len(n))
        ]
        monkeypatch.setattr(events_draws, "st", fake_st)
        return fake_st

    def test_empty_state_when_no_matches(self, monkeypatch):
        self._fake_st(monkeypatch)
        empty_state = MagicMock()
        component = MagicMock()
        monkeypatch.setattr(events_draws, "render_empty_state", empty_state)
        monkeypatch.setattr(events_draws, "interactive_bracket", component)

        tournament = make_tournament(1, [])
        render_bracket(tournament, [])

        assert empty_state.called
        assert not component.called

    def test_empty_state_when_tournament_none(self, monkeypatch):
        self._fake_st(monkeypatch)
        empty_state = MagicMock()
        component = MagicMock()
        monkeypatch.setattr(events_draws, "render_empty_state", empty_state)
        monkeypatch.setattr(events_draws, "interactive_bracket", component)

        render_bracket(None, [])

        assert empty_state.called
        assert not component.called

    def test_native_fallback_always_rendered_with_matches(self, monkeypatch):
        fake_st = self._fake_st(monkeypatch)
        empty_state = MagicMock()
        component = MagicMock(return_value=None)
        monkeypatch.setattr(events_draws, "render_empty_state", empty_state)
        monkeypatch.setattr(events_draws, "interactive_bracket", component)

        players = [make_player(1, "Alice"), make_player(2, "Bob")]
        tournament = make_tournament(1, [make_match(10, "Alice", "Bob")])
        render_bracket(tournament, players)

        # Native fallback rendered at least one match card (never blank).
        assert fake_st.container.called
        # Interactive visual bracket still attempted (inside the expander).
        assert component.called
        assert not empty_state.called

    def test_visual_component_failure_does_not_blank_or_raise(self, monkeypatch):
        fake_st = self._fake_st(monkeypatch)
        monkeypatch.setattr(events_draws, "render_empty_state", MagicMock())
        boom = MagicMock(side_effect=RuntimeError("render failed"))
        monkeypatch.setattr(events_draws, "interactive_bracket", boom)

        players = [make_player(1, "Alice"), make_player(2, "Bob")]
        tournament = make_tournament(1, [make_match(10, "Alice", "Bob")])

        # Must not propagate the exception...
        render_bracket(tournament, players)

        # ...native fallback still rendered (section not blank)...
        assert fake_st.container.called
        # ...and a warning was surfaced about the visual bracket.
        assert fake_st.warning.called
