"""
Adapter for TT3D dataset.
3D ball trajectory reconstruction.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class TT3DAdapter(BaseAdapter):
    """Adapter for TT3D dataset."""
    
    def validate_manifest(self) -> bool:
        if not self.local_path:
            return False
        return (self.local_path / "trajectories").exists() or (self.local_path / "3d_data").exists()
    
    def validate_local_path(self) -> bool:
        if not self.local_path:
            return False
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": "TT3D",
            "modality": "trajectory",
            "task": "trajectory_reconstruction",
            "license": "mit",
            "commercial_allowed": True,
        }
    
    def list_samples(self) -> List[DataSample]:
        samples = []
        if not self.local_path:
            return samples
        
        trajectories_path = self.local_path / "trajectories"
        if trajectories_path.exists():
            for traj_file in trajectories_path.glob("*.json"):
                samples.append(DataSample(
                    sample_key=traj_file.stem,
                    metadata={
                        "trajectory_path": str(traj_file),
                    }
                ))
        
        return samples
    
    def _get_name(self) -> str:
        return "TT3D"
    
    def _get_modality(self) -> str:
        return "trajectory"
    
    def _get_task(self) -> str:
        return "trajectory_reconstruction"
    
    def _get_license(self) -> str:
        return "mit"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://github.com/"  # Placeholder - actual URL to be added