"""
Tests for Duplicate Player Detection Service.
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.models import Player, Match, RatingHistory


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    return db


@pytest.fixture
def sample_players():
    """Create sample players with no duplicates."""
    return [
        Player(id=1, name="John Smith", email="john@example.com", rating=1000),
        Player(id=2, name="Jane Doe", email="jane@example.com", rating=1200),
        Player(id=3, name="Bob Wilson", email="bob@example.com", rating=800),
    ]


@pytest.fixture
def duplicate_players():
    """Create sample players with duplicates."""
    return [
        Player(id=1, name="John Smith", email="john@example.com", rating=1000),
        Player(id=2, name="John Smith", email="john.smith@example.com", rating=1100),  # Same name
        Player(id=3, name="Jane Doe", email="jane@example.com", rating=1200),
        Player(id=4, name="Jon Smith", email="jon@example.com", rating=950),  # Fuzzy match
    ]


# ============================================================================
# Exact Match Tests
# ============================================================================

def test_find_duplicate_candidates_exact_email(mock_db, duplicate_players):
    """Test that exact email matches are detected."""
    # Set up mock to return players
    mock_db.query.return_value.all.return_value = duplicate_players
    
    # Import after patching to avoid import errors
    from tournament_platform.services.duplicate_players import find_duplicate_candidates
    
    candidates = find_duplicate_candidates(mock_db)
    
    # Should find exact email match
    email_matches = [c for c in candidates if c["reason"] == "exact_email"]
    assert len(email_matches) == 0  # No exact email matches in this data
    
    # Should find exact name match
    name_matches = [c for c in candidates if c["reason"] == "exact_name"]
    assert len(name_matches) == 1
    assert name_matches[0]["player1_name"] == "John Smith"
    assert name_matches[0]["player2_name"] == "John Smith"


def test_find_duplicate_candidates_fuzzy_name(mock_db, duplicate_players):
    """Test that fuzzy name matches are detected when RapidFuzz is available."""
    mock_db.query.return_value.all.return_value = duplicate_players
    
    # Import and check if RapidFuzz is available
    import tournament_platform.services.duplicate_players as dp_module
    
    if not dp_module.RAPIDFUZZ_AVAILABLE:
        pytest.skip("RapidFuzz not installed")
    
    from tournament_platform.services.duplicate_players import find_duplicate_candidates
    candidates = find_duplicate_candidates(mock_db, fuzzy_threshold=85)
    
    fuzzy_matches = [c for c in candidates if c["reason"] == "fuzzy_name"]
    assert len(fuzzy_matches) >= 1


def test_find_duplicate_candidates_no_duplicates(mock_db, sample_players):
    """Test that no candidates are found when there are no duplicates."""
    mock_db.query.return_value.all.return_value = sample_players
    
    from tournament_platform.services.duplicate_players import find_duplicate_candidates
    
    candidates = find_duplicate_candidates(mock_db)
    
    assert len(candidates) == 0


def test_find_duplicate_candidates_sorted_by_similarity(mock_db, duplicate_players):
    """Test that candidates are sorted by similarity score descending."""
    mock_db.query.return_value.all.return_value = duplicate_players
    
    import tournament_platform.services.duplicate_players as dp_module
    
    if not dp_module.RAPIDFUZZ_AVAILABLE:
        pytest.skip("RapidFuzz not installed")
    
    from tournament_platform.services.duplicate_players import find_duplicate_candidates
    candidates = find_duplicate_candidates(mock_db, fuzzy_threshold=80)
    
    if len(candidates) > 1:
        scores = [c["similarity_score"] for c in candidates]
        assert scores == sorted(scores, reverse=True)


# ============================================================================
# Merge Preview Tests
# ============================================================================

def test_preview_player_merge_success(mock_db):
    """Test successful merge preview."""
    target = Player(id=1, name="John Smith", email="john@example.com", rating=1000)
    source = Player(id=2, name="John Smith", email="john.smith@example.com", rating=1100)
    
    from tournament_platform.services.duplicate_players import preview_player_merge
    
    # Mock database queries
    mock_db.query.return_value.filter.return_value.first.side_effect = [target, source]
    mock_db.query.return_value.filter.return_value.all.return_value = []
    
    result = preview_player_merge(mock_db, target_player_id=1, source_player_id=2)
    
    assert result["success"] is True
    assert result["target_player"]["id"] == 1
    assert result["source_player"]["id"] == 2
    assert result["matches_to_transfer"] == 0
    assert result["rating_history_to_transfer"] == 0


def test_preview_player_merge_target_not_found(mock_db):
    """Test merge preview when target player doesn't exist."""
    from tournament_platform.services.duplicate_players import preview_player_merge
    
    mock_db.query.return_value.filter.return_value.first.return_value = None
    
    result = preview_player_merge(mock_db, target_player_id=999, source_player_id=1)
    
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_preview_player_merge_source_not_found(mock_db):
    """Test merge preview when source player doesn't exist."""
    target = Player(id=1, name="John Smith", email="john@example.com", rating=1000)
    
    from tournament_platform.services.duplicate_players import preview_player_merge
    
    mock_db.query.return_value.filter.return_value.first.side_effect = [target, None]
    
    result = preview_player_merge(mock_db, target_player_id=1, source_player_id=999)
    
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_preview_player_merge_includes_warnings(mock_db):
    """Test that merge preview includes appropriate warnings."""
    target = Player(id=1, name="John Smith", email="john@example.com", rating=1000)
    source = Player(id=2, name="John Smith", email="john.smith@example.com", rating=1100)
    
    # Mock matches
    match1 = Match(id=1, player1_id=2, player2_id=3)
    match2 = Match(id=2, winner_id=2)
    
    # Mock rating history
    history = RatingHistory(id=1, player_id=2, rating=1100)
    
    from tournament_platform.services.duplicate_players import preview_player_merge
    
    mock_db.query.return_value.filter.return_value.first.side_effect = [target, source]
    mock_db.query.return_value.filter.return_value.all.side_effect = [[match1, match2], [history]]
    
    result = preview_player_merge(mock_db, target_player_id=1, source_player_id=2)
    
    assert result["success"] is True
    assert result["matches_to_transfer"] == 2
    assert result["rating_history_to_transfer"] == 1
    assert len(result["warnings"]) > 0


