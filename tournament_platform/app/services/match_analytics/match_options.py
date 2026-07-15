from typing import Any, List, Optional

from tournament_platform.app.services.match_analytics.models import MatchAnalyticsOption


def parse_game_scores(game_scores_str: Optional[str]) -> List[tuple]:
    if not game_scores_str:
        return []
    scores = []
    for part in game_scores_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            a_str, b_str = part.split("-")
            scores.append((int(a_str), int(b_str)))
        except (ValueError, TypeError):
            continue
    return scores


def build_synthetic_engine_from_match(match: Any) -> Any:
    round_scores = parse_game_scores(getattr(match, "game_scores", None))
    games_won_a = 0
    games_won_b = 0
    for a, b in round_scores:
        if a > b:
            games_won_a += 1
        elif b > a:
            games_won_b += 1

    class _SyntheticEngine:
        pass

    engine = _SyntheticEngine()
    engine.round_scores = round_scores
    engine.games_won_a = games_won_a
    engine.games_won_b = games_won_b
    engine.match_status = "match_won" if getattr(match, "winner", None) else "in_progress"
    engine.history = []
    engine.points_to_win = 11
    return engine


def load_completed_match_options(
    db: Any,
    tournament_id: Optional[int] = None,
    limit: int = 100,
    tournament_name: Optional[str] = None,
) -> List[MatchAnalyticsOption]:
    from tournament_platform.models import Match, MatchStatus

    query = db.query(Match).filter(Match.status == MatchStatus.completed)
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)
    query = query.order_by(Match.completed_at.desc().nullslast(), Match.id.desc())
    matches = query.limit(limit).all()

    options: List[MatchAnalyticsOption] = []
    for m in matches:
        player_a = m.player1 or "Player A"
        player_b = m.player2 or "Player B"

        if _looks_like_generated_player(player_a) and _looks_like_generated_player(player_b):
            continue

        winner = m.winner or ""
        score = m.score or ""
        game_scores_list = [s.strip() for s in m.game_scores.split(",") if s.strip()] if m.game_scores else None

        label = format_match_option_label(
            player_a=player_a,
            player_b=player_b,
            winner=winner,
            match_score=score,
            game_scores=game_scores_list,
            match_id=m.id,
        )

        options.append(
            MatchAnalyticsOption(
                id=str(m.id),
                label=label,
                player_a_name=player_a,
                player_b_name=player_b,
                winner_name=winner or None,
                match_score=score or None,
                game_scores=game_scores_list,
                source="database",
            )
        )
    return options


_GENERATED_PLAYER_PREFIXES = (
    "MetA",
    "MetB",
    "SwissA",
    "SwissB",
    "SeedA",
    "SeedB",
    "GKS",
    "SGS",
)


def _looks_like_generated_player(name: str) -> bool:
    if not name:
        return False
    for prefix in _GENERATED_PLAYER_PREFIXES:
        if name.startswith(prefix):
            return True
    if name.isdigit() or (len(name) > 8 and name.startswith("Player")):
        return True
    return False


def format_match_option_label(
    player_a: str,
    player_b: str,
    winner: str = "",
    match_score: str = "",
    game_scores: Optional[List[str]] = None,
    match_id: Optional[int] = None,
) -> str:
    parts = [f"{player_a} vs {player_b}"]

    if winner:
        parts.append(f"{winner} won")
        if match_score:
            parts.append(match_score)
    elif match_score:
        parts.append(match_score)

    if game_scores:
        parts.append("—")
        parts.append(", ".join(game_scores))

    if match_id is not None and not winner and not match_score:
        parts.append(f"completed match #{match_id}")

    return " ".join(parts)
