"""
Dataset Registry for managing public table tennis and voice datasets.

Provides manifest loading, validation, and license gating for dataset combinations.
"""

import os
import json
import yaml
import logging
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set

logger = logging.getLogger(__name__)


class LicenseType(str, Enum):
    """License types for datasets."""
    CC0 = "cc0"  # Public domain, commercial use allowed
    CC_BY = "cc_by"  # Creative Commons Attribution
    MIT = "mit"  # MIT License
    APACHE = "apache"  # Apache License
    BSD = "bsd"  # BSD License
    NON_COMMERCIAL = "non_commercial"  # Research-only, no commercial use
    RESEARCH_ONLY = "research_only"  # Research-only license
    UNKNOWN = "unknown"


class Modality(str, Enum):
    """Data modalities supported by the system."""
    AUDIO = "audio"
    VIDEO = "video"
    SENSOR = "sensor"
    TEXT = "text"
    TRAJECTORY = "trajectory"


class Task(str, Enum):
    """ML tasks supported by the datasets."""
    ASR = "asr"  # Automatic Speech Recognition
    INTENT = "intent"  # Intent Classification
    ANTI_SPOOF = "anti_spoof"  # Anti-spoofing detection
    SPEAKER_ID = "speaker_id"  # Speaker identification
    BALL_DETECTION = "ball_detection"
    EVENT_SPOTTING = "event_spotting"
    STROKE_CLASSIFICATION = "stroke_classification"
    POSE_ESTIMATION = "pose_estimation"
    TRAJECTORY_RECONSTRUCTION = "trajectory_reconstruction"
    COACHING = "coaching"


@dataclass
class DatasetInfo:
    """Information about a dataset."""
    dataset_id: str
    name: str
    modality: Modality
    task: Task
    license: LicenseType
    commercial_allowed: bool
    source_url: str
    local_raw_path: Optional[str] = None
    local_processed_path: Optional[str] = None
    required_for_phase: Optional[List[str]] = None
    notes: Optional[str] = None
    size_gb: Optional[float] = None
    version: Optional[str] = None

    def __post_init__(self):
        if self.required_for_phase is None:
            self.required_for_phase = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "modality": self.modality.value,
            "task": self.task.value,
            "license": self.license.value,
            "commercial_allowed": self.commercial_allowed,
            "source_url": self.source_url,
            "local_raw_path": self.local_raw_path,
            "local_processed_path": self.local_processed_path,
            "required_for_phase": self.required_for_phase,
            "notes": self.notes,
            "size_gb": self.size_gb,
            "version": self.version,
        }


# Dataset combination presets
DATASET_COMBINATIONS: Dict[str, Set[str]] = {
    "voice_core": {
        "mozilla_common_voice",
        "gigaspeech",
        "ami_meeting",
        "fluent_speech_commands",
    },
    "tt_perception_core": {
        "openttgames",
        "blurball",
        "ttswing",
    },
    "coaching_core": {
        "t3set",
        "extended_openttgames",
    },
    "research_full": {
        "mozilla_common_voice",
        "gigaspeech",
        "ami_meeting",
        "fluent_speech_commands",
        "asvspoof2021",
        "t3set",
        "openttgames",
        "extended_openttgames",
        "blurball",
        "ttswing",
        "tt3d",
    },
    "commercial_safe_baseline": {
        "mozilla_common_voice",
        "gigaspeech",
        "openttgames",
        "blurball",
        "ttswing",
    },
}


