from typing import Any, Dict, List, Optional, Tuple

from tournament_platform.app.services.match_analytics.models import (
    GameInsight,
    GameLabel,
    KeyEvent,
    MatchInsight,
    MomentumWindow,
)


def classify_game_label(score_a: int, score_b: int, points_to_win: int = 11) -> GameLabel:
    margin = abs(score_a - score_b)
    max_score = max(score_a, score_b)
    is_deuce = score_a >= 10 and score_b >= 10

    if is_deuce:
        return GameLabel.DEUCE_BATTLE
    if margin >= 8:
        return GameLabel.TOTAL_DOMINATION
    if margin >= 5:
        return GameLabel.COMFORTABLE_WIN
    if margin <= 2 and max_score >= points_to_win:
        return GameLabel.CLOSE_GAME
    return GameLabel.CLOSE_GAME


def game_label_to_summary(label: GameLabel, winner: str, loser: str, score: str, margin: int) -> str:
    summaries = {
        GameLabel.TOTAL_DOMINATION: f"{winner} dominated {loser} {score} with a {margin}-point margin.",
        GameLabel.COMFORTABLE_WIN: f"{winner} beat {loser} {score} in a comfortable win.",
        GameLabel.CLOSE_GAME: f"{winner} edged {loser} {score} in a close game.",
        GameLabel.DEUCE_BATTLE: f"{winner} won {score} against {loser} after a tense deuce battle.",
    }
    return summaries.get(label, f"{winner} won {score} against {loser}.")


def build_game_insights(
    round_scores: List[Tuple[int, int]],
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
    points_to_win: int = 11,
) -> List[GameInsight]:
    insights: List[GameInsight] = []
    for i, (a, b) in enumerate(round_scores):
        winner = player_a_name if a > b else player_b_name
        loser = player_b_name if a > b else player_a_name
        label = classify_game_label(a, b, points_to_win)
        score_str = f"{a}-{b}"
        margin = abs(a - b)
        summary = game_label_to_summary(label, winner, loser, score_str, margin)
        insights.append(
            GameInsight(
                game_number=i + 1,
                winner=winner,
                loser=loser,
                score=score_str,
                margin=margin,
                label=label,
                summary=summary,
            )
        )
    return insights


def detect_momentum(
    history: List[Dict[str, Any]],
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
) -> List[MomentumWindow]:
    momentum: List[MomentumWindow] = []
    if not history:
        return momentum

    current_player: Optional[str] = None
    streak_points = 0
    start_score: str = "0-0"
    end_score: str = "0-0"

    for entry in history:
        if entry.get("action") != "point_added":
            continue
        scorer = entry.get("player")
        if scorer is None:
            continue

        score_a = entry.get("score_a", 0)
        score_b = entry.get("score_b", 0)
        score_str = f"{score_a}-{score_b}"

        if current_player is None:
            current_player = scorer
            streak_points = 1
            start_score = score_str
            end_score = score_str
        elif scorer == current_player:
            streak_points += 1
            end_score = score_str
        else:
            if streak_points >= 3:
                is_major = streak_points >= 5
                label = player_a_name if current_player == "A" else player_b_name
                momentum.append(
                    MomentumWindow(
                        player=label,
                        points=streak_points,
                        start_score=start_score,
                        end_score=end_score,
                        is_major=is_major,
                    )
                )
            current_player = scorer
            streak_points = 1
            start_score = score_str
            end_score = score_str

    if current_player is not None and streak_points >= 3:
        is_major = streak_points >= 5
        label = player_a_name if current_player == "A" else player_b_name
        momentum.append(
            MomentumWindow(
                player=label,
                points=streak_points,
                start_score=start_score,
                end_score=end_score,
                is_major=is_major,
            )
        )

    return momentum


