"""
Adapter for Mozilla Common Voice dataset.
Multilingual ASR and broad acoustic coverage.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class CommonVoiceAdapter(BaseAdapter):
    """Adapter for Mozilla Common Voice dataset."""
    
    def validate_manifest(self) -> bool:
        """Validate that the dataset manifest is correct."""
        if not self.local_path:
            return False
        
        # Check for expected files
        expected_files = ["train.tsv", "test.tsv", "dev.tsv", "validated.tsv"]
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
            "name": "Mozilla Common Voice",
            "modality": "audio",
            "task": "asr",
            "license": "cc0",
            "commercial_allowed": True,
        }
        
        if self.local_path:
            # Count samples from TSV files
            total_samples = 0
            for split in ["train", "test", "dev", "validated"]:
                tsv_path = self.local_path / f"{split}.tsv"
                if tsv_path.exists():
                    with open(tsv_path, "r", encoding="utf-8") as f:
                        total_samples += sum(1 for _ in f) - 1  # Subtract header
            
            metadata["total_samples"] = total_samples
        
        return metadata
    
    def list_samples(self) -> List[DataSample]:
        """List all samples in the dataset."""
        samples = []
        
        if not self.local_path:
            return samples
        
        for split in ["train", "test", "dev", "validated"]:
            tsv_path = self.local_path / f"{split}.tsv"
            if tsv_path.exists():
                with open(tsv_path, "r", encoding="utf-8") as f:
                    header = f.readline().strip().split("\t")
                    for line in f:
                        parts = line.strip().split("\t")
                        if len(parts) >= 2:
                            samples.append(DataSample(
                                sample_key=f"{split}_{parts[0]}",
                                metadata={
                                    "path": parts[0],
                                    "sentence": parts[1] if len(parts) > 1 else None,
                                    "split": split,
                                }
                            ))
        
        return samples
    
    def _get_name(self) -> str:
        return "Mozilla Common Voice"
    
    def _get_modality(self) -> str:
        return "audio"
    
    def _get_task(self) -> str:
        return "asr"
    
    def _get_license(self) -> str:
        return "cc0"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://commonvoice.mozilla.org/"