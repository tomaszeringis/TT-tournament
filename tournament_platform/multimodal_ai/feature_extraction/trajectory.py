"""Ball trajectory feature extraction interface."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class BallPoint3D:
    """3D ball position."""
    x: float
    y: float
    z: float
    timestamp: float
    confidence: float


@dataclass
class TrajectoryFeatures:
    """Extracted trajectory features."""
    points_2d: List[Tuple[float, float, float]] = None  # (x, y, timestamp)
    points_3d: List[BallPoint3D] = None
    speed: List[float] = None
    bounce_points: List[Tuple[float, float, float]] = None
    spin_proxy: Optional[float] = None
    
    def __post_init__(self):
        if self.points_2d is None:
            self.points_2d = []
        if self.points_3d is None:
            self.points_3d = []
        if self.speed is None:
            self.speed = []
        if self.bounce_points is None:
            self.bounce_points = []


class TrajectoryFeatureExtractor(ABC):
    """Abstract base class for trajectory feature extraction."""
    
    @abstractmethod
    def reconstruct_2d_trajectory(self, video_path: str) -> List[Tuple[float, float, float]]:
        """Reconstruct 2D ball trajectory from video."""
        pass
    
    @abstractmethod
    def reconstruct_3d_trajectory(self, video_path: str) -> List[BallPoint3D]:
        """Reconstruct 3D ball trajectory from video."""
        pass
    
    @abstractmethod
    def calculate_speed(self, trajectory: List[Tuple[float, float, float]]) -> List[float]:
        """Calculate ball speed along trajectory."""
        pass
    
    @abstractmethod
    def detect_bounce_points(self, trajectory: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
        """Detect bounce points from trajectory."""
        pass
    
    def extract_all(self, video_path: str) -> TrajectoryFeatures:
        """Extract all available trajectory features."""
        points_2d = self.reconstruct_2d_trajectory(video_path)
        return TrajectoryFeatures(
            points_2d=points_2d,
            points_3d=self.reconstruct_3d_trajectory(video_path),
            speed=self.calculate_speed(points_2d),
            bounce_points=self.detect_bounce_points(points_2d),
        )