def detect_comeback(
    history: List[Dict[str, Any]],
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
    threshold: int = 5,
) -> List[KeyEvent]:
    key_events: List[KeyEvent] = []
    if len(history) < 2:
        return key_events

    for i in range(1, len(history)):
        prev = history[i - 1]
        curr = history[i]
        if prev.get("action") != "point_added" or curr.get("action") != "point_added":
            continue

        prev_a = prev.get("score_a", 0)
        prev_b = prev.get("score_b", 0)
        curr_a = curr.get("score_a", 0)
        curr_b = curr.get("score_b", 0)

        prev_diff = prev_a - prev_b
        curr_diff = curr_a - curr_b

        if prev_diff <= -threshold and curr_diff >= 0:
            scorer = curr.get("player")
            player = player_a_name if scorer == "A" else player_b_name
            key_events.append(
                KeyEvent(
                    event_type="comeback",
                    player=player,
                    score=f"{curr_a}-{curr_b}",
                    game_number=curr.get("set", 1),
                    text=f"{player} completed a comeback from {abs(prev_diff)} points down to {curr_a}-{curr_b}.",
                    source="history",
                )
            )
        elif prev_diff >= threshold and curr_diff <= 0:
            scorer = curr.get("player")
            player = player_a_name if scorer == "A" else player_b_name
            key_events.append(
                KeyEvent(
                    event_type="comeback",
                    player=player,
                    score=f"{curr_a}-{curr_b}",
                    game_number=curr.get("set", 1),
                    text=f"{player} completed a comeback from {abs(prev_diff)} points down to {curr_a}-{curr_b}.",
                    source="history",
                )
            )

    return key_events


def classify_match_result(
    round_scores: List[Tuple[int, int]],
    games_won_a: int,
    games_won_b: int,
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
) -> GameLabel:
    total_games = games_won_a + games_won_b
    if total_games == 0:
        return GameLabel.ONGOING

    winner = player_a_name if games_won_a > games_won_b else player_b_name

    if games_won_a == 0 or games_won_b == 0:
        return GameLabel.STRAIGHT_GAMES_WIN

    if abs(games_won_a - games_won_b) == 1:
        return GameLabel.TIGHT_MATCH

    return GameLabel.TIGHT_MATCH


def build_match_insight(
    engine: Any,
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
    key_events: Optional[List[KeyEvent]] = None,
) -> MatchInsight:
    round_scores = list(getattr(engine, "round_scores", []))
    games_won_a = getattr(engine, "games_won_a", 0)
    games_won_b = getattr(engine, "games_won_b", 0)
    match_status = getattr(engine, "match_status", "in_progress")
    history = list(getattr(engine, "history", []))
    points_to_win = getattr(engine, "points_to_win", 11)

    game_insights = build_game_insights(round_scores, player_a_name, player_b_name, points_to_win)
    momentum = detect_momentum(history, player_a_name, player_b_name)
    comeback_events = detect_comeback(history, player_a_name, player_b_name)

    all_key_events = list(key_events or []) + comeback_events

    if match_status == "match_won" and round_scores:
        match_label = classify_match_result(round_scores, games_won_a, games_won_b, player_a_name, player_b_name)
        winner = player_a_name if games_won_a > games_won_b else player_b_name
        loser = player_b_name if games_won_a > games_won_b else player_a_name
        score_str = f"{games_won_a}-{games_won_b}"

        if match_label == GameLabel.STRAIGHT_GAMES_WIN:
            title = f"{winner} wins {score_str} in straight games"
            summary = f"{winner} dominated {loser} with a {score_str} straight-games victory."
        elif match_label == GameLabel.TIGHT_MATCH:
            title = f"{winner} wins {score_str} in a tight match"
            summary = f"{winner} edged out {loser} {score_str} in a competitive match."
        else:
            title = f"{winner} wins {score_str}"
            summary = f"{winner} defeated {loser} {score_str}."

        evidence = [g.summary for g in game_insights]
        if momentum:
            for m in momentum:
                evidence.append(f"{m.player} had a {'major' if m.is_major else 'scoring'} run of {m.points} points.")
        if all_key_events:
            for ke in all_key_events:
                evidence.append(ke.text)

        return MatchInsight(
            title=title,
            summary=summary,
            confidence="high",
            evidence=evidence,
            source="deterministic",
            game_insights=game_insights,
            momentum=momentum,
            key_events=all_key_events,
        )

    if round_scores:
        latest_a, latest_b = round_scores[-1]
        title = f"Match in progress: {player_a_name} {latest_a}-{latest_b} {player_b_name}"
        summary = f"Match is ongoing. {len(round_scores)} game(s) completed so far."
    else:
        title = "Match in progress"
        summary = "No completed games yet."

    evidence = [g.summary for g in game_insights]
    if momentum:
        for m in momentum:
            evidence.append(f"{m.player} had a {'major' if m.is_major else 'scoring'} run of {m.points} points.")
    if all_key_events:
        for ke in all_key_events:
            evidence.append(ke.text)

    return MatchInsight(
        title=title,
        summary=summary,
        confidence="medium" if round_scores else "low",
        evidence=evidence,
        source="deterministic",
        game_insights=game_insights,
        momentum=momentum,
        key_events=all_key_events,
    )
