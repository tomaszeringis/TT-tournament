"""
Daily Digest Service — Build tournament daily digests from completed matches.

Digest boundaries are calculated in the configured tournament timezone so that
late matches do not fall into the wrong digest.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from tournament_platform.config import settings
from tournament_platform.models import Match, MatchStatus, Tournament
from tournament_platform.services.standings_service import get_standings
from tournament_platform.app.services.awards_service import get_awards
from tournament_platform.app.services.teams_publisher import TeamsPublisher, TeamsEvent

logger = logging.getLogger(__name__)


def build_daily_digest(db: Session, tournament_id: int, target_date: Optional[datetime] = None, tone: str = "neutral") -> str:
    """
    Build a daily digest for a tournament.

    Args:
        db: Database session
        tournament_id: Tournament ID
        target_date: Date to build digest for (timezone-aware). Defaults to today in TOURNAMENT_TIMEZONE.
        tone: Recap tone selector (passed to template engines if applicable).

    Returns:
        Markdown digest string.
    """
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
    if target_date is None:
        target_date = datetime.now(tz)
    elif target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=tz)

    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day.replace(hour=23, minute=59, second=59, microsecond=999999)

    start_utc = start_of_day.astimezone(timezone.utc)
    end_utc = end_of_day.astimezone(timezone.utc)

    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    tournament_name = tournament.name if tournament else "Unknown Tournament"

    completed_today = [
        m for m in db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status == MatchStatus.completed,
            Match.completed_at >= start_utc,
            Match.completed_at <= end_utc,
        ).all()
    ]

    upcoming = [
        m for m in db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status != MatchStatus.completed,
            Match.scheduled_time >= start_utc,
            Match.scheduled_time <= end_of_day,
        ).order_by(Match.scheduled_time.asc()).all()
    ]

    standings = get_standings(db, tournament_id=tournament_id)
    awards = get_awards(db, tournament_id=tournament_id)

    # Build digest text
    lines = [
        f"# {tournament_name} — Daily Digest",
        f"",
        f"_Generated for {start_of_day.strftime('%Y-%m-%d')} ({settings.TOURNAMENT_TIMEZONE})_",
        f"",
        f"## 📋 Today’s Results ({len(completed_today)} matches)",
    ]

    if completed_today:
        for m in completed_today:
            scheduled_str = ""
            if m.scheduled_time:
                local_time = m.scheduled_time.replace(tzinfo=timezone.utc).astimezone(tz)
                scheduled_str = f" @ {local_time.strftime('%H:%M')}"
            lines.append(f"- **{m.player1}** vs **{m.player2}** → {m.score or 'TBD'} (Winner: {m.winner or 'TBD'}){scheduled_str}")
    else:
        lines.append("No completed matches today.")

    lines.extend([
        f"",
        f"## 📊 Current Standings",
    ])
    if standings:
        for i, s in enumerate(standings[:5], 1):
            lines.append(f"{i}. **{s['name']}** — {s.get('wins', 0)}W / {s.get('losses', 0)}L (rating: {s.get('rating', 0)})")
    else:
        lines.append("No standings available yet.")

    lines.extend([
        f"",
        f"## 🏆 Awards & Highlights",
    ])
    if awards.get("champion"):
        lines.append(f"- **Champion:** {awards['champion']}")
    if awards.get("runner_up"):
        lines.append(f"- **Runner-up:** {awards['runner_up']}")
    if awards.get("closest_match"):
        cm = awards["closest_match"]
        lines.append(f"- **Closest Match:** {cm['player1']} vs {cm['player2']} ({cm['margin']} pts)")
    if awards.get("biggest_comeback"):
        bc = awards["biggest_comeback"]
        lines.append(f"- **Biggest Comeback:** {bc['winner']} overcame a {bc['deficit']}-point deficit")
    if awards.get("most_dominant_win"):
        md = awards["most_dominant_win"]
        lines.append(f"- **Dominant Win:** {md['winner']} ({md['max_margin']} pts)")
    if awards.get("most_active_player"):
        lines.append(f"- **Most Active Player:** {awards['most_active_player']}")

    lines.extend([
        f"",
        f"## ⏭️ Upcoming Matches",
    ])
    if upcoming:
        for m in upcoming:
            lines.append(f"- **{m.player1}** vs **{m.player2}** ({m.score or 'vs'})")
    else:
        lines.append("No upcoming matches scheduled.")

    lines.extend([
        f"",
        f"## 🔗 Public Board",
        f"",
        f"View live scores: /?public=1&tournament={tournament_id}",
        f"",
        f"---",
        f"*Auto-generated by Tournament Platform*",
    ])

    return "\n".join(lines)


def post_daily_digest(db: Session, tournament_id: int, actor: str, tone: str = "neutral") -> Dict[str, Any]:
    """
    Build and post a daily digest to Teams.

    Returns:
        Post result dict.
    """
    text = build_daily_digest(db, tournament_id, tone=tone)

    publisher = TeamsPublisher()
    event = TeamsEvent(
        event_type="daily_digest",
        tournament_id=tournament_id,
        match_id=None,
        title="Daily Digest",
        body=text,
        facts={},
        created_at=datetime.now(timezone.utc),
    )
    result = publisher.post_plain_text(event, actor=actor)
    return {
        "success": result.success,
        "status": result.status,
        "message": result.message,
        "text": text,
    }
