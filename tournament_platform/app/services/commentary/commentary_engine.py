"""
Local template-based commentary engine.

Produces deterministic, styleable, multilingual commentary lines from
structured ``CommentaryEventData`` and ``MatchContext`` inputs. No LLM,
no network calls.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from tournament_platform.app.services.commentary.event_schema import (
    CommentaryEventData,
    TTEventType,
    tt_event_type_to_legacy_category,
)
from tournament_platform.app.services.commentary.match_context import MatchContext
from tournament_platform.app.services.commentary.template_bank import normalize_commentary_type
from tournament_platform.services.commentary_templates import (
    _SafeDict,
    _LT_FORBIDDEN_EN_FRAGMENTS,
    looks_english_in_lithuanian,
    normalize_language,
    normalize_style,
    render_template,
)
from tournament_platform.app.services.commentary.template_bank import select_template_with_dedup
from tournament_platform.services.commentary_service import CommentaryLine, contains_english_commentary

logger = logging.getLogger(__name__)


@dataclass
class GeneratedCommentary:
    text: str
    event_type: str
    language: str
    style: str
    commentary_type: str
    should_speak: bool
    used_fallback: bool
    mixed_language_detected: bool
    template_style: str
    base_template: str
    tts_language_code: str = "en-US"
    generated_text: str = ""
    final_text: str = ""


class CommentaryEngine:
    """Local event-to-commentary template engine."""

    def __init__(self):
        self._recent_templates: List[str] = []

    def generate_commentary(
        self,
        event: CommentaryEventData,
        context: MatchContext,
        *,
        recent: Optional[List[str]] = None,
        spoken_enabled: bool = True,
        fast_score_change: bool = False,
        detail: str = "standard",
        rng: Optional[random.Random] = None,
    ) -> GeneratedCommentary:
        if recent is None:
            recent = list(self._recent_templates)

        event_type = event.event_type
        language = normalize_language(event.language or "en")
        style = normalize_style(event.style or "neutral")
        commentary_type = event.derived_commentary_type()

        # Detail override: short forces minimal output; tactical enables richer types.
        if detail == "short":
            commentary_type = "play_by_play"
            style = "short"
        elif detail == "tactical" and commentary_type == "play_by_play":
            commentary_type = "tactical"
        elif fast_score_change:
            commentary_type = "play_by_play"
            style = "short"

        variables = self._build_variables(event, context, language)

        chosen, text, new_recent = select_template_with_dedup(
            language=language,
            style=style,
            category=event_type.value,
            commentary_type=commentary_type,
            variables=variables,
            recent_keys=recent,
            rng=rng,
        )

        self._recent_templates = new_recent
        used_fallback = False
        mixed_language_detected = False

        if not text:
            # Fallback to neutral style.
            if style != "neutral":
                chosen, text, new_recent = select_template_with_dedup(
                    language=language,
                    style="neutral",
                    category=event_type.value,
                    commentary_type=commentary_type,
                    variables=variables,
                    recent_keys=recent,
                    rng=rng,
                )
                self._recent_templates = new_recent
                used_fallback = True
            if not text:
                # Ultimate fallback: safe message.
                text = "Komentaras negalimas." if language == "lt" else "Commentary unavailable."
                chosen = text

        # Mixed-language guard for Lithuanian.
        if language == "lt" and text:
            player_names = (event.player or "", event.opponent or "")
            if contains_english_commentary(text, language, player_names) or looks_english_in_lithuanian(text, player_names):
                _, text, new_recent = select_template_with_dedup(
                    language="lt",
                    style="neutral",
                    category=event_type.value,
                    commentary_type=commentary_type,
                    variables=variables,
                    recent_keys=[],
                    rng=rng,
                )
                self._recent_templates = new_recent
                mixed_language_detected = True

        final_text = text
        tts_language_code = "lt-LT" if language == "lt" else "en-US"
        should_speak = spoken_enabled and bool(final_text)

        return GeneratedCommentary(
            text=final_text,
            event_type=event_type.value,
            language=language,
            style=style,
            commentary_type=commentary_type,
            should_speak=should_speak,
            used_fallback=used_fallback,
            mixed_language_detected=mixed_language_detected,
            template_style=style,
            base_template=chosen or "",
            tts_language_code=tts_language_code,
            generated_text=text,
            final_text=final_text,
        )

    def from_event_kwargs(self, **kwargs: Any) -> CommentaryEventData:
        return CommentaryEventData(**kwargs)

    def _build_variables(self, event: CommentaryEventData, context: MatchContext, language: str) -> Dict[str, Any]:
        score = self._format_score(context.score_a, context.score_b, language)
        match_score = self._format_sets(context.games_won_a, context.games_won_b, language)

        winner = event.player
        loser = event.opponent or (context.player_b if event.player == context.player_a else context.player_a)
        player = event.player

        server = event.serving_player or context.serving_player or context.player_a
        receiver = context.player_b if server == context.player_a else context.player_a
        leader = context.player_a if context.score_a >= context.score_b else context.player_b
        trailer = context.player_b if context.score_b <= context.score_a else context.player_a
        lead = abs(context.score_a - context.score_b)
        game_number = context.current_game
        if language != "en":
            game_number = f"{context.current_game}-ą"

        vars_dict: Dict[str, Any] = {
            "player_a": context.player_a,
            "player_b": context.player_b,
            "winner": winner,
            "loser": loser,
            "player": player,
            "server": server,
            "receiver": receiver,
            "leader": leader,
            "trailer": trailer,
            "lead": lead,
            "score": score,
            "game_score": score,
            "match_score": match_score,
            "game_number": game_number,
            "set": context.current_game,
            "stage": f"game {context.current_game}",
            "streak_count": 1,
            "sets_a": context.games_won_a,
            "sets_b": context.games_won_b,
            "serving_player": server,
            "opponent": event.opponent or "",
        }

        if event.rally_length is not None:
            vars_dict["rally_length"] = event.rally_length
        if event.stroke_type:
            vars_dict["stroke_type"] = event.stroke_type
        if event.stroke_side:
            vars_dict["stroke_side"] = event.stroke_side
        if event.rally_outcome:
            vars_dict["rally_outcome"] = event.rally_outcome
        if event.posture:
            vars_dict["posture"] = event.posture
        if event.tempo:
            vars_dict["tempo"] = event.tempo
        if event.pressure_level:
            vars_dict["pressure_level"] = event.pressure_level
        if event.momentum_player:
            vars_dict["momentum_player"] = event.momentum_player

        return vars_dict

    @staticmethod
    def _format_score(a: int, b: int, language: str) -> str:
        if language == "lt":
            return f"{a}\u2013{b}"
        return f"{a} to {b}"

    @staticmethod
    def _format_sets(a: int, b: int, language: str) -> str:
        if language == "lt":
            return f"{a} : {b}"
        return f"{a} to {b}"

    def reset_recent(self) -> None:
        self._recent_templates = []
