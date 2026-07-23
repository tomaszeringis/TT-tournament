"""
Public Board Service — Safe read-model for the public tournament board.

Pure database helpers; no Streamlit imports. Returns only public-safe fields.
"""

import io
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional, List, Dict, Any

from sqlalchemy.orm import Session

from tournament_platform.models import Tournament, TournamentParticipant
from tournament_platform.services.tournament_read_models import list_tournaments, get_public_schedule
from tournament_platform.services.standings_service import get_standings


@dataclass
class PublicBoardState:
    tournament_name: str
    tournament_id: int
    registration_open: bool
    registered_count: int
    checked_in_count: int
    duplicate_pending_count: int
    bracket_eligible_count: int
    live_matches: List[Dict[str, Any]]
    called_matches: List[Dict[str, Any]]
    next_match: Optional[Dict[str, Any]]
    coming_up: List[Dict[str, Any]]
    delayed_matches: List[Dict[str, Any]]
    completed_matches: List[Dict[str, Any]]
    recent: List[Dict[str, Any]]
    all_matches: List[Dict[str, Any]]
    standings: List[Dict[str, Any]]


def build_public_board_url(base_url: str, tournament_id: int, kiosk: bool = False) -> str:
    """Build a full public board URL.

    Always includes ``public=1`` so the link bypasses auth.
    """
    params = {"public": "1", "tournament": str(tournament_id)}
    if kiosk:
        params["kiosk"] = "1"
    query = urllib.parse.urlencode(params)
    if base_url:
        return f"{base_url.rstrip('/')}?{query}"
    return f"?{query}"


def make_qr_png_bytes(url: str, scale: int = 6) -> bytes:
    """Return PNG bytes for a QR code encoding ``url``.

    Uses a white background and black modules so it is visible on dark themes.
    """
    import segno

    qr = segno.make(url)
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale, border=2, dark="black", light="white")
    return buffer.getvalue()


def classify_public_board_match(match: Dict[str, Any]) -> str:
    """Classify a match into a Public Board lane.

    Returns one of:
        "now"        — active/in_progress/live match
        "coming_up"  — pending, queued, not_called, or called-but-not-active
        "delayed"    — delayed or attention-needed
        "recent"     — completed or cancelled
    """
    status = (match.get("status") or "pending").lower()
    call_status = (match.get("call_status") or "not_called").lower()

    if status in ("completed", "cancelled"):
        return "recent"
    if call_status == "delayed":
        return "delayed"
    if status in ("active", "in_progress", "live") or call_status == "active":
        return "now"
    if call_status == "called":
        return "coming_up"
    if call_status in ("queued", "pending", "not_called"):
        return "coming_up"

    return "coming_up"


def get_public_board_state(db: Session, tournament_id: Optional[int]) -> PublicBoardState:
    """
    Build the public board state for a tournament.

    Falls back to the first available tournament when ``tournament_id`` is None.

    Returns only public-safe fields. No secrets, no webhook status, no diagnostics.
    """
    tournaments = list_tournaments(db)

    if not tournaments:
        return PublicBoardState(
            tournament_name="No Tournament",
            tournament_id=0,
            registration_open=False,
            registered_count=0,
            checked_in_count=0,
            duplicate_pending_count=0,
            bracket_eligible_count=0,
            live_matches=[],
            called_matches=[],
            next_match=None,
            coming_up=[],
            delayed_matches=[],
            completed_matches=[],
            recent=[],
            all_matches=[],
            standings=[],
        )

    target_tournament = None
    if tournament_id is not None:
        for t in tournaments:
            if t["id"] == tournament_id:
                target_tournament = t
                break

    if target_tournament is None:
        target_tournament = tournaments[0]

    target_id = target_tournament["id"]
    target_name = target_tournament["name"]

    tournament = db.query(Tournament).filter(Tournament.id == target_id).first()
    registration_open = bool(tournament.registration_open) if tournament else False

    registered_count = (
        db.query(TournamentParticipant)
        .filter(TournamentParticipant.tournament_id == target_id)
        .count()
    )
    checked_in_count = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == target_id,
            TournamentParticipant.checked_in == True,  # noqa: E712
        )
        .count()
    )
    duplicate_pending_count = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == target_id,
            TournamentParticipant.duplicate_status == "pending_review",
        )
        .count()
    )
    bracket_eligible_count = (
        db.query(TournamentParticipant)
        .filter(
            TournamentParticipant.tournament_id == target_id,
            TournamentParticipant.checked_in == True,  # noqa: E712
            TournamentParticipant.bracket_eligible == True,  # noqa: E712
        )
        .count()
    )

    matches = get_public_schedule(db, tournament_id=target_id, limit=100)

    lanes = {"now": [], "coming_up": [], "delayed": [], "recent": []}
    for m in matches:
        lane = classify_public_board_match(m)
        lanes[lane].append(m)

    live = lanes["now"]
    called = [m for m in lanes["coming_up"] if m.get("call_status") == "called"]
    next_candidates = [m for m in lanes["coming_up"] if m.get("call_status") != "called"]
    next_match = next_candidates[0] if next_candidates else None
    coming_up = next_candidates[1:4] if len(next_candidates) > 1 else []
    delayed = lanes["delayed"]
    completed = [m for m in lanes["recent"] if m.get("status") == "completed"]
    recent = sorted(completed, key=lambda m: m.get("scheduled_time") or "", reverse=True)[:5]

    standings = get_standings(db, tournament_id=target_id)

    return PublicBoardState(
        tournament_name=target_name,
        tournament_id=target_id,
        registration_open=registration_open,
        registered_count=registered_count,
        checked_in_count=checked_in_count,
        duplicate_pending_count=duplicate_pending_count,
        bracket_eligible_count=bracket_eligible_count,
        live_matches=live,
        called_matches=called,
        next_match=next_match,
        coming_up=coming_up,
        delayed_matches=delayed,
        completed_matches=completed,
        recent=recent,
        all_matches=matches,
        standings=standings,
    )


@dataclass
class BoardFreshness:
    loaded_at: datetime | None
    age_seconds: int | None
    stale_after_seconds: int
    state: Literal["fresh", "stale", "unknown", "error"]
    message: str


def compute_freshness(loaded_at: datetime | None, stale_after_seconds: int = 60) -> BoardFreshness:
    """Compute freshness state from a load timestamp."""
    if loaded_at is None:
        return BoardFreshness(
            loaded_at=None,
            age_seconds=None,
            stale_after_seconds=stale_after_seconds,
            state="unknown",
            message="No data loaded yet",
        )

    age = int((datetime.now(timezone.utc) - loaded_at).total_seconds())

    if age >= stale_after_seconds:
        state = "stale"
        message = f"⚠ May be stale ({age}s ago)"
    else:
        state = "fresh"
        message = f"Updated {age}s ago"

    return BoardFreshness(
        loaded_at=loaded_at,
        age_seconds=age,
        stale_after_seconds=stale_after_seconds,
        state=state,
        message=message,
    )
