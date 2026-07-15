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
from tournament_platform.app.services.commentary.event_schema import (
    CommentaryEventData,
    TTEventType,
    legacy_category_to_tt_event_type,
    tt_event_type_to_legacy_category,
)
from tournament_platform.app.services.commentary.generator import CommentaryTextGenerator
from tournament_platform.app.services.commentary.match_context import MatchContext, MatchContextBuilder
from tournament_platform.app.services.commentary.commentary_engine import CommentaryEngine, GeneratedCommentary
from tournament_platform.app.services.commentary.orchestrator import CommentaryOrchestrator
from tournament_platform.app.services.commentary.policy import CommentaryPolicy
from tournament_platform.app.services.commentary.template_bank import (
    generate_match_summary,
    get_templates,
    normalize_commentary_type,
    select_template_with_dedup,
    validate_template_bank,
)

__all__ = [
    "CommentaryOrchestrator",
    "CommentaryEvent",
    "CommentaryEventType",
    "CommentaryContext",
    "CommentaryContextBuilder",
    "CommentaryPolicy",
    "CommentaryTextGenerator",
    "CommentaryEngine",
    "GeneratedCommentary",
    "CommentaryEventData",
    "MatchContext",
    "MatchContextBuilder",
    "TTEventType",
    "generate_match_summary",
    "get_templates",
    "normalize_commentary_type",
    "select_template_with_dedup",
    "validate_template_bank",
    "tt_event_type_to_legacy_category",
    "legacy_category_to_tt_event_type",
]
