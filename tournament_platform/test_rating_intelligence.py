"""
Tests for ranking intelligence helper functions in services/rating_intelligence.py.
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.services.rating_intelligence import (
    get_leaderboard_data,
    get_player_rating_history_data,
    preview_match_rating,
    UPSET_THRESHOLD,
)


def make_player(player_id, name, rating, history=None):
    p = MagicMock()
    p.id = player_id
    p.name = name
    p.rating = rating
    p.rating_history = history or []
    return p


@pytest.fixture
def mock_session():
    session = MagicMock()
    return session


def test_get_leaderboard_data_returns_sorted_by_rating_desc(mock_session):
    """Players should be returned sorted by rating descending."""
    p1 = make_player(1, "Alice", 1500)
    p2 = make_player(2, "Bob", 1200)
    p3 = make_player(3, "Charlie", 1800)

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            q.order_by.return_value.all.return_value = [p3, p1, p2]
            return q
        elif model.__name__ == "Match":
            q = MagicMock()
            q.filter.return_value.all.return_value = []
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = get_leaderboard_data(db_session=mock_session)

    names = [entry["name"] for entry in result]
    assert names == ["Charlie", "Alice", "Bob"]


def test_get_leaderboard_data_counts_wins_losses(mock_session):
    """Wins and losses should be derived from completed matches."""
    p1 = make_player(1, "Alice", 1500)
    p2 = make_player(2, "Bob", 1200)

    match1 = MagicMock()
    match1.winner_id = 1
    match1.status.value = "completed"

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            q.order_by.return_value.all.return_value = [p1, p2]
            return q
        elif model.__name__ == "Match":
            q = MagicMock()
            q.filter.return_value.all.return_value = [match1]
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = get_leaderboard_data(db_session=mock_session)
    alice_entry = next(e for e in result if e["name"] == "Alice")
    bob_entry = next(e for e in result if e["name"] == "Bob")

    assert alice_entry["wins"] == 1
    assert alice_entry["losses"] == 0
    assert bob_entry["wins"] == 0
    assert bob_entry["losses"] == 1


def test_get_leaderboard_data_last_rating_change(mock_session):
    """Last rating change should be computed from history."""
    from datetime import datetime

    p1 = make_player(1, "Alice", 1500)
    h1 = MagicMock(rating=1500, timestamp=datetime(2024, 1, 1))
    h2 = MagicMock(rating=1480, timestamp=datetime(2024, 1, 2))
    p1.rating_history = [h1, h2]

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            q.order_by.return_value.all.return_value = [p1]
            return q
        elif model.__name__ == "Match":
            q = MagicMock()
            q.filter.return_value.all.return_value = []
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = get_leaderboard_data(db_session=mock_session)
    # 1480 - 1500 = -20
    assert result[0]["last_rating_change"] == -20


def test_get_leaderboard_data_no_history(mock_session):
    """Last rating change should be None when no history exists."""
    p1 = make_player(1, "Alice", 1500)

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            q.order_by.return_value.all.return_value = [p1]
            return q
        elif model.__name__ == "Match":
            q = MagicMock()
            q.filter.return_value.all.return_value = []
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = get_leaderboard_data(db_session=mock_session)
    assert result[0]["last_rating_change"] is None


def test_get_player_rating_history_data(mock_session):
    """Should return history entries as dicts sorted by timestamp ascending."""
    from datetime import datetime

    p1 = make_player(1, "Alice", 1500)
    h1 = MagicMock(id=10, rating=1400, timestamp=datetime(2024, 1, 1))
    h2 = MagicMock(id=11, rating=1500, timestamp=datetime(2024, 1, 2))

    def query_side_effect(model):
        if model.__name__ == "RatingHistory":
            q = MagicMock()
            q.filter.return_value.order_by.return_value.all.return_value = [h1, h2]
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = get_player_rating_history_data(1, db_session=mock_session)
    assert len(result) == 2
    assert result[0]["rating"] == 1400
    assert result[1]["rating"] == 1500


def test_get_player_rating_history_data_empty(mock_session):
    """Should return empty list when no history exists."""
    def query_side_effect(model):
        if model.__name__ == "RatingHistory":
            q = MagicMock()
            q.filter.return_value.order_by.return_value.all.return_value = []
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = get_player_rating_history_data(999, db_session=mock_session)
    assert result == []


def test_preview_match_rating_identical_ratings(mock_session):
    """When ratings are equal, no favorite and no upset."""
    p1 = make_player(1, "Alice", 1500)
    p2 = make_player(2, "Bob", 1500)

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            q.filter.return_value.first.side_effect = [p1, p2]
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = preview_match_rating(1, 2, db_session=mock_session)

    assert result["rating_difference"] == 0
    assert result["upset_possible"] is False
    assert "identical" in result["explanation"].lower()


def test_preview_match_rating_clear_favorite(mock_session):
    """Higher-rated player is the expected favorite."""
    p1 = make_player(1, "Alice", 1600)
    p2 = make_player(2, "Bob", 1400)

    # Use a call counter to return p1 then p2 on successive .first() calls
    call_counter = [0]

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            def first_side_effect():
                call_counter[0] += 1
                if call_counter[0] == 1:
                    return p1
                return p2
            q.filter.return_value.first.side_effect = first_side_effect
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = preview_match_rating(1, 2, db_session=mock_session)

    assert result["expected_favorite"] == 1
    assert result["rating_difference"] == 200
    assert result["upset_possible"] is False


def test_preview_match_rating_upset_when_lower_rated_wins(mock_session):
    """If lower-rated player is selected as winner, upset_possible is True."""
    p1 = make_player(1, "Alice", 1600)
    p2 = make_player(2, "Bob", 1400)

    call_counter = [0]

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            def first_side_effect():
                call_counter[0] += 1
                if call_counter[0] == 1:
                    return p1
                return p2
            q.filter.return_value.first.side_effect = first_side_effect
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = preview_match_rating(1, 2, winner_id=2, db_session=mock_session)

    assert result["upset_possible"] is True
    assert "upset" in result["explanation"].lower()


def test_preview_match_rating_no_upset_when_favorite_wins(mock_session):
    """If favorite wins, upset_possible is False."""
    p1 = make_player(1, "Alice", 1600)
    p2 = make_player(2, "Bob", 1400)

    call_counter = [0]

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            def first_side_effect():
                call_counter[0] += 1
                if call_counter[0] == 1:
                    return p1
                return p2
            q.filter.return_value.first.side_effect = first_side_effect
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = preview_match_rating(1, 2, winner_id=1, db_session=mock_session)

    assert result["upset_possible"] is False
    assert "expected winner" in result["explanation"].lower()


def test_preview_match_rating_missing_player(mock_session):
    """Should handle missing players gracefully."""
    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            q.filter.return_value.first.side_effect = [None, None]
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    result = preview_match_rating(1, 2, db_session=mock_session)

    assert result["explanation"] == "One or both players not found."
    assert result["upset_possible"] is False


def test_preview_match_rating_predicted_changes(mock_session):
    """Predicted rating changes should be computed when winner is specified."""
    p1 = make_player(1, "Alice", 1600)
    p2 = make_player(2, "Bob", 1400)

    call_counter = [0]

    def query_side_effect(model):
        if model.__name__ == "Player":
            q = MagicMock()
            def first_side_effect():
                call_counter[0] += 1
                if call_counter[0] == 1:
                    return p1
                return p2
            q.filter.return_value.first.side_effect = first_side_effect
            return q
        return MagicMock()

    mock_session.query.side_effect = query_side_effect

    with patch("tournament_platform.services.ranking_service.Rankings") as MockRankings, \
         patch("tournament_platform.services.ranking_service.ConfigManager") as MockConfig:
        mock_rankings = MagicMock()
        mock_rankings._points_to_assign.return_value = (25.0, -25.0)
        MockRankings.return_value = mock_rankings

        mock_cm = MagicMock()
        mock_cm.current_config.compute.rating_factor = 2.0
        MockConfig.return_value = mock_cm

        result = preview_match_rating(1, 2, winner_id=1, db_session=mock_session)

    assert result["predicted_rating_changes"] is not None
    assert len(result["predicted_rating_changes"]) == 2
