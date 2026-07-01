"""
Adapter for GigaSpeech dataset.
Core ASR pretraining and benchmarking.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class GigaSpeechAdapter(BaseAdapter):
    """Adapter for GigaSpeech dataset."""
    
    def validate_manifest(self) -> bool:
        """Validate that the dataset manifest is correct."""
        if not self.local_path:
            return False
        
        # Check for expected files
        expected_files = ["train.jsonl", "test.jsonl", "dev.jsonl"]
        for f in expected_files:
            if not (self.local_path / f).exists():
                return False
        
        return True
    
    def validate_local_path(self) -> bool:
        """Validate that the local path exists and contains expected files."""
        if not self.local_path:
            return False
        
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        """Extract metadata from the dataset."""
        metadata = {
            "dataset_id": self.dataset_id,
            "name": "GigaSpeech",
            "modality": "audio",
            "task": "asr",
            "license": "apache",
            "commercial_allowed": True,
        }
        
        if self.local_path:
            # Count samples from JSONL files
            total_samples = 0
            for split in ["train", "test", "dev"]:
                jsonl_path = self.local_path / f"{split}.jsonl"
                if jsonl_path.exists():
                    with open(jsonl_path, "r", encoding="utf-8") as f:
                        total_samples += sum(1 for _ in f)
            
            metadata["total_samples"] = total_samples
        
        return metadata
    
    def list_samples(self) -> List[DataSample]:
        """List all samples in the dataset."""
        samples = []
        
        if not self.local_path:
            return samples
        
        for split in ["train", "test", "dev"]:
            jsonl_path = self.local_path / f"{split}.jsonl"
            if jsonl_path.exists():
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        samples.append(DataSample(
                            sample_key=f"{split}_{i}",
                            metadata={
                                "split": split,
                                "line_number": i,
                            }
                        ))
        
        return samples
    
    def _get_name(self) -> str:
        return "GigaSpeech"
    
    def _get_modality(self) -> str:
        return "audio"
    
    def _get_task(self) -> str:
        return "asr"
    
    def _get_license(self) -> str:
        return "apache"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://github.com/alibaba-damo-academy/gigaspeech"