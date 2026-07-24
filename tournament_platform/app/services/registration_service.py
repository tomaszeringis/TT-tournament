"""
Registration service for self-serve tournament sign-up and check-in.

Pure service layer — no Streamlit imports, safe to call from pages, tests,
and (optionally) API endpoints.
"""

import hashlib
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tournament_platform.config import settings
from tournament_platform.models import (
    Player,
    Tournament,
    TournamentParticipant,
    AuditLog,
)
from tournament_platform.services.audit_service import log_audit


logger = logging.getLogger(__name__)

_DISPLAY_NAME_MAX_LENGTH = 64
_FIELD_MAX_LENGTH = 120

_TOKEN_HASH_ALGO = "sha256"
_DUPLICATE_STATUSES = {
    "pending_review",
    "resolved",
}


# ============================================================================
# Helpers
# ============================================================================

def sanitize_display_name(name: str) -> str:
    """Strip whitespace, remove control chars, and cap length."""
    name = name.strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    if len(name) > _DISPLAY_NAME_MAX_LENGTH:
        name = name[:_DISPLAY_NAME_MAX_LENGTH]
    return name


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/diacritics, remove punctuation, collapse whitespace."""
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = normalized.lower()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def hash_optional(value: Optional[str]) -> Optional[str]:
    """Return a SHA-256 hex digest, or None if value is empty."""
    if not value:
        return None
    value = value.strip().lower()
    if not value:
        return None
    return hashlib.new(_TOKEN_HASH_ALGO, value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.utcnow()


# ============================================================================
# Token helpers
# ============================================================================

def get_registration_link(token: str, tournament_id: int, base_url: str = "") -> str:
    """Build the public registration URL for ``token`` and ``tournament_id``."""
    base = (base_url or settings.PUBLIC_BOARD_BASE_URL or "").rstrip("/")
    query = f"?public=1&tournament={tournament_id}&register=1&token={token}"
    if base:
        return f"{base}{query}"
    return query


def validate_registration_token(db: Session, tournament_id: int, token: str) -> Optional[Tournament]:
    """Return the tournament if ``token`` is valid for it, else None."""
    if not token:
        return None
    token_hash = hash_optional(token)
    if not token_hash:
        return None
    tournament = (
        db.query(Tournament)
        .filter(
            Tournament.id == tournament_id,
            Tournament.public_registration_token_hash == token_hash,
        )
        .first()
    )
    return tournament


# ============================================================================
# Duplicate detection
# ============================================================================

def _similarity(a: str, b: str) -> float:
    """Return similarity ratio between two strings using stdlib difflib."""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def find_duplicate_candidates_for_registration(
    db: Session,
    tournament_id: int,
    display_name: str,
    email_hash: Optional[str] = None,
    threshold: float = 0.85,
) -> list[dict]:
    """Return possible duplicate players for a registration attempt.

    Returns a list of dicts with keys:
      player_id, display_name, tournament_name, year, confidence, reason
    """
    candidates = []
    normalized = normalize_name(display_name)

    current_participants = (
        db.query(TournamentParticipant)
        .filter(TournamentParticipant.tournament_id == tournament_id)
        .all()
    )

    exact_current = []
    exact_historical = []
    fuzzy_historical = []

    for p in current_participants:
        if normalize_name(p.display_name) == normalized:
            exact_current.append(p)
        elif email_hash and p.email_hash == email_hash:
            exact_current.append(p)

    if exact_current:
        for p in exact_current:
            candidates.append({
                "player_id": p.player_id,
                "display_name": p.display_name,
                "tournament_name": p.tournament.name if p.tournament else None,
                "year": p.tournament.created_at.year if p.tournament and p.tournament.created_at else None,
                "confidence": "high",
                "reason": "Same name or email already registered in this tournament",
            })
        return candidates

    if email_hash:
        historical_by_email = (
            db.query(TournamentParticipant)
            .filter(TournamentParticipant.email_hash == email_hash)
            .filter(TournamentParticipant.tournament_id != tournament_id)
            .all()
        )
        for p in historical_by_email:
            candidates.append({
                "player_id": p.player_id,
                "display_name": p.display_name,
                "tournament_name": p.tournament.name if p.tournament else None,
                "year": p.tournament.created_at.year if p.tournament and p.tournament.created_at else None,
                "confidence": "high",
                "reason": "Email matches a previous registration",
            })

    historical_players = db.query(Player).all()
    for player in historical_players:
        norm_name = normalize_name(player.name)
        if norm_name == normalized:
            exact_historical.append(player)
        elif _similarity(norm_name, normalized) >= threshold:
            fuzzy_historical.append(player)

    for player in exact_historical:
        candidates.append({
            "player_id": player.id,
            "display_name": player.name,
            "tournament_name": None,
            "year": None,
            "confidence": "high",
            "reason": "Global player name already exists",
        })

    for player in fuzzy_historical:
        candidates.append({
            "player_id": player.id,
            "display_name": player.name,
            "tournament_name": None,
            "year": None,
            "confidence": "medium",
            "reason": "Name is similar to an existing player",
        })

    return candidates


# ============================================================================
# Check-in
# ============================================================================

def check_in_player(
    db: Session,
    tournament_id: int,
    player_id: int,
    source: str = "public_self_serve",
) -> Optional[TournamentParticipant]:
    """Mark a participant as checked in. Return the participant or None."""
    participant = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.player_id == player_id,
        )
        .first()
    )
    if not participant:
        return None

    participant.checked_in = True
    participant.status = "checked_in"
    participant.checked_in_at = _now()
    db.add(participant)

    log_audit(
        db,
        action="check_in",
        entity_type="tournament_participant",
        entity_id=participant.id,
        actor=source,
        payload={"tournament_id": tournament_id, "player_id": player_id},
    )

    try:
        db.commit()
        db.refresh(participant)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to commit check-in: %s", exc, exc_info=True)
        return None

    return participant


# ============================================================================
# Register
# ============================================================================

def register_player(
    db: Session,
    tournament_id: int,
    display_name: str,
    department: Optional[str] = None,
    email: Optional[str] = None,
    employee_id: Optional[str] = None,
    source: str = "self_serve",
) -> dict:
    """Register (and immediately check in) a player for a tournament.

    Returns a dict with keys:
      action: "checked_in_existing" | "created_new" | "duplicate_blocked"
      participant: TournamentParticipant or None
      duplicates: list of duplicate candidates (may be empty)
    """
    display_name = sanitize_display_name(display_name)
    if not display_name:
        return {"action": "duplicate_blocked", "participant": None, "duplicates": []}

    department = (department or "").strip() if department else None
    email_hash = hash_optional(email)
    employee_id_hash = hash_optional(employee_id)

    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return {"action": "duplicate_blocked", "participant": None, "duplicates": []}

    if not tournament.registration_open:
        return {"action": "duplicate_blocked", "participant": None, "duplicates": []}

    duplicates = find_duplicate_candidates_for_registration(
        db, tournament_id, display_name, email_hash=email_hash
    )

    existing_player = None
    if duplicates:
        top = duplicates[0]
        if top["confidence"] == "high":
            existing_player = db.query(Player).filter(Player.id == top["player_id"]).first()

    if existing_player:
        participant = check_in_player(db, tournament_id, existing_player.id, source=source)
        action = "checked_in_existing" if participant else "duplicate_blocked"
        return {
            "action": action,
            "participant": participant,
            "duplicates": duplicates,
        }

    player = Player(
        name=display_name,
        email=email,
        rating=settings.DEFAULT_PLAYER_RATING,
        import_source=source,
        registration_status="approved",
    )
    db.add(player)

    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to flush new player: %s", exc, exc_info=True)
        return {"action": "duplicate_blocked", "participant": None, "duplicates": duplicates}

    participant = TournamentParticipant(
        tournament_id=tournament_id,
        player_id=player.id,
        display_name=display_name,
        department=department,
        email_hash=email_hash,
        employee_id_hash=employee_id_hash,
        checked_in=True,
        checked_in_at=_now(),
        registration_source=source,
        status="checked_in",
        bracket_eligible=True,
    )
    db.add(participant)

    log_audit(
        db,
        action="register",
        entity_type="tournament_participant",
        entity_id=participant.id,
        actor=source,
        payload={
            "tournament_id": tournament_id,
            "player_id": player.id,
            "display_name": display_name,
            "source": source,
        },
    )

    try:
        db.commit()
        db.refresh(participant)
    except IntegrityError:
        db.rollback()
        existing_participant = (
            db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.player_id == player.id,
            )
            .first()
        )
        if existing_participant:
            return {
                "action": "checked_in_existing",
                "participant": existing_participant,
                "duplicates": duplicates,
            }
        return {"action": "duplicate_blocked", "participant": None, "duplicates": duplicates}
    except Exception as exc:
        db.rollback()
        logger.error("Failed to commit registration: %s", exc, exc_info=True)
        return {"action": "duplicate_blocked", "participant": None, "duplicates": duplicates}

    return {
        "action": "created_new",
        "participant": participant,
        "duplicates": duplicates,
    }


def force_register_player(
    db: Session,
    tournament_id: int,
    display_name: str,
    department: Optional[str] = None,
    email: Optional[str] = None,
    employee_id: Optional[str] = None,
    source: str = "public_self_serve",
    duplicate_status: Optional[str] = None,
) -> Optional[TournamentParticipant]:
    """Create a new player and tournament participant without duplicate checks.

    Used when a public user explicitly chooses "This is a new player"
    after duplicate review.
    """
    display_name = sanitize_display_name(display_name)
    if not display_name:
        return None

    department = (department or "").strip() if department else None
    email_hash = hash_optional(email)
    employee_id_hash = hash_optional(employee_id)

    player = Player(
        name=display_name,
        email=email,
        rating=settings.DEFAULT_PLAYER_RATING,
        import_source=source,
        registration_status="approved",
    )
    db.add(player)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.error("Duplicate name blocked in force_register_player: %s", display_name)
        return None
    except Exception as exc:
        db.rollback()
        logger.error("Failed to flush new player in force_register: %s", exc, exc_info=True)
        return None

    status = "pending_review" if duplicate_status == "pending_review" else "registered"
    is_checked_in = status != "pending_review"

    participant = TournamentParticipant(
        tournament_id=tournament_id,
        player_id=player.id,
        display_name=display_name,
        department=department,
        email_hash=email_hash,
        employee_id_hash=employee_id_hash,
        checked_in=is_checked_in,
        checked_in_at=_now() if is_checked_in else None,
        registration_source=source,
        status=status,
        duplicate_status=duplicate_status,
        bracket_eligible=is_checked_in,
    )
    db.add(participant)

    log_audit(
        db,
        action="register",
        entity_type="tournament_participant",
        entity_id=participant.id,
        actor=source,
        payload={
            "tournament_id": tournament_id,
            "player_id": player.id,
            "display_name": display_name,
            "source": source,
            "duplicate_status": duplicate_status,
        },
    )

    try:
        db.commit()
        db.refresh(participant)
    except IntegrityError:
        db.rollback()
        existing_participant = (
            db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.player_id == player.id,
            )
            .first()
        )
        if existing_participant:
            return existing_participant
        return None
    except Exception as exc:
        db.rollback()
        logger.error("Failed to commit force_register: %s", exc, exc_info=True)
        return None

    return participant


# ============================================================================
# Token management
# ============================================================================

import secrets


def generate_registration_token() -> str:
    """Return a new URL-safe random token for a tournament registration link."""
    return secrets.token_urlsafe(16)


def set_registration_token(db: Session, tournament_id: int, raw_token: Optional[str] = None) -> str:
    """Set (or rotate) the public registration token for a tournament.

    Returns the raw token that was stored.
    """
    token = raw_token or generate_registration_token()
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise ValueError(f"Tournament {tournament_id} not found")
    tournament.public_registration_token_hash = hash_optional(token)
    tournament.registration_open = True
    db.add(tournament)
    log_audit(
        db,
        action="set_registration_token",
        entity_type="tournament",
        entity_id=tournament.id,
        actor="operator",
        payload={"tournament_id": tournament_id},
    )
    try:
        db.commit()
        db.refresh(tournament)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to set registration token: %s", exc, exc_info=True)
        raise
    return token


def close_registration(db: Session, tournament_id: int) -> None:
    """Close public registration for a tournament without removing the token.

    Keeps the existing token so registration can be re-enabled later without
    rotating the link. Existing registrations, players, matches, and bracket
    state are left untouched.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise ValueError("Tournament not found")
    tournament.registration_open = False
    db.add(tournament)
    log_audit(
        db,
        action="close_registration",
        entity_type="tournament",
        entity_id=tournament.id,
        actor="operator",
        payload={"tournament_id": tournament_id},
    )
    try:
        db.commit()
        db.refresh(tournament)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to close registration: %s", exc, exc_info=True)
        raise


