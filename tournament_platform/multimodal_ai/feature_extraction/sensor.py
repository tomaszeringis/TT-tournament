"""Sensor/IMU feature extraction interface."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class SwingPhase:
    """Swing phase detection."""
    phase: str  # 'prep', 'backswing', 'forward', 'followthrough'
    start_time: float
    end_time: float
    confidence: float


@dataclass
class KinematicFeatures:
    """Kinematic features from IMU."""
    acceleration: List[float]
    angular_velocity: List[float]
    orientation: Optional[List[float]] = None
    timestamp: Optional[float] = None


@dataclass
class SensorFeatures:
    """Extracted sensor features."""
    swing_phases: List[SwingPhase] = None
    acceleration: List[KinematicFeatures] = None
    sample_rate: Optional[int] = None
    duration_seconds: Optional[float] = None
    
    def __post_init__(self):
        if self.swing_phases is None:
            self.swing_phases = []
        if self.acceleration is None:
            self.acceleration = []


class SensorFeatureExtractor(ABC):
    """Abstract base class for sensor feature extraction."""
    
    @abstractmethod
    def detect_swing_phases(self, sensor_data_path: str) -> List[SwingPhase]:
        """Detect swing phases from IMU data."""
        pass
    
    @abstractmethod
    def extract_kinematics(self, sensor_data_path: str) -> List[KinematicFeatures]:
        """Extract kinematic features from IMU data."""
        pass
    
    def extract_all(self, sensor_data_path: str) -> SensorFeatures:
        """Extract all available features from sensor data."""
        return SensorFeatures(
            swing_phases=self.detect_swing_phases(sensor_data_path),
            acceleration=self.extract_kinematics(sensor_data_path),
        )