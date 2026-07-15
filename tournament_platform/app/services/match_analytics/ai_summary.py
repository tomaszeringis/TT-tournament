import hashlib
from typing import Any, Dict, List, Optional

import streamlit as st

from tournament_platform.app.services.match_analytics.models import MatchInsight
from tournament_platform.app.services.match_analytics.formatter import format_match_insight


def _score_hash(engine: Any) -> str:
    round_scores = getattr(engine, "round_scores", [])
    games_won_a = getattr(engine, "games_won_a", 0)
    games_won_b = getattr(engine, "games_won_b", 0)
    data = f"{games_won_a}-{games_won_b}:{round_scores}"
    return hashlib.sha1(data.encode()).hexdigest()


def build_ai_prompt(insight: MatchInsight, player_a_name: str = "Player A", player_b_name: str = "Player B") -> str:
    formatted = format_match_insight(insight, player_a_name, player_b_name)

    facts: List[str] = []
    facts.append(f"Match: {player_a_name} vs {player_b_name}")
    facts.append(f"Title: {formatted.get('title', '')}")
    facts.append(f"Summary: {formatted.get('summary', '')}")
    facts.append(f"Match result confidence: {formatted.get('confidence', 'unknown')}")

    for g in formatted.get("game_by_game", []):
        facts.append(f"Game {g['game']}: {g['winner']} won {g['score']} ({g['label']}). {g['summary']}")

    for m in formatted.get("momentum", []):
        size = "major" if m["is_major"] else "scoring"
        facts.append(f"Momentum: {m['player']} had a {size} run of {m['points']} points ({m['start_score']} to {m['end_score']}).")

    for ke in formatted.get("key_events", []):
        facts.append(f"Key event ({ke['event_type']}): {ke['text']}")

    prompt = (
        "You are summarizing a table tennis match.\n"
        "Use only the facts below.\n"
        "Do not invent points, scores, winners, or game numbers.\n"
        "Return 3 concise bullets and a one-sentence match story.\n\n"
        "Facts:\n"
    )
    for f in facts:
        prompt += f"- {f}\n"

    return prompt


@st.cache_data(ttl=3600)
def _cached_ai_summary(match_id: int, score_hash: str, prompt: str) -> Optional[str]:
    try:
        from tournament_platform.services.ai_engine import AIEngine
        engine = AIEngine()
        response = engine._chat_with_fallback(
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.get("message", {}).get("content", "").strip()
        if not text:
            return None
        return text
    except Exception:
        return None


def generate_ai_summary(
    insight: MatchInsight,
    match_id: int,
    engine: Any,
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
) -> str:
    prompt = build_ai_prompt(insight, player_a_name, player_b_name)
    score_hash = _score_hash(engine)

    cached = _cached_ai_summary(match_id, score_hash, prompt)
    if cached:
        return cached

    try:
        from tournament_platform.services.ai_engine import AIEngine
        ai_engine = AIEngine()
        response = ai_engine._chat_with_fallback(
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.get("message", {}).get("content", "").strip()
        if not text:
            return ""
        return text
    except Exception:
        return ""
