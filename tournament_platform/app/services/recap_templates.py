"""
Deterministic recap templates for tournament match results.

Every template receives only ``MatchFacts`` as input. Tone modifiers are applied
after the base template is selected.
"""

from typing import Optional

from tournament_platform.app.services.match_facts import MatchFacts


# ============================================================================
# Base templates
# ============================================================================

def straight_games_win(facts: MatchFacts) -> str:
    return f"🎾 {facts.winner} swept {facts.loser_name()} {facts.final_score} in straight games."


def dominant_win(facts: MatchFacts) -> str:
    margins = _parse_game_margins(facts)
    top_margin = max(margins) if margins else 0
    return (
        f"🎾 {facts.winner} dominated {facts.loser_name()} {facts.final_score} "
        f"with a dominant performance (max game margin: {top_margin} pts)."
    )


def close_decider(facts: MatchFacts) -> str:
    margins = _parse_game_margins(facts)
    min_margin = min(margins) if margins else 0
    return (
        f"🎾 {facts.winner} edged out {facts.loser_name()} {facts.final_score} "
        f"in a nail-biting decider (closest game margin: {min_margin} pts)."
    )


def deuce_thriller(facts: MatchFacts) -> str:
    return (
        f"🎾 {facts.winner} survived a tense battle with {facts.loser_name()} "
        f"{facts.final_score}. Multiple deuce battles made this a thriller to watch."
    )


def comeback_win(facts: MatchFacts) -> str:
    if "comeback" in facts.tags:
        return (
            f"🎾 Incredible comeback! {facts.winner} fought back to defeat "
            f"{facts.loser_name()} {facts.final_score} after being behind."
        )
    return (
        f"🎾 {facts.winner} completed the comeback against {facts.loser_name()} "
        f"{facts.final_score}. Never say never!"
    )


def upset_alert(facts: MatchFacts) -> str:
    return (
        f"🚨 Upset alert! {facts.winner} (lower rated) knocked out "
        f"{facts.loser_name()} {facts.final_score}. A stunning result!"
    )


def longest_match(facts: MatchFacts) -> str:
    return (
        f"⏱️ Marathon match! {facts.winner} outlasted {facts.loser_name()} "
        f"{facts.final_score} in the longest match of the tournament so far."
    )


# ============================================================================
# Selectors & formatters
# ============================================================================

def build_recap(facts: MatchFacts, tone: str = "neutral") -> str:
    """Choose a deterministic template and apply the requested tone."""
    base = _select_template(facts)
    return apply_tone(base, tone)


def _select_template(facts: MatchFacts) -> str:
    games = facts.game_scores
    if not games:
        return f"🎾 {facts.winner} defeated {facts.loser_name()} {facts.final_score}."

    parsed = _parse_game_scores(games)
    games_won_winner = sum(1 for p1, p2 in parsed if p1 > p2 if facts.player_a == facts.winner) + \
                       sum(1 for p1, p2 in parsed if p2 > p1 if facts.player_b == facts.winner)
    games_won_loser = len(games) - games_won_winner

    if games_won_winner == 0 or games_won_loser == 0:
        return straight_games_win(facts)

    if games_won_loser == games_won_winner - 1:
        if any(p1 >= 10 and p2 >= 10 for p1, p2 in parsed):
            deuce_count = sum(1 for p1, p2 in parsed if p1 >= 10 and p2 >= 10)
            if deuce_count >= 1:
                return deuce_thriller(facts)
        margins = _parse_game_margins(facts)
        if margins and min(margins) <= 2:
            return close_decider(facts)
        return close_decider(facts)

    if games_won_winner > games_won_loser + 1:
        margins = _parse_game_margins(facts)
        if margins and max(margins) >= 6:
            return dominant_win(facts)
        return dominant_win(facts)

    return close_decider(facts)


# ============================================================================
# Tone modifiers
# ============================================================================

def apply_tone(text: str, tone: str) -> str:
    if tone == "professional":
        return text.replace("🎾", "Match Result:").replace("🚨", "Notice:").replace("⏱️", "Note:")
    if tone == "fun_office_banter":
        return text.replace("🎾", "🥋").replace("🚨", "🔥") + " What a match!"
    if tone == "sport_commentator":
        return text.replace("🎾", "📣") + " And that's the final whistle!"
    if tone == "short_teams_update":
        return text.split(".")[0] + "."
    return text


# ============================================================================
# Helpers
# ============================================================================

def _parse_game_scores(game_scores: list[str]) -> list[tuple[int, int]]:
    results = []
    for gs in game_scores:
        try:
            parts = gs.strip().split("-")
            if len(parts) == 2:
                results.append((int(parts[0].strip()), int(parts[1].strip())))
        except (ValueError, AttributeError):
            continue
    return results


def _parse_game_margins(facts: MatchFacts) -> list[int]:
    parsed = _parse_game_scores(facts.game_scores)
    return [abs(p1 - p2) for p1, p2 in parsed]
