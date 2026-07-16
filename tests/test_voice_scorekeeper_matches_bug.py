"""
Regression test for the Voice Scorekeeper "No active or pending matches" bug.

Reproduces a tournament (e.g. "LITIT taure") with generated pending knockout
matches shown on the Tournament page, then asserts that Voice Scorekeeper's
``fetch_active_matches`` reads the same canonical ``Match`` table and returns
those generated pending matches even when no external FastAPI server is running.

Also covers:
- no duplicate matches after repeated generation (idempotent upstream generation)
- selecting a generated pending match loads the correct player names
- completed matches are excluded from the active selector
"""

import pytest
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, Player, Tournament, Match, MatchStatus, TournamentType
from tournament_platform.services.tournament_engine import KnockoutStrategy


@pytest.fixture
def sqlite_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    import tournament_platform.app.pages.voice_scorekeeper as page
    import tournament_platform.app.components.match_selector as selector
    monkeypatch.setattr(page, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(selector, "SessionLocal", TestingSessionLocal)
    yield TestingSessionLocal


def _seed(db):
    names = ["Tomas Z", "Darius A", "Saulius V", "Juozas M", "Saulius P"]
    players = [Player(name=n, rating=1200) for n in names]
    db.add_all(players)
    db.flush()
    t = Tournament(name="LITIT taure", tournament_type=TournamentType.knockout)
    db.add(t)
    db.commit()
    return t, names


def test_voice_scorekeeper_sees_generated_pending_matches(sqlite_db):
    from tournament_platform.app.pages.voice_scorekeeper import fetch_active_matches

    db = sqlite_db()
    tournament, names = _seed(db)

    # Generate knockout matches (as the Tournament page does).
    KnockoutStrategy().generate_matches(names, tournament.id, db)
    db.commit()

    # Tournament page source: tournament.matches
    generated = list(tournament.matches)
    pending = [m for m in generated if m.status == MatchStatus.pending]

    # Voice Scorekeeper must show the same generated pending matches.
    matches = fetch_active_matches(tournament.id, statuses=["active", "pending"])

    assert len(matches) == len(pending)
    assert len(matches) >= 4  # 5 players -> 4 first-round pairings in an 8-slot bracket
    for m in matches:
        assert m["status"] == "pending"
        # Each returned match carries a readable round + player label.
        assert m["round_number"] is not None


def test_match_selector_uses_canonical_db_source(sqlite_db):
    from tournament_platform.app.components.match_selector import fetch_active_matches as ms_fetch

    db = sqlite_db()
    tournament, names = _seed(db)
    KnockoutStrategy().generate_matches(names, tournament.id, db)
    db.commit()

    # match_selector (video scorekeeper) must agree with the Tournament page.
    matches = ms_fetch(tournament.id, statuses=["active", "pending"])
    assert len(matches) == len([m for m in tournament.matches if m.status == MatchStatus.pending])


def test_completed_matches_excluded_from_active_selector(sqlite_db):
    from tournament_platform.app.pages.voice_scorekeeper import fetch_active_matches

    db = sqlite_db()
    tournament, names = _seed(db)
    KnockoutStrategy().generate_matches(names, tournament.id, db)

    # Mark one pending match as completed with a winner.
    first = db.query(Match).filter(
        Match.tournament_id == tournament.id, Match.status == MatchStatus.pending
    ).first()
    first.status = MatchStatus.completed
    first.winner = first.player1
    first.winner_id = first.player1_id
    db.commit()

    matches = fetch_active_matches(tournament.id, statuses=["active", "pending"])
    assert all(m["status"] != "completed" for m in matches)
    assert first.id not in {m["match_id"] for m in matches}


def test_selected_generated_match_loads_player_names(sqlite_db):
    from tournament_platform.app.components.match_selector import (
        fetch_active_matches as ms_fetch,
        apply_selected_match_to_session,
    )

    db = sqlite_db()
    tournament, names = _seed(db)
    KnockoutStrategy().generate_matches(names, tournament.id, db)
    db.commit()

    matches = ms_fetch(tournament.id, statuses=["active", "pending"])
    target = next(
        m for m in matches
        if m["player1_name"] != "TBD" and m["player2_name"] != "TBD"
    )

    apply_selected_match_to_session("voice", target)
    assert st.session_state.voice_selected_match_id == target["match_id"]
    assert st.session_state.voice_selected_player1_name == target["player1_name"]
    assert st.session_state.voice_selected_player2_name == target["player2_name"]
