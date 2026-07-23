"""
Tests for the refactored advanced analytics helpers in voice_scorekeeper.py.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import streamlit as st


class _SessionState(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)

    def __setattr__(self, item, value):
        self[item] = value

    def __delattr__(self, item):
        try:
            del self[item]
        except KeyError:
            raise AttributeError(item)


def _mock_streamlit(monkeypatch):
    mock_st = MagicMock()
    mock_st.session_state = _SessionState()
    monkeypatch.setattr("tournament_platform.app.pages.voice_scorekeeper.st", mock_st)
    return mock_st


def test_stable_session_key_is_stable(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["voice_selected_player1_id"] = 1
    mock_st.session_state["voice_selected_player2_id"] = 2
    mock_st.session_state["_match_session_start_ts"] = 1000

    from tournament_platform.app.pages.voice_scorekeeper import _stable_session_key
    first = _stable_session_key()
    second = _stable_session_key()
    assert first == "session:1:2:1000"
    assert first == second


def test_active_scoring_match_key_with_live_match(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["voice_selected_match_id"] = 42

    from tournament_platform.app.pages.voice_scorekeeper import _active_scoring_match_key
    assert _active_scoring_match_key() == "live:42"


def test_active_scoring_match_key_fallback_to_session(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["voice_selected_player1_id"] = 1
    mock_st.session_state["voice_selected_player2_id"] = 2
    mock_st.session_state["_match_session_start_ts"] = 500

    from tournament_platform.app.pages.voice_scorekeeper import _active_scoring_match_key, _stable_session_key
    assert _active_scoring_match_key() == _stable_session_key()


def test_record_point_event_per_match_dict(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["voice_selected_player1_id"] = 1
    mock_st.session_state["voice_selected_player2_id"] = 2
    mock_st.session_state["_match_session_start_ts"] = 1000
    mock_st.session_state["advanced_point_event_log_by_match"] = {}

    from tournament_platform.app.pages.voice_scorekeeper import (
        _record_successful_point_event,
        _active_scoring_match_key,
        _get_point_log_dict,
    )

    class FakeEngine:
        match_status = "in_progress"
        round_scores = []
        points_played_this_game = 1
        games_won_a = 0
        games_won_b = 0
        score_a = 0
        score_b = 0
        serving_player = "A"
        best_of = 5
        points_to_win = 11
        win_by = 2

    before = FakeEngine()
    after = FakeEngine()
    after.score_a = 1

    _record_successful_point_event(
        match_key="live:10",
        before_state=before,
        after_state=after,
        scorer_side="A",
        source="manual",
    )

    log = _get_point_log_dict()
    assert "live:10" in log
    assert len(log["live:10"]) == 1
    assert log["live:10"][0]["scorer_side"] == "A"
    assert log["live:10"][0]["score_a_after"] == 1


def test_pop_successful_point_event(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:10": [
            {"game_index": 0, "scorer_side": "A"},
            {"game_index": 1, "scorer_side": "A"},
        ]
    }

    from tournament_platform.app.pages.voice_scorekeeper import _pop_successful_point_event
    _pop_successful_point_event("live:10", 1)
    assert len(mock_st.session_state["advanced_point_event_log_by_match"]["live:10"]) == 1
    assert mock_st.session_state["advanced_point_event_log_by_match"]["live:10"][0]["game_index"] == 0


def test_pop_point_events_for_game(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:10": [
            {"game_index": 0, "scorer_side": "A"},
            {"game_index": 0, "scorer_side": "B"},
            {"game_index": 1, "scorer_side": "A"},
        ]
    }

    from tournament_platform.app.pages.voice_scorekeeper import _pop_point_events_for_game
    _pop_point_events_for_game("live:10", 0)
    events = mock_st.session_state["advanced_point_event_log_by_match"]["live:10"]
    assert len(events) == 1
    assert events[0]["game_index"] == 1


def test_last_event_game_index(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:10": [
            {"game_index": 0, "scorer_side": "A"},
            {"game_index": 1, "scorer_side": "B"},
            {"game_index": 1, "scorer_side": "A"},
        ]
    }

    from tournament_platform.app.pages.voice_scorekeeper import _last_event_game_index
    assert _last_event_game_index("live:10", "A") == 1
    assert _last_event_game_index("live:10") == 1
    assert _last_event_game_index("live:99") is None


def test_clear_point_events_for_match(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:10": [{"game_index": 0}],
        "live:20": [{"game_index": 0}],
    }

    from tournament_platform.app.pages.voice_scorekeeper import _clear_point_events_for_match
    _clear_point_events_for_match("live:10")
    assert "live:10" not in mock_st.session_state["advanced_point_event_log_by_match"]
    assert "live:20" in mock_st.session_state["advanced_point_event_log_by_match"]


def test_clear_advanced_analytics_state_selective(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:10": [{"game_index": 0}],
        "live:20": [{"game_index": 0}],
    }
    mock_st.session_state["advanced_analytics_partial"] = True

    from tournament_platform.app.pages.voice_scorekeeper import _clear_advanced_analytics_state
    _clear_advanced_analytics_state(match_key="live:10")
    assert "live:10" not in mock_st.session_state["advanced_point_event_log_by_match"]
    assert "live:20" in mock_st.session_state["advanced_point_event_log_by_match"]
    assert mock_st.session_state["advanced_analytics_partial"] is False


def test_clear_advanced_analytics_state_global(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:10": [{"game_index": 0}],
    }
    mock_st.session_state["advanced_analytics_partial"] = True

    from tournament_platform.app.pages.voice_scorekeeper import _clear_advanced_analytics_state
    _clear_advanced_analytics_state()
    assert mock_st.session_state["advanced_point_event_log_by_match"] == {}
    assert mock_st.session_state["advanced_analytics_partial"] is False


def test_migrate_legacy_point_log(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log"] = [
        {"match_id": 10, "game_index": 0},
        {"match_id": 10, "game_index": 1},
    ]
    mock_st.session_state["advanced_point_event_log_by_match"] = {}
    mock_st.session_state["_legacy_point_log_migrated"] = False
    mock_st.session_state["voice_selected_match_id"] = 10
    mock_st.session_state["_match_session_start_ts"] = 1000

    from tournament_platform.app.pages.voice_scorekeeper import _migrate_legacy_point_log, _get_point_log_dict
    _migrate_legacy_point_log()
    assert mock_st.session_state["_legacy_point_log_migrated"] is True
    assert mock_st.session_state["advanced_point_event_log"] == []
    log = _get_point_log_dict()
    assert "live:10" in log
    assert len(log["live:10"]) == 2


def test_migrate_legacy_point_log_idempotent(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log"] = []
    mock_st.session_state["advanced_point_event_log_by_match"] = {"live:10": []}
    mock_st.session_state["_legacy_point_log_migrated"] = True

    from tournament_platform.app.pages.voice_scorekeeper import _migrate_legacy_point_log
    _migrate_legacy_point_log()
    assert mock_st.session_state["_legacy_point_log_migrated"] is True


def test_finalize_match_migrates_live_to_completed(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["advanced_point_event_log_by_match"] = {
        "live:5": [{"game_index": 0}],
    }

    from tournament_platform.app.pages.voice_scorekeeper import _get_point_log_dict, finalize_voice_match

    mock_db = MagicMock()
    mock_match = MagicMock()
    mock_match.status = "active"
    mock_match.id = 5
    mock_db.query.return_value.filter.return_value.first.return_value = mock_match

    mock_updated = MagicMock()
    mock_updated.winner_id = 1
    mock_updated.player1_id = 1
    mock_updated.player2_id = 2

    monkeypatch.setattr(
        "tournament_platform.app.pages.voice_scorekeeper.SessionLocal",
        lambda: mock_db,
    )
    monkeypatch.setattr(
        "tournament_platform.services.match_reporting.report_existing_match",
        lambda db, cmd: mock_updated,
    )
    monkeypatch.setattr(
        "tournament_platform.services.ranking_service.RatingManager",
        MagicMock,
    )

    class FakeEngine:
        games_won_a = 2
        games_won_b = 1
        player_a_name = "A"
        player_b_name = "B"
        round_scores = [(11, 9), (11, 8)]

    finalize_voice_match(5, FakeEngine())

    log = _get_point_log_dict()
    assert "live:5" not in log
    assert "completed:5" in log
    assert len(log["completed:5"]) == 1


def test_apply_selected_match_sets_stable_key(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["_match_session_start_ts"] = None
    mock_st.session_state["match_manager"] = MagicMock()
    mock_st.session_state["match_manager"].state.player_a_id = None
    mock_st.session_state["match_manager"].state.player_b_id = None

    from tournament_platform.app.pages.voice_scorekeeper import apply_selected_match_to_session

    apply_selected_match_to_session({
        "match_id": 10,
        "player1_id": 1,
        "player1_name": "Alice",
        "player2_id": 2,
        "player2_name": "Bob",
    })
    assert mock_st.session_state["voice_selected_match_id"] == 10
    assert mock_st.session_state["_match_session_start_ts"] is not None


def test_clear_selected_match_clears_stable_key(monkeypatch):
    mock_st = _mock_streamlit(monkeypatch)
    mock_st.session_state["_match_session_start_ts"] = 1234
    mock_st.session_state["voice_selected_match_id"] = 10
    mock_st.session_state["advanced_point_event_log_by_match"] = {"live:10": []}

    from tournament_platform.app.pages.voice_scorekeeper import clear_selected_match
    clear_selected_match()
    assert mock_st.session_state["_match_session_start_ts"] is None
    assert mock_st.session_state["voice_selected_match_id"] is None
