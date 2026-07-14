"""
Commentary package — orchestration layer for voice/score commentary.

Public API:
    CommentaryOrchestrator — page-facing composition root
    CommentaryEvent — normalized event with stable event_id
    CommentaryEventType — event type enum
    CommentaryContext — match context dataclass
    CommentaryContextBuilder — derives context from engine state
    CommentaryPolicy — importance, dedup, cooldown, suppression
    CommentaryTextGenerator — template selection + formatting + Ollama rewrite
"""

from tournament_platform.app.services.commentary.context import CommentaryContext, CommentaryContextBuilder
from tournament_platform.app.services.commentary.events import CommentaryEvent, CommentaryEventType
from tournament_platform.app.services.commentary.generator import CommentaryTextGenerator
from tournament_platform.app.services.commentary.orchestrator import CommentaryOrchestrator
from tournament_platform.app.services.commentary.policy import CommentaryPolicy

__all__ = [
    "CommentaryOrchestrator",
    "CommentaryEvent",
    "CommentaryEventType",
    "CommentaryContext",
    "CommentaryContextBuilder",
    "CommentaryPolicy",
    "CommentaryTextGenerator",
]
