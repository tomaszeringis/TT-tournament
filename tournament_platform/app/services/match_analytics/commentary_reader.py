from typing import Any, Dict, List, Optional

from tournament_platform.app.services.match_analytics.models import KeyEvent

HIGH_VALUE_EVENT_TYPES = {
    "game_point",
    "match_point",
    "game_won",
    "match_won",
    "streak",
    "comeback",
    "lead_change",
    "deuce",
    "advantage",
}

HIGH_IMPORTANCE = {"important", "critical"}


def _read_commentary_events_db(match_id: int, limit: int = 20) -> List[Any]:
    try:
        from tournament_platform.services.commentary_service import get_recent_commentary_events
        return get_recent_commentary_events(match_id, limit=limit)
    except Exception:
        return []


def _read_session_commentary() -> List[str]:
    try:
        import streamlit as st
        texts = []
        last_text = st.session_state.get("last_commentary_text")
        if last_text:
            texts.append(last_text)
        pending = st.session_state.get("pending_commentary", [])
        if isinstance(pending, list):
            for item in pending:
                if isinstance(item, str) and item:
                    texts.append(item)
                elif isinstance(item, dict):
                    text = item.get("final_text") or item.get("generated_text") or item.get("text")
                    if text:
                        texts.append(text)
        return texts
    except Exception:
        return []


def _event_importance(event: Any) -> Optional[str]:
    importance = getattr(event, "importance", None)
    if importance:
        return str(importance).lower()
    intensity = getattr(event, "intensity", None)
    if intensity:
        return str(intensity).lower()
    event_type = getattr(event, "event_type", "")
    if event_type in ("game_won", "match_won", "match_point", "game_point"):
        return "critical"
    if event_type in ("streak", "comeback", "lead_change", "deuce", "advantage"):
        return "important"
    return None


def _map_commentary_event_to_key_event(event: Any, player_a_name: str, player_b_name: str) -> Optional[KeyEvent]:
    event_type = getattr(event, "event_type", "")
    final_text = getattr(event, "final_text", "") or getattr(event, "generated_text", "")
    if not final_text:
        return None

    score_after = getattr(event, "score_after_json", None)
    score_str = ""
    if score_after:
        try:
            import json
            parsed = json.loads(score_after)
            if isinstance(parsed, dict):
                score_str = f"{parsed.get('score_a', '?')}-{parsed.get('score_b', '?')}"
        except Exception:
            score_str = ""

    player_a = getattr(event, "player_a", None) or player_a_name
    player_b = getattr(event, "player_b", None) or player_b_name

    player = player_a
    if event_type and event_type.endswith("_b") or event_type.endswith("B"):
        player = player_b

    return KeyEvent(
        event_type=event_type,
        player=player,
        score=score_str,
        game_number=0,
        text=final_text,
        source="commentary_log",
    )


def read_key_events(
    match_id: int,
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
    include_session: bool = True,
    limit: int = 20,
) -> List[KeyEvent]:
    key_events: List[KeyEvent] = []

    db_events = _read_commentary_events_db(match_id, limit=limit)
    for event in db_events:
        importance = _event_importance(event)
        event_type = getattr(event, "event_type", "")

        if event_type in HIGH_VALUE_EVENT_TYPES:
            mapped = _map_commentary_event_to_key_event(event, player_a_name, player_b_name)
            if mapped:
                key_events.append(mapped)
            continue

        if importance in HIGH_IMPORTANCE:
            mapped = _map_commentary_event_to_key_event(event, player_a_name, player_b_name)
            if mapped:
                key_events.append(mapped)

    if include_session:
        session_texts = _read_session_commentary()
        for text in session_texts:
            key_events.append(
                KeyEvent(
                    event_type="session_commentary",
                    player=player_a_name,
                    score="",
                    game_number=0,
                    text=text,
                    source="commentary_log",
                )
            )

    return key_events
