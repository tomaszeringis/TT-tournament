"""TT Sounds / Audio Rally Assistant package.

Provides lightweight impact detection and rally context management without
requiring Torch at import time.
"""

from .detector import ImpactDetector
from .processor import TTRallyProcessor
from .rally_context import RallyManager
from .schemas import AudioImpactEvent, AudioRallySummary, RallyContext, TTAudioEvent
from .classifier import TTClassifier
from .settings import (
    TT_SOUNDS_ENABLED,
    TT_SOUNDS_ABS_MIN_ENERGY,
    TT_SOUNDS_THRESHOLD_MULTIPLIER,
    TT_SOUNDS_NOISE_FLOOR_DECAY,
    TT_SOUNDS_COOLDOWN_MS,
    TT_SOUNDS_WINDOW_MS,
    TT_SOUNDS_EVENT_WINDOW_MS,
    TT_SOUNDS_MIN_INTERVAL_MS,
    TT_SOUNDS_DEBUG,
    TT_SOUNDS_MODEL_DIR,
)

__all__ = [
    "ImpactDetector",
    "TTRallyProcessor",
    "RallyManager",
    "TTAudioEvent",
    "AudioImpactEvent",
    "AudioRallySummary",
    "RallyContext",
    "TTClassifier",
    "TT_SOUNDS_ENABLED",
    "TT_SOUNDS_ABS_MIN_ENERGY",
    "TT_SOUNDS_THRESHOLD_MULTIPLIER",
    "TT_SOUNDS_NOISE_FLOOR_DECAY",
    "TT_SOUNDS_COOLDOWN_MS",
    "TT_SOUNDS_WINDOW_MS",
    "TT_SOUNDS_EVENT_WINDOW_MS",
    "TT_SOUNDS_MIN_INTERVAL_MS",
    "TT_SOUNDS_DEBUG",
    "TT_SOUNDS_MODEL_DIR",
]
