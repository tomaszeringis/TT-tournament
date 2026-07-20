"""
Tournament AI Package

AI and multimodal features separated from core tournament logic.
This package contains:
- AI assistant and coaching
- Voice command processing
- Video scorekeeper
- Intent classification
- Commentary generation

The re-exports below are best-effort: if a referenced lab symbol is unavailable
(e.g. the lab module was refactored), the package still imports so that the
production ``tournament_ai.rag`` subpackage can be used independently.
"""

try:
    from tournament_platform.services.ai_assistant import AIAssistant
except Exception:  # pragma: no cover - depends on lab module shape
    AIAssistant = None

try:
    from tournament_platform.services.ai_engine import AIEngine
except Exception:  # pragma: no cover
    AIEngine = None

try:
    from tournament_platform.services.ai_facade import AIFacade
except Exception:  # pragma: no cover
    AIFacade = None

try:
    from tournament_platform.services.ai_tool_registry import ai_tool_registry
except Exception:  # pragma: no cover
    ai_tool_registry = None

__all__ = [
    "AIAssistant",
    "AIEngine",
    "AIFacade",
    "ai_tool_registry",
]