# Default dataset manifest (embedded for initial use)
DEFAULT_MANIFEST: Dict[str, Any] = {
    "datasets": {
        "mozilla_common_voice": {
            "name": "Mozilla Common Voice",
            "modality": "audio",
            "task": "asr",
            "license": "cc0",
            "commercial_allowed": True,
            "source_url": "https://commonvoice.mozilla.org",
            "notes": "Multilingual ASR dataset, broad acoustic coverage",
            "size_gb": 100.0,
        },
        "gigaspeech": {
            "name": "GigaSpeech",
            "modality": "audio",
            "task": "asr",
            "license": "apache",
            "commercial_allowed": True,
            "source_url": "https://github.com/SpeechLLM/gigaspeech",
            "notes": "Large-scale ASR for pretraining/benchmarking",
            "size_gb": 200.0,
        },
        "ami_meeting": {
            "name": "AMI Meeting Corpus",
            "modality": "audio",
            "task": "asr",
            "license": "cc_by",
            "commercial_allowed": True,
            "source_url": "https://groups.inf.ed.ac.uk/ami/corpus",
            "notes": "Far-field, turn-taking, conversational robustness",
            "size_gb": 10.0,
        },
        "fluent_speech_commands": {
            "name": "Fluent Speech Commands",
            "modality": "audio",
            "task": "intent",
            "license": "mit",
            "commercial_allowed": True,
            "source_url": "https://github.com/microsoft/fluent-speech-commands",
            "notes": "Command/intent supervision for voice control",
            "size_gb": 0.1,
        },
        "asvspoof2021": {
            "name": "ASVspoof 2021",
            "modality": "audio",
            "task": "anti_spoof",
            "license": "research_only",
            "commercial_allowed": False,
            "source_url": "https://www.asvspoof.org",
            "notes": "Anti-spoofing for voice authentication",
            "size_gb": 1.0,
        },
        "t3set": {
            "name": "T3Set",
            "modality": "video",
            "task": "coaching",
            "license": "non_commercial",
            "commercial_allowed": False,
            "source_url": "https://t3set.github.io",
            "notes": "Video + sensor + coaching text for table tennis",
            "size_gb": 50.0,
        },
        "openttgames": {
            "name": "OpenTTGames",
            "modality": "video",
            "task": "ball_detection",
            "license": "unknown",
            "commercial_allowed": False,
            "source_url": "https://github.com/OpenTTGames",
            "notes": "Ball detection, bounce/net events, segmentation",
            "size_gb": 20.0,
        },
        "extended_openttgames": {
            "name": "Extended OpenTTGames",
            "modality": "video",
            "task": "stroke_classification",
            "license": "unknown",
            "commercial_allowed": False,
            "source_url": "https://github.com/OpenTTGames",
            "notes": "Stroke subtype, posture, rally outcome labels",
            "size_gb": 30.0,
        },
        "blurball": {
            "name": "BlurBall",
            "modality": "video",
            "task": "ball_detection",
            "license": "unknown",
            "commercial_allowed": False,
            "source_url": "https://github.com/BlurBall",
            "notes": "Fast blurred ball tracking",
            "size_gb": 15.0,
        },
        "ttswing": {
            "name": "TTSwing",
            "modality": "sensor",
            "task": "stroke_classification",
            "license": "unknown",
            "commercial_allowed": False,
            "source_url": "https://github.com/TTSwing",
            "notes": "Racket IMU/kinematics and biomechanics",
            "size_gb": 5.0,
        },
        "tt3d": {
            "name": "TT3D",
            "modality": "video",
            "task": "trajectory_reconstruction",
            "license": "unknown",
            "commercial_allowed": False,
            "source_url": "https://github.com/TT3D",
            "notes": "3D ball trajectory reconstruction",
            "size_gb": 25.0,
        },
    }
}


