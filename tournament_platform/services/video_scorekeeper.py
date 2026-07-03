"""
Video Scorekeeper Service - AI-assisted video score suggestions with confirmation.

This module provides:
- Video analysis (read-only, no DB writes)
- Point winner suggestions with confidence and evidence
- Safe state management for confirmed points
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum
import logging
import math

logger = logging.getLogger(__name__)


class SuggestedWinner(str, Enum):
    """Suggested point winner."""
    PLAYER_A = "player_a"
    PLAYER_B = "player_b"
    UNKNOWN = "unknown"


@dataclass
class CalibrationConfig:
    """Manual calibration for table geometry."""
    table_corners: Optional[List[Tuple[float, float]]] = None  # 4 points (x, y)
    net_line_y: Optional[float] = None  # Y-coordinate of net
    player_a_side: str = "top"  # "top" or "bottom"
    player_b_side: str = "bottom"
    frame_width: int = 640
    frame_height: int = 480


@dataclass
class BallTrackPoint:
    """Single ball position in a frame."""
    frame_number: int
    x: float
    y: float
    timestamp: float
    confidence: float


@dataclass
class RallyEvent:
    """Detected event in a rally."""
    event_type: str  # "bounce", "net_hit", "rally_start", "rally_end"
    timestamp: float
    frame_number: int
    x: Optional[float] = None
    y: Optional[float] = None
    confidence: float = 0.0
    player_side: Optional[str] = None  # "a" or "b" if determinable


@dataclass
class VideoAnalysisResult:
    """Result of video analysis (read-only)."""
    video_path: str
    duration_seconds: float
    fps: float
    frame_count: int
    ball_trajectory: List[BallTrackPoint]
    events: List[RallyEvent]
    calibration: Optional[CalibrationConfig] = None


@dataclass
class VideoScoreSuggestion:
    """AI suggestion for point winner (read-only, no DB writes)."""
    suggested_winner: SuggestedWinner
    confidence: float  # 0.0 - 1.0
    reason: str
    evidence_timestamps: List[float]
    detected_events: List[RallyEvent]
    needs_review: bool  # True if confidence < threshold
    raw_analysis: Optional[VideoAnalysisResult] = None


@dataclass
class ConfirmedPoint:
    """A point that has been confirmed by user."""
    match_id: int
    point_number: int
    winner: str  # "player_a" or "player_b"
    timestamp: float
    source: str  # "ai_suggested" or "manual_override"
    evidence: List[RallyEvent]


# ============================================================================
# Video Analysis Implementation
# ============================================================================

def _detect_ball_in_frame(frame) -> Optional[Tuple[float, float, float]]:
    """
    Detect ball in a single frame using color-based heuristic.
    
    Looks for orange/yellow ping pong ball.
    
    Returns:
        (x, y, confidence) or None if not detected
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    
    # Convert to HSV for color detection
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # Define orange/yellow range for ping pong ball
    lower_orange = np.array([5, 100, 100])
    upper_orange = np.array([25, 255, 255])
    lower_yellow = np.array([25, 100, 100])
    upper_yellow = np.array([40, 255, 255])
    
    # Create masks
    mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
    mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)
    mask = cv2.bitwise_or(mask_orange, mask_yellow)
    
    # Morphological operations to clean up
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None
    
    # Find largest contour (likely the ball)
    largest = max(contours, key=cv2.contourArea)
    
    if cv2.contourArea(largest) < 100:  # Too small, likely noise
        return None
    
    # Get center
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    
    x = M["m10"] / M["m00"]
    y = M["m01"] / M["m00"]
    
    # Confidence based on contour area (larger = more confident)
    confidence = min(cv2.contourArea(largest) / 10000.0, 1.0)
    
    return (float(x), float(y), confidence)


def _detect_bounce(
    prev_point: BallTrackPoint,
    curr_point: BallTrackPoint,
    next_point: BallTrackPoint,
    table_height: float = 480.0
) -> bool:
    """
    Detect bounce based on trajectory change.
    
    A bounce is detected when the ball changes direction suddenly
    near table height.
    """
    # Check if near table height (y close to table surface)
    if not (table_height * 0.3 < curr_point.y < table_height * 0.8):
        return False
    
    # Check for direction change (velocity sign change)
    prev_vy = curr_point.y - prev_point.y
    next_vy = next_point.y - curr_point.y
    
    # Bounce: going down then up (or vice versa)
    if prev_vy * next_vy < 0 and abs(prev_vy) > 5 and abs(next_vy) > 5:
        return True
    
    return False


