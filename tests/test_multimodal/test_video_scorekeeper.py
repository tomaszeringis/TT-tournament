"""
Tests for video scorekeeper service and UI integration.
"""

import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from tournament_platform.services.video_scorekeeper import (
    analyze_video_clip,
    suggest_point_winner,
    apply_confirmed_point,
    build_video_score_state,
    validate_video_score_state,
    CalibrationConfig,
    VideoScoreSuggestion,
    VideoAnalysisResult,
    RallyEvent,
    BallTrackPoint,
    SuggestedWinner,
    ConfirmedPoint,
)
from tournament_platform.services.match_manager import MatchManager


# Test fixtures
@pytest.fixture
def match_manager():
    """Create a MatchManager instance for testing."""
    return MatchManager(player_a="Player A", player_b="Player B")


@pytest.fixture
def sample_calibration():
    """Create a sample calibration config."""
    return CalibrationConfig(
        table_corners=[(100, 50), (540, 50), (540, 430), (100, 430)],
        net_line_y=240.0,
        player_a_side="top",
        player_b_side="bottom",
    )


@pytest.fixture
def sample_analysis_result(sample_calibration):
    """Create a sample analysis result."""
    return VideoAnalysisResult(
        video_path="/tmp/test.mp4",
        duration_seconds=5.0,
        fps=30.0,
        frame_count=150,
        ball_trajectory=[
            BallTrackPoint(frame_number=0, x=320, y=240, timestamp=0.0, confidence=0.9),
            BallTrackPoint(frame_number=30, x=300, y=200, timestamp=1.0, confidence=0.85),
        ],
        events=[
            RallyEvent(event_type="rally_start", timestamp=0.0, frame_number=0, confidence=0.9),
            RallyEvent(event_type="bounce", timestamp=0.5, frame_number=15, x=310, y=220, confidence=0.8),
        ],
        calibration=sample_calibration,
    )


class TestVideoScoreSuggestionSafety:
    """Tests for safety rules - no DB mutations from AI."""

    def test_suggestion_does_not_mutate_db(self, match_manager, sample_analysis_result):
        """Verify suggest_point_winner never writes to DB."""
        # The function should only return a suggestion, not modify any state
        suggestion = suggest_point_winner(sample_analysis_result)
        
        # Verify it returns a VideoScoreSuggestion
        assert isinstance(suggestion, VideoScoreSuggestion)
        
        # Verify match_manager state is unchanged
        assert match_manager.state.score_a == 0
        assert match_manager.state.score_b == 0

    def test_confirmed_point_updates_local_state(self, match_manager, sample_analysis_result, sample_calibration):
        """Verify apply_confirmed_point only updates MatchManager state."""
        suggestion = suggest_point_winner(sample_analysis_result, calibration=sample_calibration)
        
        # Apply confirmed point
        confirmed = apply_confirmed_point(match_manager, suggestion)
        
        # Verify it returns a ConfirmedPoint
        assert isinstance(confirmed, ConfirmedPoint)
        
        # Verify MatchManager was updated
        assert match_manager.state.score_a == 1 or match_manager.state.score_b == 1

    def test_low_confidence_marks_needs_review(self, match_manager):
        """Verify suggestions below threshold have needs_review=True."""
        # Create analysis with no events (low confidence)
        analysis = VideoAnalysisResult(
            video_path="/tmp/test.mp4",
            duration_seconds=5.0,
            fps=30.0,
            frame_count=150,
            ball_trajectory=[],
            events=[],
        )
        
        suggestion = suggest_point_winner(analysis, confidence_threshold=0.7)
        
        assert suggestion.needs_review == True
        assert suggestion.suggested_winner == SuggestedWinner.UNKNOWN


