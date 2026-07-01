"""Audio feature extraction interface."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class AudioFeatures:
    """Extracted audio features."""
    transcript: Optional[str] = None
    speaker_id: Optional[str] = None
    intent: Optional[str] = None
    anti_spoof_score: Optional[float] = None
    acoustic_events: List[str] = None
    duration_seconds: Optional[float] = None
    sample_rate: Optional[int] = None
    
    def __post_init__(self):
        if self.acoustic_events is None:
            self.acoustic_events = []


class AudioFeatureExtractor(ABC):
    """Abstract base class for audio feature extraction."""
    
    @abstractmethod
    def extract_transcript(self, audio_path: str) -> str:
        """Extract transcript from audio file."""
        pass
    
    @abstractmethod
    def extract_speaker_id(self, audio_path: str) -> Optional[str]:
        """Extract speaker identification."""
        pass
    
    @abstractmethod
    def extract_intent(self, transcript: str) -> Optional[str]:
        """Extract intent/command from transcript."""
        pass
    
    @abstractmethod
    def extract_anti_spoof_score(self, audio_path: str) -> Optional[float]:
        """Extract anti-spoofing score."""
        pass
    
    def extract_all(self, audio_path: str) -> AudioFeatures:
        """Extract all available features from audio."""
        transcript = self.extract_transcript(audio_path)
        return AudioFeatures(
            transcript=transcript,
            speaker_id=self.extract_speaker_id(audio_path),
            intent=self.extract_intent(transcript) if transcript else None,
            anti_spoof_score=self.extract_anti_spoof_score(audio_path),
        )