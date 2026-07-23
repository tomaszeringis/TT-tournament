"""
Tests for deterministic recap templates.
"""

from datetime import datetime, timezone

from tournament_platform.app.services.match_facts import MatchFacts
from tournament_platform.app.services.recap_templates import (
    apply_tone,
    build_recap,
    close_decider,
    comeback_win,
    deuce_thriller,
    dominant_win,
    longest_match,
    straight_games_win,
    upset_alert,
)


def _facts(match_id=1, tournament_id=1, player_a="Alice", player_b="Bob", winner="Alice",
           final_score="3-1", game_scores=None, completed_at=None, tags=None,
           player_a_rating=None, player_b_rating=None):
    if game_scores is None:
        game_scores = ["11-5", "11-7", "9-11", "11-3"]
    if tags is None:
        tags = []
    if completed_at is None:
        completed_at = datetime.now(timezone.utc)
    return MatchFacts(
        match_id=match_id,
        tournament_id=tournament_id,
        player_a=player_a,
        player_b=player_b,
        winner=winner,
        final_score=final_score,
        game_scores=game_scores,
        completed_at=completed_at,
        player_a_rating=player_a_rating,
        player_b_rating=player_b_rating,
        tags=tags,
    )


class TestRecapTemplates:
    def test_straight_games_win(self):
        facts = _facts(winner="Alice", final_score="3-0", game_scores=["11-5", "11-3", "11-7"])
        text = straight_games_win(facts)
        assert "Alice" in text
        assert "straight games" in text
        assert "3-0" in text

    def test_dominant_win(self):
        facts = _facts(winner="Alice", final_score="3-1", game_scores=["11-2", "11-8", "8-11", "11-4"])
        text = dominant_win(facts)
        assert "dominated" in text
        assert "Alice" in text

    def test_close_decider(self):
        facts = _facts(winner="Alice", final_score="3-2", game_scores=["11-9", "9-11", "11-10", "8-11", "11-9"])
        text = close_decider(facts)
        assert "edged" in text or "decider" in text

    def test_deuce_thriller(self):
        facts = _facts(winner="Alice", final_score="3-2", game_scores=["11-9", "9-11", "15-13", "8-11", "11-9"])
        text = deuce_thriller(facts)
        assert "deuce" in text.lower() or "tense" in text.lower()

    def test_comeback_win_with_tag(self):
        facts = _facts(winner="Alice", final_score="3-2", game_scores=["5-11", "8-11", "11-9", "11-8", "11-7"], tags=["comeback"])
        text = comeback_win(facts)
        assert "comeback" in text.lower()

    def test_upset_alert(self):
        facts = _facts(winner="Alice", player_a_rating=1100, player_b_rating=1500, final_score="3-2")
        text = upset_alert(facts)
        assert "Upset" in text
        assert "Alice" in text

    def test_longest_match(self):
        facts = _facts(winner="Alice", final_score="3-2", game_scores=["11-9", "9-11", "15-13", "8-11", "11-9"])
        text = longest_match(facts)
        assert "marathon" in text.lower()

    def test_build_recap_selects_template(self):
        facts = _facts(winner="Alice", final_score="3-0", game_scores=["11-5", "11-3", "11-7"])
        text = build_recap(facts)
        assert "Alice" in text
        assert "Bob" in text

    def test_build_recap_neutral_tone(self):
        facts = _facts(winner="Alice", final_score="3-0")
        text = build_recap(facts, tone="neutral")
        assert "🎾" in text

    def test_tone_professional(self):
        text = apply_tone("🎾 Alice won.", tone="professional")
        assert "Match Result:" in text

    def test_tone_fun_office_banter(self):
        text = apply_tone("🎾 Alice won.", tone="fun_office_banter")
        assert "🥋" in text or "🔥" in text

    def test_tone_sport_commentator(self):
        text = apply_tone("🎾 Alice won.", tone="sport_commentator")
        assert "📣" in text

    def test_tone_short_teams_update(self):
        text = apply_tone("🎾 Alice won. Great match!", tone="short_teams_update")
        assert text.endswith(".")
        assert "Great match" not in text

    def test_missing_point_history_graceful_fallback(self):
        facts = _facts(winner="Alice", game_scores=[])
        text = build_recap(facts)
        assert "Alice" in text
        assert "Bob" in text
