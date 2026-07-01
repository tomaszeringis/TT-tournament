"""
Multimodal AI subsystem for table tennis coaching and analysis.

This package provides:
- Dataset registry and management
- Intent classification for voice commands
- Feature extraction interfaces
- Coaching pipeline integration
"""

from .dataset_registry import DatasetRegistry, DatasetInfo, LicenseType
from .intent_classifier import IntentClassifier, IntentResult, IntentType

__all__ = [
    "DatasetRegistry",
    "DatasetInfo",
    "LicenseType",
    "IntentClassifier",
    "IntentResult",
    "IntentType",
]