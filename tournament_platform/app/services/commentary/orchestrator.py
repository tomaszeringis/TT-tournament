"""
Commentary orchestrator — page-facing API that composes the commentary pipeline.
"""

from typing import Optional

from tournament_platform.services.commentary_service import (
    CommentaryLine,
    CommentarySettings,
    CommentaryService,
    ImportanceLevel,
)
from tournament_platform.app.services.commentary.context import CommentaryContextBuilder
from tournament_platform.app.services.commentary.events import CommentaryEvent
from tournament_platform.app.services.commentary.generator import CommentaryTextGenerator
from tournament_platform.app.services.commentary.policy import CommentaryPolicy


class CommentaryOrchestrator:
    """Composes the commentary pipeline for page integration."""

    def __init__(self, service: Optional[CommentaryService] = None):
        self.service = service or CommentaryService()
        self.policy = CommentaryPolicy()
        self.generator = CommentaryTextGenerator(self.service.rewriter)
        self.context_builder = CommentaryContextBuilder()

    def build_score_commentary(
        self,
        event_type: str,
        state: any,
        settings: CommentarySettings,
        event_id: str,
        previous_state: Optional[any] = None,
    ) -> CommentaryLine:
        return self.service.build_score_commentary(
            event_type=event_type,
            state=state,
            settings=settings,
            event_id=event_id,
            previous_state=previous_state,
        )

    def build_set_win_commentary(self, game_event: dict, settings: CommentarySettings) -> CommentaryLine:
        return self.service.build_set_win_commentary(game_event, settings)

    def should_generate(self, event_type: str, importance: ImportanceLevel, mode, intensity) -> bool:
        return self.service.should_generate(event_type, importance, mode, intensity)

    def should_speak(self, last_event_id: Optional[str], current_event_id: str, settings: CommentarySettings) -> bool:
        return self.service.should_speak_commentary(last_event_id, current_event_id, settings)
