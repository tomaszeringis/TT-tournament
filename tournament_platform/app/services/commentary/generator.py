"""
Commentary text generator — wraps template library + selector + Ollama rewrite.
"""

from typing import Any, Optional

from tournament_platform.services.commentary_service import (
    ScoreMoment,
    CommentaryVerbosity,
    TEMPLATE_LIBRARY,
    LITHUANIAN_GENERIC_TEMPLATES,
    ENGLISH_GENERIC_TEMPLATES,
    SAFE_MESSAGE,
    contains_english_commentary,
    CommentaryLine as _CommentaryLine,
)
from tournament_platform.services import commentary_templates as ct
from tournament_platform.services.commentary_templates import (
    select_event_template,
    normalize_verbosity,
)


class CommentaryTextGenerator:
    """Generates CommentaryLine text from templates and optional Ollama rewrite."""

    def __init__(self, rewriter: Optional[Any] = None):
        self.rewriter = rewriter

    def generate(
        self,
        event_type: str,
        moment: ScoreMoment,
        state: Any,
        settings: Any,
        event_id_str: str,
        event_id: str,
        previous_state: Optional[Any] = None,
        recent_store: Optional[dict] = None,
    ) -> _CommentaryLine:
        language = _normalize_language(settings.language)
        style_str = settings.style.value

        effective_verbosity = settings.verbosity
        nverb = normalize_verbosity(effective_verbosity)
        if nverb == "silent":
            return _CommentaryLine(
                text="",
                event_type=event_type,
                priority=1,
                should_speak=False,
                dedupe_key=f"{event_type}:{event_id}",
                event_id=event_id,
            )

        if getattr(settings, "voice_profile_id", None) == "sport_commentator":
            critical_moments = (
                ScoreMoment.DEUCE,
                ScoreMoment.ADVANTAGE_A,
                ScoreMoment.ADVANTAGE_B,
                ScoreMoment.GAME_POINT_A,
                ScoreMoment.GAME_POINT_B,
                ScoreMoment.GAME_WON_A,
                ScoreMoment.GAME_WON_B,
                ScoreMoment.MATCH_WON_A,
                ScoreMoment.MATCH_WON_B,
                ScoreMoment.COMEBACK_A,
                ScoreMoment.COMEBACK_B,
            )
            if moment in critical_moments:
                effective_verbosity = CommentaryVerbosity.EXPRESSIVE

        variables = _build_generator_variables(state, moment, event_id_str, language, previous_state)

        # Primary path: dedicated, well-structured phrase bank module.
        chosen, text, _new_recent = select_event_template(
            event_id_str, language, style_str, effective_verbosity, variables,
            recent_store=recent_store,
        )
        used_fallback = False
        fallback_reason = None
        tpl_lang = language
        tpl_style = style_str
        base_tmpl = chosen or ""

        if not text:
            # Fallback path: keep the previous legacy template logic intact.
            text, used_fallback, fallback_reason, tpl_style, base_tmpl = self._generate_legacy(
                event_type, moment, state, settings, event_id_str, language, style_str,
                effective_verbosity, variables,
            )
            tpl_lang = language

        if not text:
            # Minimal/silent verbosity suppresses speech entirely; never fall
            # back to a safe message for an intentionally muted event.
            if nverb in ("minimal", "silent"):
                text = ""
            else:
                text = SAFE_MESSAGE.get(language, SAFE_MESSAGE["en"])
            base_tmpl = text

        generated_text = text
        final_text = text

        winner = state.player_a
        loser = state.player_b
        if moment in (ScoreMoment.MATCH_WON_A, ScoreMoment.GAME_WON_A, ScoreMoment.POINT_A, ScoreMoment.STREAK_A, ScoreMoment.COMEBACK_A):
            winner = state.player_a
            loser = state.player_b
        elif moment in (ScoreMoment.MATCH_WON_B, ScoreMoment.GAME_WON_B, ScoreMoment.POINT_B, ScoreMoment.STREAK_B, ScoreMoment.COMEBACK_B):
            winner = state.player_b
            loser = state.player_a
        facts = {
            "player_a": state.player_a,
            "player_b": state.player_b,
            "score_a": state.score_a,
            "score_b": state.score_b,
            "winner": winner,
            "loser": loser,
        }

        used_ollama = False
        if language != "en" and settings.ollama_rewrite_enabled and generated_text:
            if self.rewriter is not None:
                rewritten, used_ollama = self.rewriter.rewrite(generated_text, facts, style_str, language, event_id_str)
                if used_ollama:
                    final_text = rewritten
                else:
                    final_text = generated_text

        mixed_language_detected = False
        if language == "lt" and final_text:
            if contains_english_commentary(final_text, language, (state.player_a, state.player_b)):
                final_text = _regenerate_lt_neutral(event_id_str, variables)
                mixed_language_detected = True

        priority = 3 if moment in (
            ScoreMoment.GAME_WON_A, ScoreMoment.GAME_WON_B,
            ScoreMoment.MATCH_WON_A, ScoreMoment.MATCH_WON_B,
            ScoreMoment.DEUCE, ScoreMoment.ADVANTAGE_A, ScoreMoment.ADVANTAGE_B,
            ScoreMoment.GAME_POINT_A, ScoreMoment.GAME_POINT_B,
        ) else 2

        return _CommentaryLine(
            text=final_text,
            event_type=event_type,
            priority=priority,
            should_speak=bool(final_text),
            dedupe_key=f"{event_type}:{event_id}",
            event_id=event_id,
            ssml_text=final_text,
            generated_text=generated_text,
            final_text=final_text,
            template_language=tpl_lang,
            template_style=tpl_style,
            base_template=base_tmpl,
            used_fallback=used_fallback,
            fallback_reason=fallback_reason,
            mixed_language_detected=mixed_language_detected,
            used_ollama=used_ollama,
            tts_language_code=None,
            cache_key=None,
            cache_hit=False,
            selected_language=settings.language,
            normalized_language=language,
            event_id_str=event_id_str,
        )

    def _generate_legacy(
        self,
        event_type: str,
        moment: ScoreMoment,
        state: Any,
        settings: Any,
        event_id_str: str,
        language: str,
        style_str: str,
        effective_verbosity: Any,
        variables: dict,
    ):
        """Previous template logic, kept as a safe fallback for uncovered slots."""
        if language == "en":
            templates = _get_commentary_templates(settings.style, moment, effective_verbosity)
            template_text = _choose_commentary_template(templates)
            if not template_text:
                return "", False, None, style_str, ""
            generated_text = template_text.format(
                player_a=state.player_a,
                player_b=state.player_b,
                score=f"{state.score_a} to {state.score_b}",
                sets_a=state.sets_a,
                sets_b=state.sets_b,
            )
            return generated_text, False, None, style_str, template_text
        else:
            template_texts, used_fallback, fallback_reason = _select_base_template(event_id_str, language, style_str)
            template_text = _choose_commentary_template(template_texts)
            base_tmpl = template_text
            try:
                generated_text = template_text.format(**variables) if variables else ""
            except KeyError:
                generated_text = ""
            tpl_style = style_str if not used_fallback else ("neutral" if fallback_reason == "neutral_fallback" else style_str)
            return generated_text, used_fallback, fallback_reason, tpl_style, base_tmpl


