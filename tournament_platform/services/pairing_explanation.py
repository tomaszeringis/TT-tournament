"""
Pairing Explanation — a read-model that explains *why* two players were paired.

All reasons are re-derived from data already persisted in the database (match
results, stage/group membership, seed positions). Nothing here is guessed: if a
reason cannot be computed from available data, it is simply omitted.

This intentionally does NOT persist any new pairing-reason column; it is a
pure, stateless explanation computed at read time.
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from tournament_platform.models import Match, Player, Entry, Stage, Tournament


def _wins_for(db: Session, player_id: Optional[int], tournament_id: Optional[int]) -> int:
    """Count completed matches won by ``player_id`` in the tournament."""
    if not player_id:
        return 0
    q = db.query(Match).filter(
        Match.winner_id == player_id,
        Match.status == "completed",
    )
    if tournament_id is not None:
        q = q.filter(Match.tournament_id == tournament_id)
    return q.count()


def _prior_opponents(db: Session, player_id: Optional[int], tournament_id: Optional[int]) -> set:
    """Set of opponent player ids this player has already faced in the tournament."""
    if not player_id:
        return set()
    q = db.query(Match).filter(
        Match.status == "completed",
        Match.tournament_id == tournament_id if tournament_id is not None else True,
    )
    opponents = set()
    for m in q.all():
        if m.player1_id == player_id and m.player2_id:
            opponents.add(m.player2_id)
        elif m.player2_id == player_id and m.player1_id:
            opponents.add(m.player1_id)
    return opponents


def _seed_positions(db: Session, tournament_id: Optional[int], p1_id, p2_id):
    """Return (seed1, seed2) from Entry seed_position, or (None, None)."""
    seeds = {}
    q = db.query(Entry)
    if tournament_id is not None:
        q = q.filter(Entry.event_id == tournament_id)
    for e in q.all():
        # Map by player1_id (singles). Seed lookup best-effort.
        if e.player1_id in (p1_id, p2_id):
            seeds[e.player1_id] = e.seed_position
    return seeds.get(p1_id), seeds.get(p2_id)


def _stage_type_of(match: Match) -> Optional[str]:
    """Best-effort determination of the pairing format for this match."""
    if match.stage and match.stage.stage_type:
        return match.stage.stage_type
    if match.tournament and match.tournament.tournament_type:
        return match.tournament.tournament_type.value
    return None


def explain_pairing(match: Match, db: Session) -> List[str]:
    """Return a list of human-readable, computable pairing-reason strings.

    Reasons are only emitted when they can be derived from existing data. No
    reason is ever fabricated.
    """
    reasons: List[str] = []

    p1_id = match.player1_id
    p2_id = match.player2_id
    tournament_id = match.tournament_id
    stage_type = _stage_type_of(match)

    # Bye detection: an assigned match with no second player.
    if not match.player2 or str(match.player2).strip().upper() == "BYE":
        reasons.append("Bye — opponent not assigned")
        return reasons

    # Swiss: record proximity + rematch avoidance.
    if stage_type == "swiss":
        w1 = _wins_for(db, p1_id, tournament_id)
        w2 = _wins_for(db, p2_id, tournament_id)
        if abs(w1 - w2) <= 1:
            reasons.append(f"Paired by similar record (wins {w1} vs {w2})")
        else:
            reasons.append(f"Record difference of {abs(w1 - w2)} win(s)")
        prior = _prior_opponents(db, p1_id, tournament_id)
        if p2_id not in prior:
            reasons.append("Rematch avoided — these players have not met before")
        return reasons

    # Groups → Knockout / Knockout: seed positions and group membership.
    if stage_type in ("knockout", "group"):
        if stage_type == "group" and match.stage:
            reasons.append(f"Group stage match ({match.stage.name or 'group'})")
        s1, s2 = _seed_positions(db, tournament_id, p1_id, p2_id)
        if s1 and s2:
            reasons.append(f"Seeded match (seed {s1} vs {s2})")
        elif s1 or s2:
            seed = s1 or s2
            reasons.append(f"Seeded match (seed {seed})")
        return reasons

    # Unknown format: omit reasons rather than guess.
    return reasons


def get_match_explanation(match_id: int, db: Session) -> List[str]:
    """Convenience wrapper: load a match by id and explain its pairing."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return []
    return explain_pairing(match, db)
