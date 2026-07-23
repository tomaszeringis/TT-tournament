"""
Tests for the public board read-model service.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, Tournament, Player, Match, MatchStatus
from tournament_platform.services.tournament_read_models import list_tournaments, get_public_schedule
from tournament_platform.app.services.public_board_service import get_public_board_state, build_public_board_url, make_qr_png_bytes, PublicBoardState, BoardFreshness, compute_freshness


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _seed_tournament_and_players(db):
    t = Tournament(name="Test T", tournament_type="knockout")
    db.add(t)
    db.commit()
    db.refresh(t)

    p1 = Player(name="Alice", rating=1500)
    p2 = Player(name="Bob", rating=1400)
    p3 = Player(name="Carol", rating=1300)
    db.add_all([p1, p2, p3])
    db.commit()

    return t, p1, p2, p3


def _seed_match(db, tournament, player1, player2, status, call_status, scheduled_time=None, score=None, winner=None, round_number=1, location="1", game_scores=None, operator_note=None):
    m = Match(
        tournament_id=tournament.id,
        player1=player1.name,
        player2=player2.name,
        player1_id=player1.id,
        player2_id=player2.id,
        status=status,
        call_status=call_status,
        scheduled_time=scheduled_time,
        score=score,
        winner=winner,
        round_number=round_number,
        location=location,
        game_scores=game_scores,
        operator_note=operator_note,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class TestPublicBoardState:
    def test_no_tournaments(self):
        engine, Session = _make_db()
        db = Session()
        try:
            state = get_public_board_state(db, None)
            assert state.tournament_name == "No Tournament"
            assert state.tournament_id == 0
            assert state.live_matches == []
            assert state.completed_matches == []
        finally:
            db.close()
            engine.dispose()

    def test_first_tournament_when_none_selected(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, p3 = _seed_tournament_and_players(db)
            _seed_match(db, t, p1, p2, MatchStatus.pending, "not_called")
            _seed_match(db, t, p3, p1, MatchStatus.completed, "completed", score="11-9", winner=p1.name)

            state = get_public_board_state(db, None)
            assert state.tournament_id == t.id
            assert state.tournament_name == "Test T"
        finally:
            db.close()
            engine.dispose()

    def test_filters_by_tournament_id(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t1, p1, p2, p3 = _seed_tournament_and_players(db)
            _seed_match(db, t1, p1, p2, MatchStatus.completed, "completed", score="11-9", winner=p1.name)

            t2 = Tournament(name="Other", tournament_type="knockout")
            db.add(t2)
            db.commit()
            db.refresh(t2)

            op1 = Player(name="X", rating=1000)
            op2 = Player(name="Y", rating=1100)
            db.add_all([op1, op2])
            db.commit()
            _seed_match(db, t2, op1, op2, MatchStatus.completed, "completed", score="11-5", winner=op1.name)

            state = get_public_board_state(db, t1.id)
            assert state.tournament_id == t1.id
            assert len(state.all_matches) == 1
            assert state.all_matches[0]["player1"] == "Alice"
        finally:
            db.close()
            engine.dispose()

    def test_falls_back_to_first_when_invalid_id(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            _seed_match(db, t, p1, p2, MatchStatus.completed, "completed", score="11-9", winner=p1.name)

            state = get_public_board_state(db, 99999)
            assert state.tournament_id == t.id
            assert len(state.all_matches) == 1
        finally:
            db.close()
            engine.dispose()

    def test_categorizes_matches(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, p3 = _seed_tournament_and_players(db)
            m_active = _seed_match(db, t, p1, p2, MatchStatus.active, "active")
            m_called = _seed_match(db, t, p2, p3, MatchStatus.pending, "called")
            m_next = _seed_match(db, t, p3, p1, MatchStatus.pending, "queued")
            m_delayed = _seed_match(db, t, p1, p3, MatchStatus.pending, "delayed")
            m_recent = _seed_match(db, t, p2, p3, MatchStatus.completed, "completed", score="11-7", winner=p2.name)

            state = get_public_board_state(db, t.id)

            assert len(state.live_matches) == 1
            assert state.live_matches[0]["id"] == m_active.id

            assert len(state.called_matches) == 1
            assert state.called_matches[0]["id"] == m_called.id

            assert state.next_match is not None
            assert state.next_match["id"] == m_next.id

            assert len(state.coming_up) == 0

            assert len(state.delayed_matches) == 1
            assert state.delayed_matches[0]["id"] == m_delayed.id

            assert len(state.recent) == 1
            assert state.recent[0]["id"] == m_recent.id
        finally:
            db.close()
            engine.dispose()

    def test_status_active_includes_in_live_even_if_call_status_not_active(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            m_voice_active = _seed_match(db, t, p1, p2, MatchStatus.active, "not_called")

            state = get_public_board_state(db, t.id)

            assert len(state.live_matches) == 1
            assert state.live_matches[0]["id"] == m_voice_active.id
            assert state.live_matches[0]["status"] == "active"
            assert state.live_matches[0]["call_status"] == "not_called"
        finally:
            db.close()
            engine.dispose()


class TestClassifyPublicBoardMatch:
    def test_active_status_goes_to_now(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "active", "call_status": "not_called"}) == "now"

    def test_active_call_status_goes_to_now(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "pending", "call_status": "active"}) == "now"

    def test_called_goes_to_coming_up(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "pending", "call_status": "called"}) == "coming_up"

    def test_pending_goes_to_coming_up(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "pending", "call_status": "not_called"}) == "coming_up"

    def test_delayed_goes_to_delayed(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "pending", "call_status": "delayed"}) == "delayed"

    def test_completed_goes_to_recent(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "completed", "call_status": "completed"}) == "recent"

    def test_in_progress_goes_to_now(self):
        from tournament_platform.app.services.public_board_service import classify_public_board_match

        assert classify_public_board_match({"status": "in_progress", "call_status": "not_called"}) == "now"

    def test_recent_sorted_descending(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, p3 = _seed_tournament_and_players(db)
            m1 = _seed_match(db, t, p1, p2, MatchStatus.completed, "completed", score="11-7", winner=p1.name)
            m2 = _seed_match(db, t, p2, p3, MatchStatus.completed, "completed", score="11-5", winner=p2.name)

            state = get_public_board_state(db, t.id)

            # Should contain both matches
            assert len(state.recent) == 2
            # They should be sorted descending by scheduled_time (both None here, so stable order by id desc)
            recent_ids = [m["id"] for m in state.recent]
            assert recent_ids == [m2.id, m1.id]
        finally:
            db.close()
            engine.dispose()

    def test_standings_populated(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, p3 = _seed_tournament_and_players(db)
            _seed_match(db, t, p1, p2, MatchStatus.completed, "completed", score="11-9", winner=p1.name)
            _seed_match(db, t, p2, p3, MatchStatus.completed, "completed", score="11-8", winner=p2.name)

            state = get_public_board_state(db, t.id)

            assert len(state.standings) == 3
            names = [s["name"] for s in state.standings]
            assert "Alice" in names
            assert "Bob" in names
            assert "Carol" in names
        finally:
            db.close()
            engine.dispose()


class TestBuildPublicBoardUrl:
    def test_includes_public_and_tournament(self):
        url = build_public_board_url("https://example.com", 1)
        assert url.startswith("https://example.com?public=1&tournament=1")

    def test_kiosk_param(self):
        url = build_public_board_url("https://example.com", 1, kiosk=True)
        assert "kiosk=1" in url
        assert "public=1" in url

    def test_empty_base_returns_relative(self):
        url = build_public_board_url("", 1)
        assert url == "?public=1&tournament=1"

    def test_base_url_trailing_slash_stripped(self):
        url = build_public_board_url("https://example.com/", 1)
        assert url.startswith("https://example.com?")
        assert not url.startswith("https://example.com//")


class TestMakeQrPngBytes:
    def test_returns_non_empty_png_bytes(self):
        png = make_qr_png_bytes("https://example.com/?public=1&tournament=1", scale=4)
        assert isinstance(png, bytes)
        assert len(png) > 100

    def test_png_starts_with_png_signature(self):
        png = make_qr_png_bytes("https://example.com/?public=1&tournament=1", scale=4)
        assert png[:4] == b"\x89PNG"

    def test_different_urls_produce_different_qr(self):
        png1 = make_qr_png_bytes("https://example.com/?public=1&tournament=1", scale=4)
        png2 = make_qr_png_bytes("https://example.com/?public=1&tournament=2", scale=4)
        assert png1 != png2


class TestBoardFreshness:
    def test_unknown_when_no_timestamp(self):
        f = compute_freshness(None, stale_after_seconds=60)
        assert f.state == "unknown"
        assert f.message == "No data loaded yet"
        assert f.age_seconds is None
        assert f.loaded_at is None

    def test_fresh_when_recent(self):
        from datetime import datetime, timezone, timedelta

        loaded = datetime.now(timezone.utc) - timedelta(seconds=5)
        f = compute_freshness(loaded, stale_after_seconds=60)
        assert f.state == "fresh"
        assert f.age_seconds >= 5
        assert "Updated" in f.message

    def test_stale_when_old(self):
        from datetime import datetime, timezone, timedelta

        loaded = datetime.now(timezone.utc) - timedelta(seconds=120)
        f = compute_freshness(loaded, stale_after_seconds=60)
        assert f.state == "stale"
        assert f.age_seconds >= 120
        assert "stale" in f.message


class TestPublicSchedule:
    def test_returns_game_scores_when_present(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            _seed_match(db, t, p1, p2, MatchStatus.completed, "completed", score="3-1", winner=p1.name,
                       game_scores="11-9, 11-7, 9-11, 11-2")

            matches = get_public_schedule(db, tournament_id=t.id)
            assert len(matches) == 1
            assert matches[0]["game_scores"] == ["11-9", "11-7", "9-11", "11-2"]
        finally:
            db.close()
            engine.dispose()

    def test_returns_none_game_scores_when_empty(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            _seed_match(db, t, p1, p2, MatchStatus.pending, "not_called")

            matches = get_public_schedule(db, tournament_id=t.id)
            assert len(matches) == 1
            assert matches[0]["game_scores"] is None
        finally:
            db.close()
            engine.dispose()
