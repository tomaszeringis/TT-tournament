"""
Adapter for Fluent Speech Commands dataset.
Command / intent supervision.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .base_adapter import BaseAdapter, DataSample


class FluentCommandsAdapter(BaseAdapter):
    """Adapter for Fluent Speech Commands dataset."""
    
    def validate_manifest(self) -> bool:
        if not self.local_path:
            return False
        return (self.local_path / "data").exists() or (self.local_path / "fluent_speech_commands.json").exists()
    
    def validate_local_path(self) -> bool:
        if not self.local_path:
            return False
        return self.local_path.exists() and self.local_path.is_dir()
    
    def extract_metadata(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": "Fluent Speech Commands",
            "modality": "audio",
            "task": "intent",
            "license": "mit",
            "commercial_allowed": True,
        }
    
    def list_samples(self) -> List[DataSample]:
        samples = []
        if not self.local_path:
            return samples
        
        json_path = self.local_path / "fluent_speech_commands.json"
        if json_path.exists():
            import json
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for i, item in enumerate(data):
                    samples.append(DataSample(
                        sample_key=f"cmd_{i}",
                        metadata={
                            "action": item.get("action"),
                            "object": item.get("object"),
                            "location": item.get("location"),
                        }
                    ))
        
        return samples
    
    def _get_name(self) -> str:
        return "Fluent Speech Commands"
    
    def _get_modality(self) -> str:
        return "audio"
    
    def _get_task(self) -> str:
        return "intent"
    
    def _get_license(self) -> str:
        return "mit"
    
    def _get_commercial_allowed(self) -> bool:
        return True
    
    def _get_source_url(self) -> str:
        return "https://github.com/google-research/google-research/tree/master/fluent_speech_commands"