def clear_registration_token(db: Session, tournament_id: int) -> None:
    """Remove the registration token and close registration for a tournament."""
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return
    tournament.public_registration_token_hash = None
    tournament.registration_open = False
    db.add(tournament)
    log_audit(
        db,
        action="clear_registration_token",
        entity_type="tournament",
        entity_id=tournament.id,
        actor="operator",
        payload={"tournament_id": tournament_id},
    )
    try:
        db.commit()
        db.refresh(tournament)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to clear registration token: %s", exc, exc_info=True)
        raise


# ============================================================================
# Stats helpers
# ============================================================================

@dataclass
class RegistrationStats:
    registered_count: int
    checked_in_count: int
    duplicate_pending_count: int
    bracket_eligible_count: int


def get_registration_stats(db: Session, tournament_id: int) -> RegistrationStats:
    """Return participant counts for a tournament."""
    registered_count = (
        db.query(TournamentParticipant)
        .filter(TournamentParticipant.tournament_id == tournament_id)
        .count()
    )
    checked_in_count = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.checked_in == True,  # noqa: E712
        )
        .count()
    )
    duplicate_pending_count = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.duplicate_status == "pending_review",
        )
        .count()
    )
    bracket_eligible_count = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.checked_in == True,  # noqa: E712
            TournamentParticipant.bracket_eligible == True,  # noqa: E712
        )
        .count()
    )
    return RegistrationStats(
        registered_count=registered_count,
        checked_in_count=checked_in_count,
        duplicate_pending_count=duplicate_pending_count,
        bracket_eligible_count=bracket_eligible_count,
    )


