"""
Tests for the registration service.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, Tournament, Player, TournamentParticipant
from tournament_platform.app.services.registration_service import (
    register_player,
    check_in_player,
    validate_registration_token,
    find_duplicate_candidates_for_registration,
    force_register_player,
    resolve_duplicate,
    sanitize_display_name,
    normalize_name,
    hash_optional,
    get_registration_link,
    generate_registration_token,
    set_registration_token,
    clear_registration_token,
    close_registration,
    get_registration_stats,
    list_pending_duplicates,
    merge_participant_into_player,
    approve_duplicate_as_new,
    dismiss_duplicate_review,
)


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _make_tournament(db, name="Test T", registration_open=True, token="secret123"):
    from tournament_platform.app.services.registration_service import hash_optional
    t = Tournament(name=name, tournament_type="knockout", registration_open=registration_open)
    if token:
        t.public_registration_token_hash = hash_optional(token)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


class TestHelpers:
    def test_sanitize_display_name_strips_control_chars(self):
        assert "\x00" not in sanitize_display_name("abc\x00def")
        assert sanitize_display_name("  abc  ") == "abc"

    def test_sanitize_display_name_caps_length(self):
        name = "a" * 100
        assert len(sanitize_display_name(name)) == 64

    def test_normalize_name_lower_and_strip(self):
        assert normalize_name("J. Smith") == "j smith"
        assert normalize_name("John  Smith") == "john smith"

    def test_hash_optional_none_for_empty(self):
        assert hash_optional("") is None
        assert hash_optional(None) is None

    def test_hash_optional_returns_hex(self):
        h = hash_optional("test@example.com")
        assert h is not None
        assert len(h) == 64

    def test_get_registration_link(self):
        link = get_registration_link("token123", 1)
        assert "token123" in link
        assert "tournament=1" in link
        assert "register=1" in link

    def test_get_registration_link_uses_base_url(self):
        link = get_registration_link("token123", 1, base_url="https://example.com")
        assert link.startswith("https://example.com")


class TestValidateRegistrationToken:
    def test_valid_token(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="mytoken")
            result = validate_registration_token(db, t.id, "mytoken")
            assert result is not None
            assert result.id == t.id
        finally:
            db.close()
            engine.dispose()

    def test_invalid_token(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="mytoken")
            result = validate_registration_token(db, t.id, "wrongtoken")
            assert result is None
        finally:
            db.close()
            engine.dispose()

    def test_missing_token(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="mytoken")
            result = validate_registration_token(db, t.id, "")
            assert result is None
        finally:
            db.close()
            engine.dispose()


class TestRegisterPlayer:
    def test_creates_new_player_and_participant(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            result = register_player(db, t.id, "Alice", source="self_serve")
            assert result["action"] == "created_new"
            assert result["participant"] is not None
            assert result["participant"].checked_in is True
            assert result["participant"].status == "checked_in"
            assert result["participant"].player.name == "Alice"
        finally:
            db.close()
            engine.dispose()

    def test_rejects_when_registration_closed(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok", registration_open=False)
            result = register_player(db, t.id, "Alice")
            assert result["action"] == "duplicate_blocked"
            assert result["participant"] is None
        finally:
            db.close()
            engine.dispose()

    def test_rejects_invalid_tournament(self):
        engine, Session = _make_db()
        db = Session()
        try:
            result = register_player(db, 99999, "Alice")
            assert result["action"] == "duplicate_blocked"
        finally:
            db.close()
            engine.dispose()

    def test_checks_in_existing_participant(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Alice", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Alice",
                checked_in=False,
                status="registered",
            )
            db.add(p1)
            db.commit()

            result = register_player(db, t.id, "Alice")
            assert result["action"] == "checked_in_existing"
            assert result["participant"].checked_in is True
            assert result["participant"].status == "checked_in"
            db.refresh(result["participant"])
        finally:
            db.close()
            engine.dispose()

    def test_auto_check_in_same_name_duplicate(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Alice", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Alice",
                checked_in=True,
                status="checked_in",
            )
            db.add(p1)
            db.commit()

            result = register_player(db, t.id, "alice")
            assert result["action"] == "checked_in_existing"
            assert result["participant"].checked_in is True
        finally:
            db.close()
            engine.dispose()

    def test_idempotent_on_integrity_error(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            result1 = register_player(db, t.id, "Bob")
            assert result1["action"] == "created_new"

            result2 = register_player(db, t.id, "Bob")
            assert result2["action"] == "checked_in_existing"
            assert result2["participant"] is not None
        finally:
            db.close()
            engine.dispose()


class TestForceRegisterPlayer:
    def test_creates_with_pending_review(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            participant = force_register_player(
                db, t.id, "Carol", source="public_self_serve", duplicate_status="pending_review"
            )
            assert participant is not None
            assert participant.status == "pending_review"
            assert participant.duplicate_status == "pending_review"
            assert participant.checked_in is False
            assert participant.bracket_eligible is False
        finally:
            db.close()
            engine.dispose()

    def test_creates_checked_in_without_flag(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            participant = force_register_player(
                db, t.id, "Dave", source="public_self_serve"
            )
            assert participant is not None
            assert participant.status == "registered"
            assert participant.checked_in is True
            assert participant.bracket_eligible is True
        finally:
            db.close()
            engine.dispose()


class TestCheckInPlayer:
    def test_checks_in_existing(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Eve", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Eve",
                checked_in=False,
                status="registered",
            )
            db.add(p1)
            db.commit()

            result = check_in_player(db, t.id, player.id)
            assert result is not None
            assert result.checked_in is True
            assert result.status == "checked_in"
            assert result.checked_in_at is not None
        finally:
            db.close()
            engine.dispose()

    def test_returns_none_when_missing(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            result = check_in_player(db, t.id, 99999)
            assert result is None
        finally:
            db.close()
            engine.dispose()


class TestResolveDuplicate:
    def test_check_in_existing(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Frank", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Frank",
                checked_in=False,
                status="registered",
            )
            db.add(p1)
            db.commit()
            db.refresh(p1)

            result = resolve_duplicate(db, p1.id, target_player_id=player.id, action="check_in_existing")
            assert result is not None
            assert result.checked_in is True
        finally:
            db.close()
            engine.dispose()

    def test_flag_review(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Grace", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Grace",
                checked_in=True,
                status="checked_in",
            )
            db.add(p1)
            db.commit()
            db.refresh(p1)

            result = resolve_duplicate(db, p1.id, action="flag_review")
            assert result is not None
            assert result.duplicate_status == "pending_review"
            assert result.status == "pending_review"
        finally:
            db.close()
            engine.dispose()

    def test_create_new_blocks_when_name_exists(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Hank", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Hank",
                checked_in=True,
                status="checked_in",
            )
            db.add(p1)
            db.commit()
            db.refresh(p1)

            result = resolve_duplicate(db, p1.id, action="create_new")
            assert result is None
        finally:
            db.close()
            engine.dispose()

    def test_create_new_succeeds_with_unique_name(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Hank", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Hank",
                checked_in=True,
                status="checked_in",
            )
            db.add(p1)
            db.commit()
            db.refresh(p1)

            p1.display_name = "Hank New"
            db.add(p1)
            db.commit()
            db.refresh(p1)

            result = resolve_duplicate(db, p1.id, action="create_new")
            assert result is not None
            assert result.duplicate_status == "pending_review"
            assert result.status == "registered"
        finally:
            db.close()
            engine.dispose()


class TestFindDuplicateCandidates:
    def test_exact_current_tournament_duplicate(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            player = Player(name="Ivy", rating=1500)
            db.add(player)
            db.commit()
            db.refresh(player)
            p1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=player.id,
                display_name="Ivy",
            )
            db.add(p1)
            db.commit()

            candidates = find_duplicate_candidates_for_registration(db, t.id, "Ivy")
            assert len(candidates) == 1
            assert candidates[0]["confidence"] == "high"
            assert candidates[0]["player_id"] == player.id
        finally:
            db.close()
            engine.dispose()

    def test_no_duplicate(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, token="tok")
            candidates = find_duplicate_candidates_for_registration(db, t.id, "Jack")
            assert candidates == []
        finally:
            db.close()
            engine.dispose()


class TestGenerateRegistrationToken:
    def test_returns_url_safe_string(self):
        token = generate_registration_token()
        assert isinstance(token, str)
        assert len(token) > 10

    def test_tokens_are_unique(self):
        tokens = {generate_registration_token() for _ in range(100)}
        assert len(tokens) == 100


class TestSetAndClearRegistrationToken:
    def test_set_opens_registration(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=False, token=None)
            token = set_registration_token(db, t.id, raw_token="mynewtoken")
            assert t.public_registration_token_hash == hash_optional("mynewtoken")
            assert t.registration_open is True
            assert token == "mynewtoken"
        finally:
            db.close()
            engine.dispose()

    def test_clear_closes_registration(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            clear_registration_token(db, t.id)
            assert t.public_registration_token_hash is None
            assert t.registration_open is False
        finally:
            db.close()
            engine.dispose()

    def test_set_rotates_token(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="oldtoken")
            new_token = set_registration_token(db, t.id, raw_token="newtoken")
            assert new_token == "newtoken"
            assert validate_registration_token(db, t.id, "oldtoken") is None
            assert validate_registration_token(db, t.id, "newtoken") is not None
        finally:
            db.close()
            engine.dispose()

    def test_set_missing_tournament_raises(self):
        engine, Session = _make_db()
        db = Session()
        try:
            with pytest.raises(ValueError):
                set_registration_token(db, 99999, raw_token="tok")
        finally:
            db.close()
            engine.dispose()


class TestCloseRegistration:
    def test_close_sets_registration_open_false(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            close_registration(db, t.id)
            assert t.registration_open is False
        finally:
            db.close()
            engine.dispose()

    def test_close_preserves_token(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            close_registration(db, t.id)
            assert t.registration_open is False
            assert t.public_registration_token_hash == hash_optional("tok")
        finally:
            db.close()
            engine.dispose()

    def test_close_does_not_delete_registrations(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p = Player(name="Alice", rating=1200)
            db.add(p)
            db.commit()
            tp = TournamentParticipant(
                tournament_id=t.id,
                player_id=p.id,
                display_name="Alice",
                checked_in=True,
            )
            db.add(tp)
            db.commit()

            close_registration(db, t.id)

            participants = db.query(TournamentParticipant).filter(TournamentParticipant.tournament_id == t.id).count()
            assert participants == 1
        finally:
            db.close()
            engine.dispose()

    def test_close_missing_tournament_raises(self):
        engine, Session = _make_db()
        db = Session()
        try:
            with pytest.raises(ValueError):
                close_registration(db, 99999)
        finally:
            db.close()
            engine.dispose()


class TestGetRegistrationStats:
    def test_empty_tournament(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            stats = get_registration_stats(db, t.id)
            assert stats.registered_count == 0
            assert stats.checked_in_count == 0
            assert stats.duplicate_pending_count == 0
            assert stats.bracket_eligible_count == 0
        finally:
            db.close()
            engine.dispose()

    def test_populated_tournament(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p1 = Player(name="Alice", rating=1200)
            p2 = Player(name="Bob", rating=1200)
            db.add_all([p1, p2])
            db.commit()
            tp1 = TournamentParticipant(
                tournament_id=t.id,
                player_id=p1.id,
                display_name="Alice",
                checked_in=True,
                bracket_eligible=True,
            )
            tp2 = TournamentParticipant(
                tournament_id=t.id,
                player_id=p2.id,
                display_name="Bob",
                checked_in=False,
                bracket_eligible=False,
                duplicate_status="pending_review",
            )
            db.add_all([tp1, tp2])
            db.commit()
            stats = get_registration_stats(db, t.id)
            assert stats.registered_count == 2
            assert stats.checked_in_count == 1
            assert stats.duplicate_pending_count == 1
            assert stats.bracket_eligible_count == 1
        finally:
            db.close()
            engine.dispose()


class TestListPendingDuplicates:
    def test_returns_empty_when_none(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            pending = list_pending_duplicates(db, t.id)
            assert pending == []
        finally:
            db.close()
            engine.dispose()

    def test_returns_pending_only(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p = Player(name="Eve", rating=1200)
            db.add(p)
            db.commit()
            tp = TournamentParticipant(
                tournament_id=t.id,
                player_id=p.id,
                display_name="Eve",
                duplicate_status="pending_review",
            )
            db.add(tp)
            db.commit()
            pending = list_pending_duplicates(db, t.id)
            assert len(pending) == 1
            assert pending[0].display_name == "Eve"
        finally:
            db.close()
            engine.dispose()


class TestMergeParticipantIntoPlayer:
    def test_checks_in_existing_player(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p = Player(name="Mallory", rating=1200)
            db.add(p)
            db.commit()
            tp = TournamentParticipant(
                tournament_id=t.id,
                player_id=p.id,
                display_name="Mallory",
                checked_in=False,
            )
            db.add(tp)
            db.commit()
            result = merge_participant_into_player(db, tp.id, p.id)
            assert result is not None
            assert result.checked_in is True
            assert result.status == "checked_in"
        finally:
            db.close()
            engine.dispose()

    def test_returns_none_when_missing(self):
        engine, Session = _make_db()
        db = Session()
        try:
            result = merge_participant_into_player(db, 99999, 99999)
            assert result is None
        finally:
            db.close()
            engine.dispose()


class TestApproveDuplicateAsNew:
    def test_creates_new_player_when_name_is_free(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p = Player(name="Trent", rating=1200)
            db.add(p)
            db.commit()
            tp = TournamentParticipant(
                tournament_id=t.id,
                player_id=p.id,
                display_name="Trent 2",
                duplicate_status="pending_review",
                status="pending_review",
            )
            db.add(tp)
            db.commit()
            result = approve_duplicate_as_new(db, tp.id)
            assert result is not None
            assert result.player_id != p.id
            assert result.duplicate_status == "pending_review"
            assert result.checked_in is False
            assert result.bracket_eligible is False
        finally:
            db.close()
            engine.dispose()

    def test_blocks_new_player_when_name_already_exists(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p = Player(name="Trent", rating=1200)
            db.add(p)
            db.commit()
            tp = TournamentParticipant(
                tournament_id=t.id,
                player_id=p.id,
                display_name="Trent",
                duplicate_status="pending_review",
                status="pending_review",
            )
            db.add(tp)
            db.commit()
            result = approve_duplicate_as_new(db, tp.id)
            assert result is None
        finally:
            db.close()
            engine.dispose()


class TestDismissDuplicateReview:
    def test_clears_duplicate_status(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = _make_tournament(db, registration_open=True, token="tok")
            p = Player(name="Oscar", rating=1200)
            db.add(p)
            db.commit()
            tp = TournamentParticipant(
                tournament_id=t.id,
                player_id=p.id,
                display_name="Oscar",
                duplicate_status="pending_review",
                status="pending_review",
                checked_in=True,
            )
            db.add(tp)
            db.commit()
            result = dismiss_duplicate_review(db, tp.id)
            assert result is not None
            assert result.duplicate_status is None
            assert result.status == "checked_in"
        finally:
            db.close()
            engine.dispose()

    def test_returns_none_when_missing(self):
        engine, Session = _make_db()
        db = Session()
        try:
            result = dismiss_duplicate_review(db, 99999)
            assert result is None
        finally:
            db.close()
            engine.dispose()
