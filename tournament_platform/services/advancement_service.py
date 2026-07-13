"""
Advancement Service - Groups to Knockout advancement workflow.

Calculates group standings and advances qualifiers into the knockout stage,
replacing TBD placeholders with actual players.
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Stage, Group, Entry, Tournament


def calculate_group_standings(
    db: Session,
    group_id: int,
) -> List[Dict[str, Any]]:
    """
    Calculate standings for a single group based on completed matches.

    Returns:
        List of entry records sorted by: wins desc, matches_played asc, name asc
    """
    entries = db.query(Entry).filter(Entry.group_id == group_id).all()
    group = db.query(Group).filter(Group.id == group_id).first()
    stage_id = group.stage_id if group else None
    matches = db.query(Match).filter(Match.stage_id == stage_id).all() if stage_id else []

    stats = {}
    for entry in entries:
        player_id = entry.player1_id
        player_name = None
        if entry.player1_rel:
            player_name = entry.player1_rel.name
        elif entry.player1:
            player_name = entry.player1

        stats[player_id] = {
            "entry_id": entry.id,
            "player_id": player_id,
            "name": player_name or f"Player {player_id}",
            "wins": 0,
            "losses": 0,
            "matches_played": 0,
        }

    for m in matches:
        if m.status != MatchStatus.completed or not m.score or not m.winner_id:
            continue
        p1 = m.player1_id
        p2 = m.player2_id
        if p1 in stats:
            stats[p1]["matches_played"] += 1
            if m.winner_id == p1:
                stats[p1]["wins"] += 1
            else:
                stats[p1]["losses"] += 1
        if p2 in stats:
            stats[p2]["matches_played"] += 1
            if m.winner_id == p2:
                stats[p2]["wins"] += 1
            else:
                stats[p2]["losses"] += 1

    standings = sorted(
        stats.values(),
        key=lambda s: (-s["wins"], s["matches_played"], s["name"]),
    )
    return standings


def get_advancement_preview(
    db: Session,
    tournament_id: int,
) -> Dict[str, Any]:
    """
    Preview the advancement from groups to knockout.

    Returns:
        Dict with group standings, qualifiers, and any issues.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return {"error": "Tournament not found"}

    group_stages = db.query(Stage).filter(
        Stage.event_id == tournament_id,
        Stage.stage_type == "group",
    ).all()

    if not group_stages:
        return {"error": "No group stage found for this tournament"}

    all_groups_ready = True
    group_previews = []
    qualifiers = []

    for stage in group_stages:
        groups = db.query(Group).filter(Group.stage_id == stage.id).all()
        for group in groups:
            standings = calculate_group_standings(db, group_id=group.id)
            expected = len(db.query(Entry).filter(Entry.group_id == group.id).all())
            expected_matches = (expected * (expected - 1)) // 2
            completed = db.query(Match).filter(
                Match.stage_id == stage.id,
                Match.status == MatchStatus.completed,
            ).count()
            ready = completed >= expected_matches and len(standings) > 0
            if not ready:
                all_groups_ready = False
            group_previews.append({
                "group_id": group.id,
                "group_name": group.name,
                "ready": ready,
                "standings": standings,
            })
            if ready and standings:
                qualifiers.extend(standings[:2])

    return {
        "tournament_id": tournament_id,
        "all_groups_ready": all_groups_ready,
        "group_previews": group_previews,
        "qualifiers": qualifiers,
    }


def commit_advancement(
    db: Session,
    tournament_id: int,
    actor: str = "operator",
) -> Dict[str, Any]:
    """
    Commit advancement: update knockout matches with qualifiers.

    Returns:
        Dict with result status.
    """
    preview = get_advancement_preview(db, tournament_id=tournament_id)
    if "error" in preview:
        return {"success": False, "error": preview["error"]}

    if not preview.get("all_groups_ready"):
        return {"success": False, "error": "Not all groups are ready for advancement"}

    qualifiers = preview.get("qualifiers", [])
    if not qualifiers:
        return {"success": False, "error": "No qualifiers found"}

    knockout_stage = db.query(Stage).filter(
        Stage.event_id == tournament_id,
        Stage.stage_type == "knockout",
    ).first()

    if not knockout_stage:
        return {"success": False, "error": "No knockout stage found"}

    knockout_matches = db.query(Match).filter(
        Match.stage_id == knockout_stage.id,
        Match.player1 == "TBD",
    ).order_by(Match.bracket_index.asc()).all()

    qualifier_idx = 0
    updated = 0
    for match in knockout_matches:
        if qualifier_idx < len(qualifiers):
            q = qualifiers[qualifier_idx]
            match.player1 = q["name"]
            match.player1_id = q["player_id"]
            qualifier_idx += 1
        if qualifier_idx < len(qualifiers):
            q = qualifiers[qualifier_idx]
            match.player2 = q["name"]
            match.player2_id = q["player_id"]
            qualifier_idx += 1
        updated += 1

    db.commit()
    return {
        "success": True,
        "updated_matches": updated,
        "qualifiers_advanced": len(qualifiers),
    }
