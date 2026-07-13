"""
Tests for the Live Scoreboard pending-review + Submit Result flow.

Covers:
- ``compute_completed_games`` / ``compute_match_score`` helpers (derived purely
  from the scoring engine's ``round_scores``).
- The final game is retained in ``round_scores`` (so completed games are never
  lost when a match completes).
- Resetting the current game does not erase completed games.
- ``finalize_voice_match`` persists winner / score / game-by-game scores and
  marks the match completed (the ONLY DB-write path).
- Scoring a match to completion does NOT write to the DB on its own (no
  auto-submit); the DB is untouched until Submit Result is clicked.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import (
    Base,
    Player,
    Tournament,
    Match,
    MatchStatus,
    TournamentType,
)
from tournament_platform.app.services.score_engine import create_match, set_score
from tournament_platform.services.match_manager import MatchManager
from tournament_platform.app.pages.voice_scorekeeper import (
    compute_completed_games,
    compute_match_score,
    finalize_voice_match,
)


# ---------------------------------------------------------------------------
# Helper: build an engine with a set of completed games
# ---------------------------------------------------------------------------

def _engine_with_games(round_scores, best_of=5):
    engine = create_match(
        player_a_name="Alice",
        player_b_name="Bob",
        best_of=best_of,
    )
    engine.round_scores = list(round_scores)
    return engine


# ---------------------------------------------------------------------------
# compute_completed_games / compute_match_score
# ---------------------------------------------------------------------------

class TestCompletedGamesHelpers:
    def test_empty_when_no_games(self):
        engine = create_match()
        assert compute_completed_games(engine) == []
        assert compute_match_score([]) == (0, 0)

    def test_single_completed_game_appears(self):
        engine = _engine_with_games([(11, 1)])
        games = compute_completed_games(engine)
        assert len(games) == 1
        assert games[0] == {
            "game": 1,
            "player_a_score": 11,
            "player_b_score": 1,
            "winner": "A",
        }

    def test_multiple_games_in_order(self):
        engine = _engine_with_games([(11, 1), (11, 3), (10, 12)])
        games = compute_completed_games(engine)
        assert [g["game"] for g in games] == [1, 2, 3]
        assert [(g["player_a_score"], g["player_b_score"]) for g in games] == [
            (11, 1),
            (11, 3),
            (10, 12),
        ]
        assert [g["winner"] for g in games] == ["A", "A", "B"]

    def test_match_score_derived_from_games(self):
        engine = _engine_with_games([(11, 1), (11, 3), (10, 12)])
        games = compute_completed_games(engine)
        assert compute_match_score(games) == (2, 1)


# ---------------------------------------------------------------------------
# Engine retains final game / completed games survive resets
# ---------------------------------------------------------------------------

class TestEngineRetainsGames:
    def test_final_game_is_retained_on_match_won(self):
        """When the last game finishes the match, it stays in round_scores."""
        engine = create_match(player_a_name="Alice", player_b_name="Bob", best_of=1)
        set_score(engine, 11, 5)  # completes the only game -> match_won
        assert engine.match_status == "match_won"
        games = compute_completed_games(engine)
        assert games[-1]["player_a_score"] == 11
        assert games[-1]["player_b_score"] == 5
        assert compute_match_score(games) == (1, 0)

    def test_reset_current_game_preserves_completed_games(self):
        mm = MatchManager("Alice", "Bob")
        mm.apply_format(11, 5, "A")
        # Finish game 1 (11-2), then advance to next game.
        mm._set_score(11, 2)
        assert mm.engine.match_status == "game_won"
        mm.engine.match_status = "in_progress"  # simulate "Next Game"
        # Score a couple of points in game 2, then reset the current game.
        mm._add_point("A")
        mm._add_point("B")
        mm.reset_current_game()
        games = compute_completed_games(mm.engine)
        assert len(games) == 1
        assert (games[0]["player_a_score"], games[0]["player_b_score"]) == (11, 2)


# ---------------------------------------------------------------------------
# finalize_voice_match persistence (the ONLY DB-write path)
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(monkeypatch):
    """In-memory SQLite bound as the module-level SessionLocal for the page."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    # Redirect the DB-write helpers in the page and the ranking service to the
    # in-memory database.
    import tournament_platform.app.pages.voice_scorekeeper as page
    monkeypatch.setattr(page, "SessionLocal", TestingSessionLocal)

    yield TestingSessionLocal
    engine.dispose()


