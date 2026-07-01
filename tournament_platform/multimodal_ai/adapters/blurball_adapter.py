"""
Adapter for BlurBall dataset.
Fast blurred ball tracking.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class BlurBallAdapter(BaseAdapter):
    """Adapter for BlurBall dataset."""
    
    def validate_manifest(self) -> bool:
        if not self.local_path:
            return False
        return (self.local_path / "videos").exists() or (self.local_path / "annotations").exists()
    
    def validate_local_path(self) -> bool:
        if not self.local_path:
            return False
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": "BlurBall",
            "modality": "video",
            "task": "ball_detection",
            "license": "mit",
            "commercial_allowed": True,
        }
    
    def list_samples(self) -> List[DataSample]:
        samples = []
        if not self.local_path:
            return samples
        
        videos_path = self.local_path / "videos"
        if videos_path.exists():
            for video_file in videos_path.glob("*.mp4"):
                samples.append(DataSample(
                    sample_key=video_file.stem,
                    metadata={
                        "video_path": str(video_file),
                    }
                ))
        
        return samples
    
    def _get_name(self) -> str:
        return "BlurBall"
    
    def _get_modality(self) -> str:
        return "video"
    
    def _get_task(self) -> str:
        return "ball_detection"
    
    def _get_license(self) -> str:
        return "mit"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://github.com/"  # Placeholder - actual URL to be added