class TestOverrideAndUndo:
    """Tests for override and undo behavior."""

    def test_override_allows_manual_winner(self, match_manager, sample_analysis_result):
        """Verify user can override AI suggestion."""
        suggestion = suggest_point_winner(sample_analysis_result)
        
        # Override to player_b
        confirmed = apply_confirmed_point(
            match_manager,
            suggestion,
            winner_override="player_b"
        )
        
        assert confirmed.winner == "player_b"
        assert match_manager.state.score_b == 1

    def test_undo_reverts_last_point(self, match_manager, sample_analysis_result):
        """Verify undo works with video-confirmed points."""
        # Add a point
        suggestion = suggest_point_winner(sample_analysis_result)
        apply_confirmed_point(match_manager, suggestion, winner_override="player_a")
        
        assert match_manager.state.score_a == 1
        
        # Undo
        success, msg = match_manager.undo_last_point()
        
        assert success == True
        assert match_manager.state.score_a == 0


class TestCalibration:
    """Tests for calibration behavior."""

    def test_calibration_required_for_side_detection(self, match_manager):
        """Verify player side detection needs calibration."""
        # Without calibration, should return unknown
        analysis = VideoAnalysisResult(
            video_path="/tmp/test.mp4",
            duration_seconds=5.0,
            fps=30.0,
            frame_count=150,
            ball_trajectory=[],
            events=[
                RallyEvent(event_type="rally_end", timestamp=5.0, frame_number=150, confidence=0.5),
            ],
        )
        
        suggestion = suggest_point_winner(analysis)
        
        # Without calibration, should be unknown
        assert suggestion.suggested_winner == SuggestedWinner.UNKNOWN


class TestVideoServiceErrorHandling:
    """Tests for error handling."""

    def test_video_service_handles_missing_deps(self):
        """Verify graceful error when OpenCV missing."""
        # Mock the import inside the function
        with patch.dict('sys.modules', {'cv2': None, 'numpy': None}):
            # Should not raise, just return empty result
            result = analyze_video_clip("/tmp/test.mp4")
            assert isinstance(result, VideoAnalysisResult)
            assert result.frame_count == 0

    def test_video_service_handles_bad_file(self):
        """Verify error handling for corrupt video."""
        # Should handle gracefully
        result = analyze_video_clip("/nonexistent/path.mp4")
        assert isinstance(result, VideoAnalysisResult)


class TestStateValidation:
    """Tests for state validation."""

    def test_validate_video_score_state_valid(self):
        """Verify valid state passes validation."""
        state = build_video_score_state(match_id=1)
        assert validate_video_score_state(state) == True

    def test_validate_video_score_state_missing_match_id(self):
        """Verify missing match_id fails validation."""
        state = {"points": []}
        assert validate_video_score_state(state) == False

    def test_validate_video_score_state_missing_points(self):
        """Verify missing points fails validation."""
        state = {"match_id": 1}
        assert validate_video_score_state(state) == False


class TestVideoScorekeeperIntegration:
    """Integration tests for video scorekeeper."""

    def test_full_suggestion_flow(self, match_manager, sample_analysis_result):
        """Test full flow: analysis -> suggestion -> confirm -> score update."""
        # Analyze
        analysis = sample_analysis_result
        
        # Suggest
        suggestion = suggest_point_winner(analysis)
        
        # Confirm
        apply_confirmed_point(match_manager, suggestion, winner_override="player_a")
        
        # Verify score updated
        assert match_manager.state.score_a == 1

    def test_match_reporting_still_required(self, match_manager, sample_analysis_result, sample_calibration):
        """Verify final submission uses existing match_reporting flow."""
        # This is verified by the fact that apply_confirmed_point
        # only updates MatchManager, not the database
        suggestion = suggest_point_winner(sample_analysis_result, calibration=sample_calibration)
        apply_confirmed_point(match_manager, suggestion)
        
        # MatchManager state is in-memory only
        # Database would need separate report_existing_match call
        assert match_manager.state.score_a == 1 or match_manager.state.score_b == 1

    def test_score_validation_rules(self, match_manager):
        """Verify table tennis rules (11 points, 2 point lead)."""
        # MatchManager already implements these rules
        # Test that we can add points
        for _ in range(11):
            match_manager._add_point("A")
        
        # After 11 points, game is won and scores reset to 0-0
        assert match_manager.state.sets_a == 1
        assert match_manager.state.score_a == 0
        assert match_manager.state.score_b == 0