from typing import Any, Dict, List, Optional

from tournament_platform.app.services.match_analytics.models import (
    GameInsight,
    GameLabel,
    KeyEvent,
    MatchInsight,
    MomentumWindow,
)


def format_match_insight(insight: MatchInsight, player_a_name: str = "Player A", player_b_name: str = "Player B") -> Dict[str, Any]:
    sections: Dict[str, Any] = {}

    sections["title"] = insight.title
    sections["summary"] = insight.summary
    sections["confidence"] = insight.confidence
    sections["source"] = insight.source

    if insight.game_insights:
        game_by_game = []
        for g in insight.game_insights:
            game_by_game.append({
                "game": g.game_number,
                "score": g.score,
                "winner": g.winner,
                "label": g.label.value,
                "summary": g.summary,
            })
        sections["game_by_game"] = game_by_game

    if insight.momentum:
        momentum_list = []
        for m in insight.momentum:
            momentum_list.append({
                "player": m.player,
                "points": m.points,
                "start_score": m.start_score,
                "end_score": m.end_score,
                "is_major": m.is_major,
            })
        sections["momentum"] = momentum_list

    if insight.key_events:
        events_list = []
        for ke in insight.key_events:
            events_list.append({
                "event_type": ke.event_type,
                "player": ke.player,
                "score": ke.score,
                "game_number": ke.game_number,
                "text": ke.text,
                "source": ke.source,
            })
        sections["key_events"] = events_list

    return sections


def render_match_analytics_sections(formatted: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    lines.append(f"### {formatted.get('title', 'Match Analytics')}")
    lines.append("")
    lines.append(f"**Summary:** {formatted.get('summary', 'No summary available.')}")
    lines.append("")

    if formatted.get("game_by_game"):
        lines.append("**Game by game:**")
        lines.append("")
        for g in formatted["game_by_game"]:
            lines.append(f"- Game {g['game']}: {g['winner']} won {g['score']} ({g['label']}). {g['summary']}")
        lines.append("")

    if formatted.get("momentum"):
        lines.append("**Momentum:**")
        lines.append("")
        for m in formatted["momentum"]:
            size = "Major" if m["is_major"] else "Scoring"
            lines.append(f"- {m['player']}: {size} run of {m['points']} points ({m['start_score']} to {m['end_score']}).")
        lines.append("")

    if formatted.get("key_events"):
        lines.append("**Key moments:**")
        lines.append("")
        for ke in formatted["key_events"]:
            lines.append(f"- [{ke['event_type']}] {ke['text']}")
        lines.append("")

    return lines
