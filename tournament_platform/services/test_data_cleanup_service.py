"""
Test Data Cleanup Service

Provides safe, transactional cleanup of test/demo/generated data.
All operations require explicit confirmation and show a preview first.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from tournament_platform.models import (
    Player,
    Tournament,
    Match,
    Announcement,
    AuditLog,
    VenueTable,
    RatingHistory,
    MatchStatus,
)
from tournament_platform.services.audit_service import log_audit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

_TOURNAMENT_NAME_RE = re.compile(
    r"test|demo|sample|quick\s*win|seed",
    re.IGNORECASE,
)
_TOURNAMENT_DESC_RE = re.compile(
    r"\[generated-test-data\]|generated\s+test\s+data|demo\s+data",
    re.IGNORECASE,
)

_PLAYER_NAME_RE = re.compile(
    r"test\s+player|demo\s+player|sample\s+player|^player\s+\d+$",
    re.IGNORECASE,
)
_PLAYER_EMAIL_DOMAINS = {"example.com", "test.local", "demo.local", "invalid.test"}

_VENUE_NAME_RE = re.compile(r"demo\s+table|test\s+table", re.IGNORECASE)
_VENUE_NOTES_RE = re.compile(r"\[generated-test-data\]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_test_tournament(t: Tournament) -> bool:
    name = t.name or ""
    desc = t.description or ""
    return bool(_TOURNAMENT_NAME_RE.search(name)) or bool(_TOURNAMENT_DESC_RE.search(desc))


def _is_test_player_name(name: str) -> bool:
    return bool(_PLAYER_NAME_RE.search(name))


def _is_test_player_email(email: str) -> bool:
    if not email:
        return False
    domain = email.split("@")[-1].lower()
    return domain in _PLAYER_EMAIL_DOMAINS


def _is_test_venue(table: VenueTable) -> bool:
    name = table.name or ""
    notes = table.notes or ""
    return bool(_VENUE_NAME_RE.search(name)) or bool(_VENUE_NOTES_RE.search(notes))


def _get_test_tournament_ids(db: Session) -> Set[int]:
    return {t.id for t in db.query(Tournament).all() if _is_test_tournament(t)}


def _player_is_exclusively_in_test(
    db: Session, player_id: int, test_tournament_ids: Set[int]
) -> bool:
    """
    Return True only if the player appears in matches that are either
    in test tournaments or have no tournament (ambiguous -> safe skip).
    If the player appears in any non-test tournament match, return False.
    """
    matches = db.query(Match).filter(
        or_(
            Match.player1_id == player_id,
            Match.player2_id == player_id,
            Match.winner_id == player_id,
        )
    ).all()

    for m in matches:
        if m.tournament_id is None:
            # Ambiguous – do not delete
            return False
        if m.tournament_id not in test_tournament_ids:
            return False
    return True


def _venue_is_safe_to_delete(db: Session, table: VenueTable, test_tournament_ids: Set[int]) -> bool:
    """
    Return True if the venue table is not referenced by any non-test match
    (via the location string field). Matches with no tournament are treated
    as ambiguous / non-test for safety.
    """
    non_test_matches = (
        db.query(Match)
        .filter(
            Match.location == table.name,
            or_(
                Match.tournament_id.is_(None),
                Match.tournament_id.notin_(test_tournament_ids),
            ),
        )
        .count()
    )
    return non_test_matches == 0


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_test_data_cleanup(db: Session) -> Dict[str, Any]:
    """
    Return a structured preview of records that would be deleted.
    """
    test_tournament_ids = _get_test_tournament_ids(db)

    # --- tournaments ---
    test_tournaments = (
        db.query(Tournament)
        .filter(Tournament.id.in_(test_tournament_ids))
        .order_by(Tournament.id)
        .all()
    )

    # --- matches in test tournaments ---
    test_matches = (
        db.query(Match)
        .filter(Match.tournament_id.in_(test_tournament_ids))
        .order_by(Match.id)
        .all()
    )
    test_match_ids: Set[int] = {m.id for m in test_matches}

    # --- announcements linked to test tournaments or test matches ---
    test_announcements = (
        db.query(Announcement)
        .filter(
            or_(
                Announcement.tournament_id.in_(test_tournament_ids),
                Announcement.match_id.in_(test_match_ids),
            )
        )
        .order_by(Announcement.id)
        .all()
    )

    # --- audit logs related to test entities ---
    test_audit_logs: List[AuditLog] = []
    for etype, eids in [
        ("tournament", test_tournament_ids),
        ("match", test_match_ids),
        ("announcement", {a.id for a in test_announcements}),
    ]:
        if eids:
            logs = (
                db.query(AuditLog)
                .filter(
                    AuditLog.entity_type == etype,
                    AuditLog.entity_id.in_(eids),
                )
                .order_by(AuditLog.id)
                .all()
            )
            test_audit_logs.extend(logs)

    # --- players: test name/email AND exclusively in test tournaments ---
    all_players = db.query(Player).order_by(Player.id).all()
    test_players: List[Player] = []
    for p in all_players:
        name_ok = _is_test_player_name(p.name or "")
        email_ok = _is_test_player_email(p.email or "")
        if (name_ok or email_ok) and _player_is_exclusively_in_test(
            db, p.id, test_tournament_ids
        ):
            test_players.append(p)
    test_player_ids: Set[int] = {p.id for p in test_players}

    # --- rating history for test players ---
    test_rating_history = (
        db.query(RatingHistory)
        .filter(RatingHistory.player_id.in_(test_player_ids))
        .order_by(RatingHistory.id)
        .all()
    )

    # --- venue tables: clearly test AND safe to delete ---
    all_venue_tables = db.query(VenueTable).order_by(VenueTable.id).all()
    test_venue_tables: List[VenueTable] = [
        v
        for v in all_venue_tables
        if _is_test_venue(v) and _venue_is_safe_to_delete(db, v, test_tournament_ids)
    ]

    return {
        "test_tournaments": {
            "count": len(test_tournaments),
            "samples": [
                {"id": t.id, "name": t.name} for t in test_tournaments[:10]
            ],
        },
        "test_matches": {
            "count": len(test_matches),
            "samples": [
                {
                    "id": m.id,
                    "tournament_id": m.tournament_id,
                    "player1": m.player1,
                    "player2": m.player2,
                }
                for m in test_matches[:10]
            ],
        },
        "test_announcements": {
            "count": len(test_announcements),
            "samples": [
                {"id": a.id, "message": (a.message or "")[:60]}
                for a in test_announcements[:10]
            ],
        },
        "test_audit_logs": {
            "count": len(test_audit_logs),
            "samples": [
                {
                    "id": l.id,
                    "action": l.action,
                    "entity_type": l.entity_type,
                    "entity_id": l.entity_id,
                }
                for l in test_audit_logs[:10]
            ],
        },
        "test_players": {
            "count": len(test_players),
            "samples": [
                {"id": p.id, "name": p.name, "email": p.email}
                for p in test_players[:10]
            ],
        },
        "test_venue_tables": {
            "count": len(test_venue_tables),
            "samples": [
                {"id": v.id, "name": v.name} for v in test_venue_tables[:10]
            ],
        },
        "test_rating_history": {
            "count": len(test_rating_history),
            "samples": [
                {"id": r.id, "player_id": r.player_id}
                for r in test_rating_history[:10]
            ],
        },
    }


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_test_data(
    db: Session,
    confirmed: bool = False,
    confirmation_text: str = "",
) -> Dict[str, Any]:
    """
    Delete all identified test/demo/generated data inside a single transaction.

    Safety checks:
    - confirmed must be True
    - confirmation_text must equal "DELETE TEST DATA"
    - All deletions happen in one transaction; rolled back on any error.
    """
    if not confirmed:
        raise ValueError(
            "Cleanup aborted: confirmed=False. "
            "Set confirmed=True and provide confirmation_text='DELETE TEST DATA'."
        )
    if confirmation_text != "DELETE TEST DATA":
        raise ValueError(
            f"Cleanup aborted: confirmation_text must be exactly 'DELETE TEST DATA'. "
            f"Got: {confirmation_text!r}"
        )

    # Recalculate preview inside the same transaction
    preview = preview_test_data_cleanup(db)

    # Collect all IDs from preview (preview only returns samples, so we must
    # re-query to get the full sets for deletion)
    test_tournament_ids: Set[int] = _get_test_tournament_ids(db)
    test_tournaments = (
        db.query(Tournament)
        .filter(Tournament.id.in_(test_tournament_ids))
        .order_by(Tournament.id)
        .all()
    )
    test_tournament_ids = {t.id for t in test_tournaments}

    test_matches = (
        db.query(Match)
        .filter(Match.tournament_id.in_(test_tournament_ids))
        .order_by(Match.id)
        .all()
    )
    test_match_ids: Set[int] = {m.id for m in test_matches}

    test_announcements = (
        db.query(Announcement)
        .filter(
            or_(
                Announcement.tournament_id.in_(test_tournament_ids),
                Announcement.match_id.in_(test_match_ids),
            )
        )
        .order_by(Announcement.id)
        .all()
    )

    all_players = db.query(Player).order_by(Player.id).all()
    test_players: List[Player] = []
    for p in all_players:
        name_ok = _is_test_player_name(p.name or "")
        email_ok = _is_test_player_email(p.email or "")
        if (name_ok or email_ok) and _player_is_exclusively_in_test(
            db, p.id, test_tournament_ids
        ):
            test_players.append(p)
    test_player_ids: Set[int] = {p.id for p in test_players}

    test_rating_history = (
        db.query(RatingHistory)
        .filter(RatingHistory.player_id.in_(test_player_ids))
        .order_by(RatingHistory.id)
        .all()
    )

    all_venue_tables = db.query(VenueTable).order_by(VenueTable.id).all()
    test_venue_tables: List[VenueTable] = [
        v
        for v in all_venue_tables
        if _is_test_venue(v) and _venue_is_safe_to_delete(db, v, test_tournament_ids)
    ]

    # Audit logs for all deleted entity types
    test_audit_logs: List[AuditLog] = []
    for etype, eids in [
        ("tournament", test_tournament_ids),
        ("match", test_match_ids),
        ("announcement", {a.id for a in test_announcements}),
        ("player", test_player_ids),
        ("venue_table", {v.id for v in test_venue_tables}),
    ]:
        if eids:
            logs = (
                db.query(AuditLog)
                .filter(
                    AuditLog.entity_type == etype,
                    AuditLog.entity_id.in_(eids),
                )
                .order_by(AuditLog.id)
                .all()
            )
            test_audit_logs.extend(logs)

    deleted_counts = {
        "tournaments": 0,
        "matches": 0,
        "announcements": 0,
        "audit_logs": 0,
        "players": 0,
        "venue_tables": 0,
        "rating_history": 0,
    }

    try:
        # 1. Delete announcements (children of matches/tournaments)
        for a in test_announcements:
            db.delete(a)
            deleted_counts["announcements"] += 1

        # 2. Delete matches (children of tournaments)
        for m in test_matches:
            db.delete(m)
            deleted_counts["matches"] += 1

        # 3. Delete rating history (children of players)
        for r in test_rating_history:
            db.delete(r)
            deleted_counts["rating_history"] += 1

        # 4. Delete test tournaments
        for t in test_tournaments:
            db.delete(t)
            deleted_counts["tournaments"] += 1

        # 5. Delete test players
        for p in test_players:
            db.delete(p)
            deleted_counts["players"] += 1

        # 6. Delete test venue tables
        for v in test_venue_tables:
            db.delete(v)
            deleted_counts["venue_tables"] += 1

        # 7. Delete audit logs
        for l in test_audit_logs:
            db.delete(l)
            deleted_counts["audit_logs"] += 1

        db.commit()

        # Write audit log for the cleanup action itself
        log_audit(
            db,
            action="cleanup_test_data",
            entity_type="system",
            actor="admin",
            payload={
                "deleted_counts": deleted_counts,
                "preview_summary": {
                    k: v["count"] for k, v in preview.items()
                },
            },
        )

        return {
            "status": "success",
            "deleted_counts": deleted_counts,
            "preview": preview,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Test data cleanup failed, rolled back: {e}", exc_info=True)
        raise