# ============================================================================
# Duplicate review helpers
# ============================================================================

def list_pending_duplicates(db: Session, tournament_id: int) -> list[TournamentParticipant]:
    """Return participants flagged for duplicate review."""
    return (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.duplicate_status == "pending_review",
        )
        .all()
    )


def merge_participant_into_player(db: Session, participant_id: int, target_player_id: int) -> Optional[TournamentParticipant]:
    """Link a participant to an existing player and check them in.

    This is a thin wrapper around resolve_duplicate for operator use.
    """
    return resolve_duplicate(
        db,
        participant_id=participant_id,
        target_player_id=target_player_id,
        action="check_in_existing",
    )


def approve_duplicate_as_new(db: Session, participant_id: int) -> Optional[TournamentParticipant]:
    """Approve a pending duplicate as a new distinct player."""
    return resolve_duplicate(
        db,
        participant_id=participant_id,
        action="create_new",
    )


def dismiss_duplicate_review(db: Session, participant_id: int) -> Optional[TournamentParticipant]:
    """Clear the duplicate review flag for a participant."""
    participant = (
        db.query(TournamentParticipant)
        .filter(TournamentParticipant.id == participant_id)
        .first()
    )
    if not participant:
        return None
    participant.duplicate_status = None
    participant.status = "checked_in" if participant.checked_in else "registered"
    db.add(participant)
    log_audit(
        db,
        action="dismiss_duplicate_review",
        entity_type="tournament_participant",
        entity_id=participant.id,
        actor="operator",
        payload={"tournament_id": participant.tournament_id},
    )
    try:
        db.commit()
        db.refresh(participant)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to dismiss duplicate review: %s", exc, exc_info=True)
        return None
    return participant


