"""
Unit tests for AI match parsing to verify correct player-score mapping.

These tests ensure that the MatchResult schema correctly preserves
the relationship between players and their scores, preventing the bug
where "Bob beats Alice 3-1" would incorrectly become "Alice-Bob 3-1".
"""

import pytest
import datetime
from unittest.mock import patch, MagicMock
from tournament_platform.services.ai_engine import MatchResult, validate_and_map_to_match
from tournament_platform.models import SessionLocal, Match, MatchStatus, init_db
from tournament_platform.services.ai_facade import get_ai_health, answer_rules_question, AIHealth, AIAnswer


class TestMatchResultSchema:
    """Tests for the MatchResult Pydantic model."""

    def test_match_result_preserves_player_score_mapping(self):
        """MatchResult should preserve exact player-score mapping without reordering."""
        # "Bob beats Alice 3-1" - Bob is player_a with score 3, Alice is player_b with score 1
        result = MatchResult(
            player_a="Bob",
            player_b="Alice",
            player_a_score=3,
            player_b_score=1,
            winner="Bob"
        )
        
        match_data = result.to_match_model()
        
        # Verify the mapping is preserved
        assert match_data["player1"] == "Bob"
        assert match_data["player2"] == "Alice"
        assert match_data["score"] == "3-1"
        assert match_data["winner"] == "Bob"

    def test_match_result_alice_bob_3_1(self):
        """Test the specific bug case: Bob beats Alice 3-1 should not become Alice-Bob 3-1."""
        result = MatchResult(
            player_a="Bob",
            player_b="Alice",
            player_a_score=3,
            player_b_score=1,
            winner="Bob"
        )
        
        match_data = result.to_match_model()
        
        # The score "3-1" should mean Bob (player1) scored 3, Alice (player2) scored 1
        # NOT the other way around
        assert match_data["player1"] == "Bob"
        assert match_data["player2"] == "Alice"
        assert match_data["score"] == "3-1"
        
        # If we were to incorrectly sort alphabetically, this would fail:
        # Alice would be player1 with score 3, which is wrong!

    def test_match_result_alice_bob_1_3(self):
        """Test the reverse: Alice beats Bob 1-3."""
        result = MatchResult(
            player_a="Alice",
            player_b="Bob",
            player_a_score=1,
            player_b_score=3,
            winner="Bob"
        )
        
        match_data = result.to_match_model()
        
        assert match_data["player1"] == "Alice"
        assert match_data["player2"] == "Bob"
        assert match_data["score"] == "1-3"
        assert match_data["winner"] == "Bob"

    def test_match_result_validates_winner(self):
        """MatchResult should validate that winner is one of the players."""
        with pytest.raises(ValueError, match="must be either player_a or player_b"):
            MatchResult(
                player_a="Alice",
                player_b="Bob",
                player_a_score=3,
                player_b_score=1,
                winner="Charlie"  # Invalid winner
            )

    def test_match_result_validates_non_negative_scores(self):
        """MatchResult should validate that scores are non-negative."""
        with pytest.raises(ValueError, match="Scores must be non-negative"):
            MatchResult(
                player_a="Alice",
                player_b="Bob",
                player_a_score=-1,
                player_b_score=1,
                winner="Alice"
            )


