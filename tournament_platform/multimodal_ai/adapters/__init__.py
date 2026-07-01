"""
Dataset adapters for the Multimodal AI system.
Each adapter handles ingestion and metadata extraction for a specific dataset.
"""

from .base_adapter import BaseAdapter
from .common_voice_adapter import CommonVoiceAdapter
from .gigaspeech_adapter import GigaSpeechAdapter
from .ami_adapter import AMIAdapter
from .fluent_commands_adapter import FluentCommandsAdapter
from .asvspoof_adapter import ASVspoofAdapter
from .t3set_adapter import T3SetAdapter
from .openttgames_adapter import OpenTTGamesAdapter
from .blurball_adapter import BlurBallAdapter
from .ttswing_adapter import TTSwingAdapter
from .tt3d_adapter import TT3DAdapter

__all__ = [
    "BaseAdapter",
    "CommonVoiceAdapter",
    "GigaSpeechAdapter",
    "AMIAdapter",
    "FluentCommandsAdapter",
    "ASVspoofAdapter",
    "T3SetAdapter",
    "OpenTTGamesAdapter",
    "BlurBallAdapter",
    "TTSwingAdapter",
    "TT3DAdapter",
]