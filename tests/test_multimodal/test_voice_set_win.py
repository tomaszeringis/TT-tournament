"""
Tests for set_win commentary helpers in voice_scorekeeper.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest


class _SessionStateProxy(dict):
    """Dict that also supports attribute access, like real Streamlit session_state."""
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


def _make_fake_session_state():
    state = _SessionStateProxy()
    state["voice_selected_match_id"] = None
    state["commentary_emitted_game_keys"] = []
    state["commentary_enabled"] = True
    state["commentary_muted"] = False
    state["commentary_mode"] = "after_every_game"
    state["commentary_intensity"] = "medium"
    state["commentary_language"] = "en"
    state["commentary_style"] = "neutral"
    state["pending_commentary"] = None
    state["last_commentary_event_id"] = None
    state["last_commentary_text"] = None
    state["last_set_win_text"] = None
    state["last_commentary_debug"] = None
    state["voice_selected_tournament_id"] = None
    state["match_manager"] = None
    return state


class TestEmitSetWinCommentary:
    def test_off_mode_does_not_emit(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk

        session = _make_fake_session_state()
        session["commentary_mode"] = "off"
        monkeypatch.setattr(vsk.st, "session_state", session)
        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is False
        assert session["pending_commentary"] is None

    def test_visual_only_emits_but_does_not_speak(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.VISUAL_ONLY.value
        monkeypatch.setattr(vsk.st, "session_state", session)
        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is True
        assert session["pending_commentary"] is not None
        assert session["pending_commentary"].should_speak is False

    def test_after_every_game_emits_and_speaks(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.AFTER_EVERY_GAME.value
        monkeypatch.setattr(vsk.st, "session_state", session)
        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is True
        assert session["pending_commentary"].should_speak is True

    def test_every_point_emits_and_speaks(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.EVERY_POINT.value
        monkeypatch.setattr(vsk.st, "session_state", session)
        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is True
        assert session["pending_commentary"].should_speak is True

    def test_spoken_mode_emits_and_speaks(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.SPOKEN.value
        session["commentary_intensity"] = "high"
        monkeypatch.setattr(vsk.st, "session_state", session)
        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is True
        assert session["pending_commentary"].should_speak is True

    def test_important_only_emits_and_speaks(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.IMPORTANT_ONLY.value
        monkeypatch.setattr(vsk.st, "session_state", session)
        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is True
        assert session["pending_commentary"].should_speak is True

    def test_rerun_dedup_prevents_duplicate(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.AFTER_EVERY_GAME.value
        monkeypatch.setattr(vsk.st, "session_state", session)
        game_event = {
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }
        assert vsk._emit_set_win_commentary(game_event, speak=True) is True
        assert vsk._emit_set_win_commentary(game_event, speak=True) is False
        assert len(session["commentary_emitted_game_keys"]) == 1

    def test_final_game_set_win_and_match_win(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        session = _make_fake_session_state()
        session["voice_selected_match_id"] = "m1"
        session["commentary_mode"] = CommentaryMode.AFTER_EVERY_GAME.value
        monkeypatch.setattr(vsk.st, "session_state", session)

        engine = MagicMock()
        engine.round_scores = [(11, 9), (11, 7), (11, 5)]
        engine.games_won_a = 3
        engine.games_won_b = 0
        engine.match_status = "match_won"
        engine.points_to_win = 11
        engine.best_of = 5
        engine.first_server = "A"

        manager = MagicMock()
        manager.engine = engine
        manager.state.player_a = "Alice"
        manager.state.player_b = "Bob"

        session["match_manager"] = manager

        vsk._reconcile_finished_games()

        assert session["pending_commentary"] is not None
        assert session["pending_commentary"].event_type == "set_win"
        assert session["pending_commentary"].should_speak is True
        assert len(session["commentary_emitted_game_keys"]) == 4

    def test_ollama_invalid_rewrite_falls_back(self, monkeypatch):
        from tournament_platform.app.pages import voice_scorekeeper as vsk
        from tournament_platform.services.commentary_service import CommentaryMode

        service = vsk.CommentaryService()
        original_call_ollama = service.rewriter._call_ollama

        def bad_ollama(prompt):
            return "Completely different text with wrong score"

        monkeypatch.setattr(service.rewriter, "_call_ollama", bad_ollama)

        session = _make_fake_session_state()
        session["commentary_mode"] = CommentaryMode.AFTER_EVERY_GAME.value
        session["commentary_ollama_rewrite_enabled"] = True
        monkeypatch.setattr(vsk.st, "session_state", session)
        monkeypatch.setattr(vsk, "_commentary_service", service)

        emitted = vsk._emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": 1,
            "winner": "Alice",
            "loser": "Bob",
            "game_score": "11\u20135",
            "match_score": "1\u20130",
            "completed_games": ["11\u20135"],
            "language": "en",
            "style": "neutral",
            "player_a": "Alice",
            "player_b": "Bob",
        }, speak=True)
        assert emitted is True
        assert "Alice" in session["pending_commentary"].text
        assert "11" in session["pending_commentary"].text
