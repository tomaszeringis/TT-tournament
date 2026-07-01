"""Feature extraction interfaces for multimodal AI."""

from .audio import AudioFeatureExtractor, AudioFeatures
from .video import VideoFeatureExtractor, VideoFeatures
from .sensor import SensorFeatureExtractor, SensorFeatures
from .trajectory import TrajectoryFeatureExtractor, TrajectoryFeatures

__all__ = [
    "AudioFeatureExtractor",
    "AudioFeatures",
    "VideoFeatureExtractor",
    "VideoFeatures",
    "SensorFeatureExtractor",
    "SensorFeatures",
    "TrajectoryFeatureExtractor",
    "TrajectoryFeatures",
]