def _build_generator_variables(state, moment, event_id_str, language, previous_state=None) -> dict:
    """Build the full variable dictionary consumed by the phrase-bank module."""
    score = f"{state.score_a} to {state.score_b}" if language == "en" else f"{state.score_a}\u2013{state.score_b}"
    match_score = f"{state.sets_a} to {state.sets_b}" if language == "en" else f"{state.sets_a} : {state.sets_b}"

    winner = state.player_a
    loser = state.player_b
    player = state.player_a
    if moment in (ScoreMoment.POINT_B, ScoreMoment.GAME_WON_B, ScoreMoment.MATCH_WON_B,
                  ScoreMoment.ADVANTAGE_B, ScoreMoment.GAME_POINT_B, ScoreMoment.STREAK_B,
                  ScoreMoment.COMEBACK_B):
        winner, loser, player = state.player_b, state.player_a, state.player_b
    elif moment in (ScoreMoment.POINT_A, ScoreMoment.GAME_WON_A, ScoreMoment.MATCH_WON_A,
                    ScoreMoment.ADVANTAGE_A, ScoreMoment.GAME_POINT_A, ScoreMoment.STREAK_A,
                    ScoreMoment.COMEBACK_A):
        winner, loser, player = state.player_a, state.player_b, state.player_a
    elif event_id_str == "serve":
        player = getattr(state, "serving_player", None) or state.player_a

    # For game/set wins the game score string is the current game score.
    if event_id_str in ("set_win", "game_won"):
        game_score = score
    else:
        game_score = score

    if moment in (ScoreMoment.STREAK_A, ScoreMoment.STREAK_B):
        recent = (state.match_history or [])[-3:]
        players = [e.get("player") for e in recent if e.get("action") == "point_added"]
        streak_count = len(players) if len(players) >= 3 and len(set(players)) == 1 else 3
    else:
        streak_count = 1

    server = getattr(state, "serving_player", None) or state.player_a
    receiver = state.player_b if server == state.player_a else state.player_a

    leader = state.player_a if state.score_a >= state.score_b else state.player_b
    trailer = state.player_b if state.score_b <= state.score_a else state.player_a
    lead = abs(state.score_a - state.score_b)

    game_number = state.current_set
    if language != "en":
        game_number = f"{state.current_set}-ą"

    return {
        "player_a": state.player_a,
        "player_b": state.player_b,
        "winner": winner,
        "loser": loser,
        "player": player,
        "server": server,
        "receiver": receiver,
        "leader": leader,
        "trailer": trailer,
        "lead": lead,
        "score": score,
        "game_score": game_score,
        "match_score": match_score,
        "game_number": game_number,
        "set": state.current_set,
        "stage": f"game {state.current_set}",
        "streak_count": streak_count,
        "sets_a": state.sets_a,
        "sets_b": state.sets_b,
    }


def _get_commentary_templates(style, moment, verbosity):
    from tournament_platform.services.commentary_service import CommentaryService
    return CommentaryService().get_commentary_templates(style, moment, verbosity)


def _choose_commentary_template(templates):
    if not templates:
        return ""
    return templates[0]


def _select_base_template(event_id, language, style):
    from tournament_platform.services.commentary_service import CommentaryService
    return CommentaryService()._select_base_template(event_id, language, style)


def _regenerate_lt_neutral(event_id, format_vars):
    from tournament_platform.services.commentary_service import CommentaryService
    return CommentaryService()._regenerate_lt_neutral(event_id, format_vars)


def _format_score(state, language):
    if language == "lt":
        return f"{state.score_a}\u2013{state.score_b}"
    return f"{state.score_a} to {state.score_b}"


def _format_sets(sets_a, sets_b, language):
    if language == "lt":
        return f"{sets_a} : {sets_b}"
    return f"{sets_a} to {sets_b}"


def _normalize_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized in {"lt", "lithuanian", "lietuvių", "lithuanian (lt)"}:
        return "lt"
    if normalized in {"en", "english", "english (en)"}:
        return "en"
    return "en"