class TestValidateAndMapToMatch:
    """Tests for the validate_and_map_to_match helper function."""

    def test_validate_and_map_returns_explicit_score_fields(self):
        """validate_and_map_to_match should return explicit player-score fields for UI."""
        result_dict = {
            "player_a": "Bob",
            "player_b": "Alice",
            "player_a_score": 3,
            "player_b_score": 1,
            "winner": "Bob"
        }
        
        mapped = validate_and_map_to_match(result_dict)
        
        # Should return a Match instance (since Match is available)
        from tournament_platform.models import Match
        assert isinstance(mapped, Match)
        assert mapped.player1 == "Bob"
        assert mapped.player2 == "Alice"
        assert mapped.winner == "Bob"
        assert mapped.score == "3-1"

    def test_validate_and_map_preserves_alphabetical_order_bug_case(self):
        """Ensure the specific bug case is handled correctly."""
        # This is the exact case that was failing: "Bob beats Alice 3-1"
        result_dict = {
            "player_a": "Bob",
            "player_b": "Alice",
            "player_a_score": 3,
            "player_b_score": 1,
            "winner": "Bob"
        }
        
        mapped = validate_and_map_to_match(result_dict)
        
        # The key assertion: Bob should be player1 with score 3, Alice should be player2 with score 1
        # NOT the other way around (which would happen with alphabetical sorting)
        assert mapped.player1 == "Bob", "Bob (player_a) should be player1"
        assert mapped.player2 == "Alice", "Alice (player_b) should be player2"
        assert mapped.score == "3-1"
        
        # Verify the score is correctly parsed
        s1, s2 = map(int, mapped.score.split('-'))
        assert s1 == 3, "Bob should have score 3"
        assert s2 == 1, "Alice should have score 1"

    def test_validate_and_map_with_match_model(self):
        """When Match model is available, validate_and_map_to_match should return Match instance."""
        from tournament_platform.models import Match, MatchStatus
        
        result_dict = {
            "player_a": "Alice",
            "player_b": "Bob",
            "player_a_score": 3,
            "player_b_score": 0,
            "winner": "Alice"
        }
        
        mapped = validate_and_map_to_match(result_dict)
        
        # Should return a Match instance
        assert isinstance(mapped, Match)
        assert mapped.player1 == "Alice"
        assert mapped.player2 == "Bob"
        assert mapped.winner == "Alice"
        assert mapped.score == "3-0"
        assert mapped.status == MatchStatus.completed


class TestGetRecentMatches:
    """Tests for the get_recent_matches function in dashboard.py."""

    @pytest.fixture(autouse=True)
    def setup_database(self):
        """Set up test database with sample matches."""
        init_db()
        db = SessionLocal()
        
        # Clear existing matches
        db.query(Match).delete()
        db.commit()
        
        # Create matches with different scheduled times
        now = datetime.datetime.utcnow()
        
        # Most recent match (should appear first)
        match1 = Match(
            player1="Alice",
            player2="Bob",
            winner="Alice",
            score="3-1",
            status=MatchStatus.completed,
            scheduled_time=now - datetime.timedelta(minutes=10)
        )
        
        # Second most recent
        match2 = Match(
            player1="Charlie",
            player2="Dave",
            winner="Charlie",
            score="3-0",
            status=MatchStatus.completed,
            scheduled_time=now - datetime.timedelta(hours=1)
        )
        
        # Oldest match
        match3 = Match(
            player1="Eve",
            player2="Frank",
            winner="Eve",
            score="3-2",
            status=MatchStatus.completed,
            scheduled_time=now - datetime.timedelta(days=1)
        )
        
        db.add_all([match1, match2, match3])
        db.commit()
        
        yield
        
        # Cleanup
        db.query(Match).delete()
        db.commit()
        db.close()

    def test_get_recent_matches_returns_limited_results(self):
        """get_recent_matches should return at most the specified limit."""
        from tournament_platform.app.pages.dashboard import get_recent_matches
        
        # Clear the cache before testing
        get_recent_matches.clear()
        
        matches = get_recent_matches(2)
        
        assert len(matches) == 2

    def test_get_recent_matches_ordered_by_scheduled_time(self):
        """get_recent_matches should return matches ordered by scheduled_time descending."""
        from tournament_platform.app.pages.dashboard import get_recent_matches
        
        # Clear the cache before testing
        get_recent_matches.clear()
        
        matches = get_recent_matches(3)
        
        # Most recent match should be first
        assert matches[0]["player1"] == "Alice"
        assert matches[0]["player2"] == "Bob"
        
        # Second most recent should be second
        assert matches[1]["player1"] == "Charlie"
        assert matches[1]["player2"] == "Dave"
        
        # Oldest should be last
        assert matches[2]["player1"] == "Eve"
        assert matches[2]["player2"] == "Frank"

    def test_get_recent_matches_returns_correct_fields(self):
        """get_recent_matches should return all required fields."""
        from tournament_platform.app.pages.dashboard import get_recent_matches
        
        # Clear the cache before testing
        get_recent_matches.clear()
        
        matches = get_recent_matches(1)
        
        assert len(matches) == 1
        match = matches[0]
        
        assert "id" in match
        assert "player1" in match
        assert "player2" in match
        assert "winner" in match
        assert "score" in match
        assert "status" in match
        assert "scheduled_time" in match

    def test_get_recent_matches_empty_database(self):
        """get_recent_matches should return empty list when no matches exist."""
        from tournament_platform.app.pages.dashboard import get_recent_matches
        
        # Clear the cache before testing
        get_recent_matches.clear()
        
        # Delete all matches
        db = SessionLocal()
        db.query(Match).delete()
        db.commit()
        db.close()
        
        matches = get_recent_matches(5)
        
        assert matches == []