def _detect_net_cross(
    prev_point: BallTrackPoint,
    curr_point: BallTrackPoint,
    net_y: float
) -> bool:
    """Detect if ball crosses the net line."""
    return (prev_point.y < net_y and curr_point.y >= net_y) or \
           (prev_point.y >= net_y and curr_point.y < net_y)


def analyze_video_clip(
    video_path: str,
    calibration: Optional[CalibrationConfig] = None,
    frame_skip: int = 2
) -> VideoAnalysisResult:
    """
    Extract events from video using heuristic analysis.
    
    Args:
        video_path: Path to video file
        calibration: Optional calibration config
        frame_skip: Process every Nth frame for performance
        
    Returns:
        VideoAnalysisResult with detected events
    """
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV not installed - video analysis unavailable")
        return VideoAnalysisResult(
            video_path=video_path,
            duration_seconds=0.0,
            fps=30.0,
            frame_count=0,
            ball_trajectory=[],
            events=[],
            calibration=calibration,
        )
    
    # Open video
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        logger.error(f"Could not open video: {video_path}")
        return VideoAnalysisResult(
            video_path=video_path,
            duration_seconds=0.0,
            fps=30.0,
            frame_count=0,
            ball_trajectory=[],
            events=[],
            calibration=calibration,
        )
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps
    
    ball_trajectory: List[BallTrackPoint] = []
    events: List[RallyEvent] = []
    
    # Get frame dimensions
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Update calibration with actual frame size
    if calibration is None:
        calibration = CalibrationConfig(
            frame_width=frame_width,
            frame_height=frame_height,
        )
    
    # Process frames
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_idx % frame_skip == 0:
            result = _detect_ball_in_frame(frame)
            
            if result:
                x, y, confidence = result
                timestamp = frame_idx / fps
                
                ball_trajectory.append(BallTrackPoint(
                    frame_number=frame_idx,
                    x=x,
                    y=y,
                    timestamp=timestamp,
                    confidence=confidence,
                ))
        
        frame_idx += 1
    
    cap.release()
    
    # Detect events from trajectory
    if len(ball_trajectory) >= 3:
        # Add rally start
        events.append(RallyEvent(
            event_type="rally_start",
            timestamp=ball_trajectory[0].timestamp,
            frame_number=ball_trajectory[0].frame_number,
            x=ball_trajectory[0].x,
            y=ball_trajectory[0].y,
            confidence=0.9,
        ))
        
        # Detect bounces and net hits
        for i in range(1, len(ball_trajectory) - 1):
            prev = ball_trajectory[i - 1]
            curr = ball_trajectory[i]
            next_p = ball_trajectory[i + 1]
            
            # Check for bounce
            if _detect_bounce(prev, curr, next_p, frame_height):
                events.append(RallyEvent(
                    event_type="bounce",
                    timestamp=curr.timestamp,
                    frame_number=curr.frame_number,
                    x=curr.x,
                    y=curr.y,
                    confidence=0.7,
                ))
            
            # Check for net cross
            if calibration.net_line_y:
                if _detect_net_cross(prev, curr, calibration.net_line_y):
                    events.append(RallyEvent(
                        event_type="net_hit",
                        timestamp=curr.timestamp,
                        frame_number=curr.frame_number,
                        x=curr.x,
                        y=curr.y,
                        confidence=0.6,
                    ))
        
        # Add rally end
        if ball_trajectory:
            last = ball_trajectory[-1]
            events.append(RallyEvent(
                event_type="rally_end",
                timestamp=last.timestamp,
                frame_number=last.frame_number,
                x=last.x,
                y=last.y,
                confidence=0.8,
            ))
    
    return VideoAnalysisResult(
        video_path=video_path,
        duration_seconds=duration,
        fps=fps,
        frame_count=frame_count,
        ball_trajectory=ball_trajectory,
        events=events,
        calibration=calibration,
    )


