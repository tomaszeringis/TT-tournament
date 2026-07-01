"""
Adapter for AMI Meeting Corpus.
Far-field, turn-taking, conversational robustness.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class AMIAdapter(BaseAdapter):
    """Adapter for AMI Meeting Corpus dataset."""
    
    def validate_manifest(self) -> bool:
        if not self.local_path:
            return False
        return (self.local_path / "corpus").exists() or (self.local_path / "meetings").exists()
    
    def validate_local_path(self) -> bool:
        if not self.local_path:
            return False
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": "AMI Meeting Corpus",
            "modality": "audio",
            "task": "asr",
            "license": "cc_by",
            "commercial_allowed": True,
        }
    
    def list_samples(self) -> List[DataSample]:
        samples = []
        if not self.local_path:
            return samples
        
        # AMI has meeting recordings
        meetings_path = self.local_path / "meetings"
        if meetings_path.exists():
            for meeting_dir in meetings_path.iterdir():
                if meeting_dir.is_dir():
                    samples.append(DataSample(
                        sample_key=meeting_dir.name,
                        metadata={"meeting_id": meeting_dir.name}
                    ))
        
        return samples
    
    def _get_name(self) -> str:
        return "AMI Meeting Corpus"
    
    def _get_modality(self) -> str:
        return "audio"
    
    def _get_task(self) -> str:
        return "asr"
    
    def _get_license(self) -> str:
        return "cc_by"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://groups.inf.ed.ac.uk/ami/corpus/"