"""
Tournament AI Package

AI and multimodal features separated from core tournament logic.
This package contains:
- AI assistant and coaching
- Voice command processing
- Video scorekeeper
- Intent classification
- Commentary generation
"""

from tournament_platform.services.ai_assistant import AIAssistant
from tournament_platform.services.ai_engine import AIEngine
from tournament_platform.services.ai_facade import AIFacade
from tournament_platform.services.ai_tool_registry import ai_tool_registry

__all__ = [
    "AIAssistant",
    "AIEngine",
    "AIFacade",
    "ai_tool_registry",
]