def suggest_point_winner(
    analysis_result: VideoAnalysisResult,
    calibration: Optional[CalibrationConfig] = None,
    confidence_threshold: float = 0.7
) -> VideoScoreSuggestion:
    """
    Map analysis results to point suggestion.
    
    Args:
        analysis_result: Result from video analysis
        calibration: Optional calibration for side detection
        confidence_threshold: Below this = needs_review
        
    Returns:
        VideoScoreSuggestion with winner and evidence
    """
    events = analysis_result.events
    evidence_timestamps = [e.timestamp for e in events if e.event_type in ("bounce", "net_hit", "rally_end")]
    
    # Determine winner based on last event
    # If ball ends on player A's side, they likely won
    # This is a simplified heuristic - real implementation would be more complex
    
    if not events:
        return VideoScoreSuggestion(
            suggested_winner=SuggestedWinner.UNKNOWN,
            confidence=0.0,
            reason="No events detected in video. Please use manual scoring.",
            evidence_timestamps=evidence_timestamps,
            detected_events=events,
            needs_review=True,
            raw_analysis=analysis_result,
        )
    
    # Check for net hits (fault)
    net_hits = [e for e in events if e.event_type == "net_hit"]
    if net_hits:
        return VideoScoreSuggestion(
            suggested_winner=SuggestedWinner.UNKNOWN,
            confidence=0.3,
            reason="Net contact detected. Please review the rally.",
            evidence_timestamps=evidence_timestamps,
            detected_events=events,
            needs_review=True,
            raw_analysis=analysis_result,
        )
    
    # Simple heuristic: if we have bounces, suggest based on last ball position
    # This is a placeholder - real implementation would use calibration
    if analysis_result.ball_trajectory:
        last_ball = analysis_result.ball_trajectory[-1]
        
        if calibration and calibration.net_line_y:
            # Determine which side based on calibration
            if last_ball.y < calibration.net_line_y:
                winner = SuggestedWinner.PLAYER_A if calibration.player_a_side == "top" else SuggestedWinner.PLAYER_B
            else:
                winner = SuggestedWinner.PLAYER_B if calibration.player_b_side == "bottom" else SuggestedWinner.PLAYER_A
            
            confidence = 0.5  # Low confidence for heuristic
            reason = f"Ball ended on {'Player A' if winner == SuggestedWinner.PLAYER_A else 'Player B'} side based on position."
        else:
            winner = SuggestedWinner.UNKNOWN
            confidence = 0.0
            reason = "No calibration provided. Cannot determine player side."
    else:
        winner = SuggestedWinner.UNKNOWN
        confidence = 0.0
        reason = "No ball trajectory detected."
    
    return VideoScoreSuggestion(
        suggested_winner=winner,
        confidence=confidence,
        reason=reason,
        evidence_timestamps=evidence_timestamps,
        detected_events=events,
        needs_review=confidence < confidence_threshold,
        raw_analysis=analysis_result,
    )


def apply_confirmed_point(
    match_manager,
    suggestion: VideoScoreSuggestion,
    winner_override: Optional[str] = None
) -> ConfirmedPoint:
    """
    Update local score state with confirmed point.
    
    This function only updates in-memory MatchManager state.
    It does NOT write to the database.
    
    Args:
        match_manager: MatchManager instance from session state
        suggestion: The confirmed suggestion
        winner_override: Optional manual override ("player_a" or "player_b")
        
    Returns:
        ConfirmedPoint record
    """
    winner = winner_override or suggestion.suggested_winner.value
    
    if winner not in ("player_a", "player_b"):
        raise ValueError(f"Invalid winner: {winner}")
    
    # Update MatchManager state
    if winner == "player_a":
        match_manager._add_point("A")
    else:
        match_manager._add_point("B")
    
    # Create confirmed point record
    point_number = len(match_manager.state.match_history)
    
    return ConfirmedPoint(
        match_id=0,  # Will be set from session state
        point_number=point_number,
        winner=winner,
        timestamp=0.0,  # Will be set from analysis
        source="manual_override" if winner_override else "ai_suggested",
        evidence=suggestion.detected_events,
    )


def build_video_score_state(match_id: int) -> dict:
    """
    Initialize state for a match.
    
    Read-only from database - no mutations.
    
    Args:
        match_id: Database match ID
        
    Returns:
        Initial state dict
    """
    return {
        "match_id": match_id,
        "points": [],
        "current_suggestion": None,
    }


def validate_video_score_state(state: dict) -> bool:
    """
    Validate state consistency.
    
    Read-only validation.
    
    Args:
        state: State dict to validate
        
    Returns:
        True if valid
    """
    if "match_id" not in state:
        return False
    if "points" not in state:
        return False
    return True