def _seed_match(SessionLocal):
    db = SessionLocal()
    try:
        alice = Player(name="Alice", email="alice@example.com", rating=1200)
        bob = Player(name="Bob", email="bob@example.com", rating=1200)
        db.add_all([alice, bob])
        db.commit()
        db.refresh(alice)
        db.refresh(bob)

        tournament = Tournament(
            name="T1", tournament_type=TournamentType.knockout
        )
        db.add(tournament)
        db.commit()
        db.refresh(tournament)

        match = Match(
            player1=alice.name,
            player2=bob.name,
            player1_id=alice.id,
            player2_id=bob.id,
            tournament_id=tournament.id,
            status=MatchStatus.active,
        )
        db.add(match)
        db.commit()
        db.refresh(match)
        return match.id, alice.id
    finally:
        db.close()


class TestFinalizeVoiceMatch:
    def test_submit_persists_winner_score_and_game_scores(self, sqlite_db):
        match_id, alice_id = _seed_match(sqlite_db)

        # Alice wins 3-0 in a best-of-5.
        engine = create_match(
            player_a_name="Alice",
            player_b_name="Bob",
            player_a_id=alice_id,
            best_of=5,
        )
        engine.round_scores = [(11, 3), (11, 5), (11, 8)]
        engine.games_won_a = 3
        engine.games_won_b = 0
        engine.match_status = "match_won"

        finalize_voice_match(match_id, engine)

        db = sqlite_db()
        try:
            row = db.query(Match).filter(Match.id == match_id).first()
            assert row.status == MatchStatus.completed
            assert row.winner == "Alice"
            assert row.winner_id == alice_id
            assert row.score == "3-0"
            assert row.game_scores == "11-3, 11-5, 11-8"
        finally:
            db.close()

    def test_no_auto_submit_until_finalize_called(self, sqlite_db):
        """Scoring a match to completion must NOT write to the DB by itself."""
        match_id, alice_id = _seed_match(sqlite_db)

        # Simulate a full match being scored via the engine only.
        engine = create_match(
            player_a_name="Alice",
            player_b_name="Bob",
            player_a_id=alice_id,
            best_of=1,
        )
        set_score(engine, 11, 4)
        assert engine.match_status == "match_won"

        # No Submit Result has been clicked -> the DB row is still active.
        db = sqlite_db()
        try:
            row = db.query(Match).filter(Match.id == match_id).first()
            assert row.status == MatchStatus.active
            assert row.winner is None
        finally:
            db.close()

        # Now finalize (Submit Result) and confirm it becomes completed.
        finalize_voice_match(match_id, engine)
        db = sqlite_db()
        try:
            row = db.query(Match).filter(Match.id == match_id).first()
            assert row.status == MatchStatus.completed
            assert row.winner == "Alice"
        finally:
            db.close()

    def test_finalize_is_idempotent_on_completed_match(self, sqlite_db):
        match_id, alice_id = _seed_match(sqlite_db)
        engine = create_match(
            player_a_name="Alice",
            player_b_name="Bob",
            player_a_id=alice_id,
            best_of=1,
        )
        engine.round_scores = [(11, 4)]
        engine.games_won_a = 1
        engine.match_status = "match_won"

        finalize_voice_match(match_id, engine)
        # Second call should be a no-op (guarded by the completed status check).
        finalize_voice_match(match_id, engine)

        db = sqlite_db()
        try:
            row = db.query(Match).filter(Match.id == match_id).first()
            assert row.status == MatchStatus.completed
        finally:
            db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