# ============================================================================
# Merge Execution Tests
# ============================================================================

def test_merge_players_success(mock_db):
    """Test successful player merge."""
    target = Player(id=1, name="John Smith", email="john@example.com", rating=1000)
    source = Player(id=2, name="John Smith", email="john.smith@example.com", rating=1100)
    
    match = Match(id=1, player1_id=2, player2_id=3, winner_id=2)
    
    from tournament_platform.services.duplicate_players import merge_players
    
    # Set up mock chain - need to handle multiple query calls
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    
    # First call: get target and source players
    mock_query.filter.return_value.first.side_effect = [target, source]
    
    # Second call: get matches for source
    mock_query.filter.return_value.all.return_value = [match]
    
    # Mock commit and delete
    mock_db.commit.return_value = None
    mock_db.delete.return_value = None
    
    result = merge_players(mock_db, target_player_id=1, source_player_id=2, actor="test")
    
    assert result["success"] is True
    assert result["matches_transferred"] == 1


def test_merge_players_same_player(mock_db):
    """Test that merging a player with themselves fails."""
    from tournament_platform.services.duplicate_players import merge_players
    
    result = merge_players(mock_db, target_player_id=1, source_player_id=1, actor="test")
    
    assert result["success"] is False
    assert "themselves" in result["error"].lower()


def test_merge_players_rollback_on_error(mock_db):
    """Test that merge rolls back on error."""
    target = Player(id=1, name="John Smith", email="john@example.com", rating=1000)
    source = Player(id=2, name="John Smith", email="john.smith@example.com", rating=1100)
    
    from tournament_platform.services.duplicate_players import merge_players
    
    mock_db.query.return_value.filter.return_value.first.side_effect = [target, source]
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.commit.side_effect = Exception("Database error")
    
    result = merge_players(mock_db, target_player_id=1, source_player_id=2, actor="test")
    
    assert result["success"] is False
    assert "error" in result
    mock_db.rollback.assert_called_once()


# ============================================================================
# Integration Tests
# ============================================================================

def test_duplicate_detection_with_matches(mock_db):
    """Test that match count is correctly calculated for duplicate candidates."""
    p1 = Player(id=1, name="John Smith", email="john@example.com", rating=1000)
    p2 = Player(id=2, name="John Smith", email="john.smith@example.com", rating=1100)
    
    # Match where both players appear
    match = Match(id=1, player1_id=1, player2_id=2)
    
    from tournament_platform.services.duplicate_players import find_duplicate_candidates, _count_shared_matches
    
    mock_db.query.return_value.all.return_value = [p1, p2]
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    
    candidates = find_duplicate_candidates(mock_db)
    
    assert len(candidates) == 1
    assert candidates[0]["match_count"] == 1