# ============================================================================
# Resolve duplicate (operator or public choice)
# ============================================================================

def resolve_duplicate(
    db: Session,
    participant_id: int,
    target_player_id: Optional[int] = None,
    action: str = "check_in_existing",
) -> Optional[TournamentParticipant]:
    """Resolve a duplicate registration based on user choice.

    Supported actions:
      - check_in_existing: mark the existing participant as checked in.
      - create_new: create a new TournamentParticipant (only for low-confidence).
      - flag_review: mark participant as pending_review.
    """
    participant = (
        db.query(TournamentParticipant)
        .filter(TournamentParticipant.id == participant_id)
        .first()
    )
    if not participant:
        return None

    if action == "check_in_existing":
        if target_player_id:
            return check_in_player(db, participant.tournament_id, target_player_id)
        return check_in_player(db, participant.tournament_id, participant.player_id)

    if action == "flag_review":
        participant.duplicate_status = "pending_review"
        participant.status = "pending_review"
        db.add(participant)
        try:
            db.commit()
            db.refresh(participant)
        except Exception as exc:
            db.rollback()
            logger.error("Failed to flag review: %s", exc, exc_info=True)
            return None
        return participant

    if action == "create_new":
        player = Player(
            name=participant.display_name,
            email=None,
            rating=settings.DEFAULT_PLAYER_RATING,
            import_source="self_serve",
            registration_status="approved",
        )
        db.add(player)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            logger.error("Duplicate name blocked in resolve_duplicate create_new: %s", participant.display_name)
            return None
        except Exception as exc:
            db.rollback()
            logger.error("Failed to create new player for duplicate resolution: %s", exc, exc_info=True)
            return None

        new_participant = TournamentParticipant(
            tournament_id=participant.tournament_id,
            player_id=player.id,
            display_name=participant.display_name,
            department=participant.department,
            email_hash=participant.email_hash,
            employee_id_hash=participant.employee_id_hash,
            checked_in=False,
            registration_source="self_serve",
            status="registered",
            duplicate_status="pending_review",
            bracket_eligible=False,
        )
        db.add(new_participant)

        log_audit(
            db,
            action="resolve_duplicate_create_new",
            entity_type="tournament_participant",
            entity_id=new_participant.id,
            actor="public_self_serve",
            payload={"original_participant_id": participant_id},
        )

        try:
            db.commit()
            db.refresh(new_participant)
        except Exception as exc:
            db.rollback()
            logger.error("Failed to commit duplicate resolution: %s", exc, exc_info=True)
            return None
        return new_participant

    return None
