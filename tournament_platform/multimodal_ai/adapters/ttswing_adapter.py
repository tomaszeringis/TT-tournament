"""
Adapter for TTSwing dataset.
Racket IMU/kinematics and biomechanics.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class TTSwingAdapter(BaseAdapter):
    """Adapter for TTSwing dataset."""
    
    def validate_manifest(self) -> bool:
        if not self.local_path:
            return False
        return (self.local_path / "imu").exists() or (self.local_path / "kinematics").exists()
    
    def validate_local_path(self) -> bool:
        if not self.local_path:
            return False
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": "TTSwing",
            "modality": "sensor",
            "task": "stroke_classification",
            "license": "mit",
            "commercial_allowed": True,
        }
    
    def list_samples(self) -> List[DataSample]:
        samples = []
        if not self.local_path:
            return samples
        
        imu_path = self.local_path / "imu"
        if imu_path.exists():
            for imu_file in imu_path.glob("*.csv"):
                samples.append(DataSample(
                    sample_key=imu_file.stem,
                    metadata={
                        "imu_path": str(imu_file),
                    }
                ))
        
        return samples
    
    def _get_name(self) -> str:
        return "TTSwing"
    
    def _get_modality(self) -> str:
        return "sensor"
    
    def _get_task(self) -> str:
        return "stroke_classification"
    
    def _get_license(self) -> str:
        return "mit"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://github.com/"  # Placeholder - actual URL to be added