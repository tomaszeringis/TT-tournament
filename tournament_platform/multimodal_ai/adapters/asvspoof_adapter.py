"""
Adapter for ASVspoof 2021 dataset.
Anti-spoofing for voice authentication.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class ASVspoofAdapter(BaseAdapter):
    """Adapter for ASVspoof 2021 dataset."""
    
    def validate_manifest(self) -> bool:
        if not self.local_path:
            return False
        return (self.local_path / "ASVspoof2021").exists() or (self.local_path / "protocols").exists()
    
    def validate_local_path(self) -> bool:
        if not self.local_path:
            return False
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": "ASVspoof 2021",
            "modality": "audio",
            "task": "anti_spoof",
            "license": "cc_by",
            "commercial_allowed": True,
        }
    
    def list_samples(self) -> List[DataSample]:
        samples = []
        if not self.local_path:
            return samples
        
        # ASVspoof has protocol files with labels
        protocols_path = self.local_path / "protocols"
        if protocols_path.exists():
            for protocol_file in protocols_path.glob("*.txt"):
                with open(protocol_file, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            samples.append(DataSample(
                                sample_key=parts[0],
                                metadata={
                                    "label": parts[1],  # bonafide or spoof
                                }
                            ))
        
        return samples
    
    def _get_name(self) -> str:
        return "ASVspoof 2021"
    
    def _get_modality(self) -> str:
        return "audio"
    
    def _get_task(self) -> str:
        return "anti_spoof"
    
    def _get_license(self) -> str:
        return "cc_by"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://www.asvspoof.org/"