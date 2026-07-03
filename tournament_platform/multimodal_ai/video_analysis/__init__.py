"""
Video Analysis module for table tennis ball detection and event spotting.

This module provides:
- Abstract interface for video analysis (VideoAnalyzer)
- Heuristic-based implementation (HeuristicVideoAnalyzer)
- Pluggable model interface for future ML models
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from dataclasses import dataclass

# Import from video_scorekeeper service
from tournament_platform.services.video_scorekeeper import (
    VideoAnalysisResult,
    CalibrationConfig,
    BallTrackPoint,
    RallyEvent,
)


class VideoAnalyzer(ABC):
    """
    Abstract interface for video analysis - allows pluggable models.
    
    Implementations can use:
    - Heuristic-based detection (current)
    - TTNet-style models
    - YOLO/Ultralytics models
    - Custom trained models
    """
    
    @abstractmethod
    def analyze(
        self,
        video_path: str,
        calibration: Optional[CalibrationConfig] = None
    ) -> VideoAnalysisResult:
        """
        Analyze video and return events.
        
        Args:
            video_path: Path to video file
            calibration: Optional calibration config
            
        Returns:
            VideoAnalysisResult with detected events
        """
        pass
    
    @abstractmethod
    def detect_ball(self, frame) -> Optional[Tuple[float, float, float]]:
        """
        Detect ball in a single frame.
        
        Args:
            frame: Video frame (numpy array)
            
        Returns:
            (x, y, confidence) or None
        """
        pass
    
    @abstractmethod
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
        pass


# Import implementations
from .heuristic import HeuristicVideoAnalyzer
from .model_loader import ModelLoader, ModelBasedAnalyzer

__all__ = [
    "VideoAnalyzer",
    "HeuristicVideoAnalyzer",
    "ModelLoader",
    "ModelBasedAnalyzer",
    "VideoAnalysisResult",
    "CalibrationConfig",
    "BallTrackPoint",
    "RallyEvent",
]