class DatasetRegistry:
    """
    Registry for managing table tennis and voice datasets.
    
    Handles manifest loading, validation, and license checking.
    """

    def __init__(self, manifest_path: Optional[str] = None):
        self._datasets: Dict[str, DatasetInfo] = {}
        self._manifest_path = manifest_path
        
        if manifest_path and os.path.exists(manifest_path):
            self.load_manifest(manifest_path)
        else:
            self._load_default_manifest()

    def _load_default_manifest(self) -> None:
        """Load the embedded default manifest."""
        for dataset_id, info in DEFAULT_MANIFEST["datasets"].items():
            self._datasets[dataset_id] = DatasetInfo(
                dataset_id=dataset_id,
                name=info["name"],
                modality=Modality(info["modality"]),
                task=Task(info["task"]),
                license=LicenseType(info["license"]),
                commercial_allowed=info["commercial_allowed"],
                source_url=info["source_url"],
                notes=info.get("notes"),
                size_gb=info.get("size_gb"),
            )
        logger.info(f"Loaded {len(self._datasets)} datasets from default manifest")

    def load_manifest(self, path: str) -> None:
        """Load dataset manifest from YAML or JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            if path.endswith('.yaml') or path.endswith('.yml'):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        for dataset_id, info in data.get("datasets", {}).items():
            self._datasets[dataset_id] = DatasetInfo(
                dataset_id=dataset_id,
                name=info["name"],
                modality=Modality(info["modality"]),
                task=Task(info["task"]),
                license=LicenseType(info["license"]),
                commercial_allowed=info["commercial_allowed"],
                source_url=info["source_url"],
                local_raw_path=info.get("local_raw_path"),
                local_processed_path=info.get("local_processed_path"),
                required_for_phase=info.get("required_for_phase", []),
                notes=info.get("notes"),
                size_gb=info.get("size_gb"),
                version=info.get("version"),
            )
        logger.info(f"Loaded {len(self._datasets)} datasets from {path}")

    def get_dataset(self, dataset_id: str) -> Optional[DatasetInfo]:
        """Get a dataset by ID."""
        return self._datasets.get(dataset_id)

    def list_datasets(self) -> List[DatasetInfo]:
        """List all registered datasets."""
        return list(self._datasets.values())

    def list_datasets_by_modality(self, modality: Modality) -> List[DatasetInfo]:
        """List datasets filtered by modality."""
        return [d for d in self._datasets.values() if d.modality == modality]

    def list_datasets_by_task(self, task: Task) -> List[DatasetInfo]:
        """List datasets filtered by task."""
        return [d for d in self._datasets.values() if d.task == task]

    def get_combination(self, combination_name: str) -> List[DatasetInfo]:
        """Get all datasets in a combination preset."""
        if combination_name not in DATASET_COMBINATIONS:
            raise ValueError(f"Unknown combination: {combination_name}")
        
        dataset_ids = DATASET_COMBINATIONS[combination_name]
        return [self._datasets[ds_id] for ds_id in dataset_ids if ds_id in self._datasets]

    def validate_license(self, dataset_id: str, allow_non_commercial: bool = False) -> bool:
        """
        Check if a dataset can be used based on license.
        
        Args:
            dataset_id: The dataset to check
            allow_non_commercial: Whether to allow non-commercial datasets
            
        Returns:
            True if the dataset can be used, False otherwise
        """
        dataset = self._datasets.get(dataset_id)
        if not dataset:
            return False
        
        if dataset.commercial_allowed:
            return True
        
        if allow_non_commercial:
            logger.warning(
                f"Using non-commercial dataset '{dataset_id}' - "
                f"not for commercial deployment"
            )
            return True
        
        return False

    def validate_combination(
        self, 
        combination_name: str, 
        allow_non_commercial: bool = False
    ) -> Dict[str, bool]:
        """
        Validate all datasets in a combination.
        
        Returns:
            Dict mapping dataset_id to validation result
        """
        dataset_ids = DATASET_COMBINATIONS.get(combination_name, set())
        return {
            ds_id: self.validate_license(ds_id, allow_non_commercial)
            for ds_id in dataset_ids
        }

    def get_non_commercial_datasets(self) -> List[DatasetInfo]:
        """Get all datasets that are not commercially allowed."""
        return [d for d in self._datasets.values() if not d.commercial_allowed]

    def get_commercial_safe_datasets(self) -> List[DatasetInfo]:
        """Get all datasets that are commercially safe."""
        return [d for d in self._datasets.values() if d.commercial_allowed]

    def save_manifest(self, path: str) -> None:
        """Save current registry to a YAML file."""
        data = {
            "datasets": {
                ds_id: ds.to_dict() 
                for ds_id, ds in self._datasets.items()
            }
        }
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)