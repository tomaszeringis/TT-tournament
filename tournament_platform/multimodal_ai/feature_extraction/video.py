"""Video feature extraction interface."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class BallDetection:
    """Ball detection result."""
    frame_number: int
    x: float
    y: float
    confidence: float
    radius: Optional[float] = None


@dataclass
class StrokeEvent:
    """Stroke event detection."""
    stroke_type: str
    start_time: float
    end_time: float
    confidence: float
    player_id: Optional[int] = None


@dataclass
class VideoFeatures:
    """Extracted video features."""
    ball_detections: List[BallDetection] = None
    bounce_events: List[Tuple[float, float]] = None
    net_events: List[Tuple[float, float]] = None
    stroke_events: List[StrokeEvent] = None
    player_poses: List[Dict[str, Any]] = None
    rally_outcomes: List[Dict[str, Any]] = None
    frame_count: Optional[int] = None
    fps: Optional[float] = None
    
    def __post_init__(self):
        if self.ball_detections is None:
            self.ball_detections = []
        if self.bounce_events is None:
            self.bounce_events = []
        if self.net_events is None:
            self.net_events = []
        if self.stroke_events is None:
            self.stroke_events = []
        if self.player_poses is None:
            self.player_poses = []
        if self.rally_outcomes is None:
            self.rally_outcomes = []


class VideoFeatureExtractor(ABC):
    """Abstract base class for video feature extraction."""
    
    @abstractmethod
    def detect_ball(self, video_path: str) -> List[BallDetection]:
        """Detect ball in video frames."""
        pass
    
    @abstractmethod
    def detect_bounce_events(self, video_path: str) -> List[Tuple[float, float]]:
        """Detect ball bounce events."""
        pass
    
    @abstractmethod
    def detect_net_events(self, video_path: str) -> List[Tuple[float, float]]:
        """Detect net events."""
        pass
    
    @abstractmethod
    def classify_strokes(self, video_path: str) -> List[StrokeEvent]:
        """Classify stroke types."""
        pass
    
    @abstractmethod
    def extract_player_pose(self, video_path: str) -> List[Dict[str, Any]]:
        """Extract player pose keypoints."""
        pass
    
    def extract_all(self, video_path: str) -> VideoFeatures:
        """Extract all available features from video."""
        return VideoFeatures(
            ball_detections=self.detect_ball(video_path),
            bounce_events=self.detect_bounce_events(video_path),
            net_events=self.detect_net_events(video_path),
            stroke_events=self.classify_strokes(video_path),
            player_poses=self.extract_player_pose(video_path),
        )