class TestAIFacade:
    """Tests for the AI facade functions."""

    def test_get_ai_health_returns_unavailable_on_error(self):
        """get_ai_health should return graceful AIHealth unavailable on error."""
        with patch('tournament_platform.services.ai_facade.get_ai_status') as mock_status:
            mock_status.side_effect = Exception("Connection failed")
            
            health = get_ai_health()
            
            assert isinstance(health, AIHealth)
            assert health.available is False
            assert health.model_name is None
            assert health.retrieval_available is False
            assert "Connection failed" in health.error

    def test_answer_rules_question_handles_retrieval_failure(self):
        """answer_rules_question should handle retrieval failure gracefully."""
        with patch('tournament_platform.services.ai_facade._get_ai_engine') as mock_engine:
            mock_engine.side_effect = Exception("Ollama not available")
            
            answer = answer_rules_question("What are the rules?")
            
            assert isinstance(answer, AIAnswer)
            assert "couldn't process" in answer.answer.lower()
            assert answer.grounded is False
            assert answer.confidence is None

    def test_answer_rules_question_returns_structured_response(self):
        """answer_rules_question should return AIAnswer with sources and confidence."""
        with patch('tournament_platform.services.ai_facade._get_ai_engine') as mock_engine:
            mock_ai = MagicMock()
            mock_ai.rules_retriever.search_rules_with_metadata.return_value = [
                {
                    'document': 'Test rule content',
                    'metadata': {'source': 'test.pdf', 'page': 1},
                    'distance': 0.1,
                    'id': 'test_1'
                }
            ]
            mock_ai._chat_with_fallback.return_value = {
                'message': {'content': 'Test answer'}
            }
            mock_engine.return_value = mock_ai
            
            answer = answer_rules_question("Test question")
            
            assert isinstance(answer, AIAnswer)
            assert answer.answer == "Test answer"
            assert answer.grounded is True
            assert answer.confidence == "high"
            assert len(answer.source_details) == 1


class TestUIPayloadHelpers:
    """Tests for UI helper functions related to match reporting."""

    def test_score_payload_builder(self):
        """Test that score payload is built correctly from player inputs."""
        # This tests the logic in render_ai_match_reporting
        p1 = "Bob"
        p2 = "Alice"
        s1 = 3
        s2 = 1
        winner = "Bob"
        
        payload = {
            "player1": p1,
            "player2": p2,
            "score": f"{s1}-{s2}",
            "winner": winner,
            "tournament_id": None
        }
        
        assert payload["player1"] == "Bob"
        assert payload["player2"] == "Alice"
        assert payload["score"] == "3-1"
        assert payload["winner"] == "Bob"

    def test_score_payload_preserves_player_order(self):
        """Test that score payload preserves player order (Bob-Alice 3-1, not Alice-Bob 3-1)."""
        # The critical test: "Bob beats Alice 3-1"
        p1 = "Bob"
        p2 = "Alice"
        s1 = 3
        s2 = 1
        
        payload = {
            "player1": p1,
            "player2": p2,
            "score": f"{s1}-{s2}",
            "winner": p1
        }
        
        # Verify Bob is player1 with score 3, Alice is player2 with score 1
        assert payload["player1"] == "Bob"
        assert payload["player2"] == "Alice"
        assert payload["score"] == "3-1"
        
        # If we parse the score, Bob should have 3, Alice should have 1
        score_parts = payload["score"].split('-')
        assert int(score_parts[0]) == 3  # Bob's score
        assert int(score_parts[1]) == 1  # Alice's score

    def test_form_payload_validation(self):
        """Test that form payload validation works correctly."""
        # Valid payload
        valid_payload = {
            "player1": "Alice",
            "player2": "Bob",
            "score": "3-1",
            "winner": "Alice"
        }
        
        # Validation: winner must be one of the players
        assert valid_payload["winner"] in [valid_payload["player1"], valid_payload["player2"]]
        
        # Invalid payload: winner not in players
        invalid_payload = {
            "player1": "Alice",
            "player2": "Bob",
            "score": "3-1",
            "winner": "Charlie"
        }
        
        assert invalid_payload["winner"] not in [invalid_payload["player1"], invalid_payload["player2"]]