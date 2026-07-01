"""
Base adapter for dataset ingestion.
Provides common interface for all dataset-specific adapters.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class DataSample:
    """Represents a single data sample from a dataset."""
    sample_key: str
    timestamp: Optional[str] = None
    duration_seconds: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class DatasetInfo:
    """Information about a dataset."""
    dataset_id: str
    name: str
    modality: str
    task: str
    license: str
    commercial_allowed: bool = False
    source_url: Optional[str] = None
    local_raw_path: Optional[str] = None
    local_processed_path: Optional[str] = None
    required_for_phase: Optional[List[str]] = None
    notes: Optional[str] = None


class BaseAdapter(ABC):
    """
    Abstract base class for dataset adapters.
    
    Each adapter handles:
    - Manifest validation
    - Local path validation
    - Metadata extraction
    - Normalized sample record creation
    """
    
    def __init__(self, dataset_id: str, local_path: Optional[str] = None):
        self.dataset_id = dataset_id
        self.local_path = Path(local_path) if local_path else None
    
    @abstractmethod
    def validate_manifest(self) -> bool:
        """Validate that the dataset manifest is correct."""
        pass
    
    @abstractmethod
    def validate_local_path(self) -> bool:
        """Validate that the local path exists and contains expected files."""
        pass
    
    @abstractmethod
    def extract_metadata(self) -> Dict[str, Any]:
        """Extract metadata from the dataset."""
        pass
    
    @abstractmethod
    def list_samples(self) -> List[DataSample]:
        """List all samples in the dataset."""
        pass
    
    def get_dataset_info(self) -> DatasetInfo:
        """Get basic dataset information."""
        return DatasetInfo(
            dataset_id=self.dataset_id,
            name=self._get_name(),
            modality=self._get_modality(),
            task=self._get_task(),
            license=self._get_license(),
            commercial_allowed=self._get_commercial_allowed(),
            source_url=self._get_source_url(),
            local_raw_path=str(self.local_path) if self.local_path else None,
        )
    
    def _get_name(self) -> str:
        """Get dataset name - override in subclasses."""
        return self.dataset_id
    
    def _get_modality(self) -> str:
        """Get dataset modality - override in subclasses."""
        return "unknown"
    
    def _get_task(self) -> str:
        """Get dataset task - override in subclasses."""
        return "unknown"
    
    def _get_license(self) -> str:
        """Get dataset license - override in subclasses."""
        return "unknown"
    
    def _get_commercial_allowed(self) -> bool:
        """Check if commercial use is allowed - override in subclasses."""
        return False
    
    def _get_source_url(self) -> Optional[str]:
        """Get source URL - override in subclasses."""
        return None