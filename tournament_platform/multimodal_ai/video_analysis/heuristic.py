"""
Heuristic-based video analyzer for table tennis.

This is the Phase 2 implementation using simple computer vision techniques.
"""

import logging
from typing import Optional, List, Tuple

from tournament_platform.services.video_scorekeeper import (
    VideoAnalysisResult,
    CalibrationConfig,
    BallTrackPoint,
    RallyEvent,
)

logger = logging.getLogger(__name__)


class HeuristicVideoAnalyzer:
    """
    Heuristic-based video analyzer.
    
    Uses simple computer vision techniques:
    - Color-based ball detection (orange/yellow)
    - Motion tracking
    - Bounce detection from trajectory changes
    - Net crossing detection
    """
    
    def __init__(self, frame_skip: int = 2):
        """
        Initialize the heuristic analyzer.
        
        Args:
            frame_skip: Process every Nth frame for performance
        """
        self.frame_skip = frame_skip
    
    def analyze(
        self,
        video_path: str,
        calibration: Optional[CalibrationConfig] = None
    ) -> VideoAnalysisResult:
        """
        Analyze video and return events.
        
        This is a wrapper around the analyze_video_clip function.
        """
        from tournament_platform.services.video_scorekeeper import analyze_video_clip
        return analyze_video_clip(video_path, calibration, self.frame_skip)
    
    def detect_ball(self, frame) -> Optional[Tuple[float, float, float]]:
        """
        Detect ball in a single frame using color-based heuristic.
        
        Args:
            frame: Video frame (numpy array)
            
        Returns:
            (x, y, confidence) or None
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
        
        # Confidence based on contour area
        confidence = min(cv2.contourArea(largest) / 10000.0, 1.0)
        
        return (float(x), float(y), confidence)
    
    def detect_events(
        self,
        trajectory: List[BallTrackPoint],
        calibration: Optional[CalibrationConfig] = None
    ) -> List[RallyEvent]:
        """
        Detect events from ball trajectory.
        
        Args:
            trajectory: List of ball positions
            calibration: Optional calibration config
            
        Returns:
            List of detected events
        """
        events: List[RallyEvent] = []
        
        if len(trajectory) < 3:
            return events
        
        # Add rally start
        events.append(RallyEvent(
            event_type="rally_start",
            timestamp=trajectory[0].timestamp,
            frame_number=trajectory[0].frame_number,
            x=trajectory[0].x,
            y=trajectory[0].y,
            confidence=0.9,
        ))
        
        # Get table height for bounce detection
        table_height = calibration.frame_height if calibration else 480.0
        
        # Detect bounces and net hits
        for i in range(1, len(trajectory) - 1):
            prev = trajectory[i - 1]
            curr = trajectory[i]
            next_p = trajectory[i + 1]
            
            # Check for bounce
            if self._detect_bounce(prev, curr, next_p, table_height):
                events.append(RallyEvent(
                    event_type="bounce",
                    timestamp=curr.timestamp,
                    frame_number=curr.frame_number,
                    x=curr.x,
                    y=curr.y,
                    confidence=0.7,
                ))
            
            # Check for net cross
            if calibration and calibration.net_line_y:
                if self._detect_net_cross(prev, curr, calibration.net_line_y):
                    events.append(RallyEvent(
                        event_type="net_hit",
                        timestamp=curr.timestamp,
                        frame_number=curr.frame_number,
                        x=curr.x,
                        y=curr.y,
                        confidence=0.6,
                    ))
        
        # Add rally end
        if trajectory:
            last = trajectory[-1]
            events.append(RallyEvent(
                event_type="rally_end",
                timestamp=last.timestamp,
                frame_number=last.frame_number,
                x=last.x,
                y=last.y,
                confidence=0.8,
            ))
        
        return events
    
    def _detect_bounce(
        self,
        prev_point: BallTrackPoint,
        curr_point: BallTrackPoint,
        next_point: BallTrackPoint,
        table_height: float = 480.0
    ) -> bool:
        """Detect bounce based on trajectory change."""
        # Check if near table height
        if not (table_height * 0.3 < curr_point.y < table_height * 0.8):
            return False
        
        # Check for direction change
        prev_vy = curr_point.y - prev_point.y
        next_vy = next_point.y - curr_point.y
        
        # Bounce: going down then up (or vice versa)
        if prev_vy * next_vy < 0 and abs(prev_vy) > 5 and abs(next_vy) > 5:
            return True
        
        return False
    
    def _detect_net_cross(
        self,
        prev_point: BallTrackPoint,
        curr_point: BallTrackPoint,
        net_y: float
    ) -> bool:
        """Detect if ball crosses the net line."""
        return (prev_point.y < net_y and curr_point.y >= net_y) or \
               (prev_point.y >= net_y and curr_point.y < net_y)