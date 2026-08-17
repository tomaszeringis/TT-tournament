"""Commentary and TTS Coordination (Phase 6)"""

from __future__ import annotations

import json, logging, time, uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

import streamlit as st

from tournament_platform.services.commentary_templates import (
    normalize_commentary_style,
    SUPPORTED_COMMENTARY_STYLES,
)

RETAINED_STYLES = ("professional", "coach", "announcer")

STYLE_COMPATIBILITY_MAP = {
    "neutral": "professional",
    "minimal": "professional",
    "kids": "professional",
    "beginner": "professional",
    "simple": "professional",
    "couch": "coach",
    "commentator": "announcer",
    "sport_commentator": "announcer",
    "energetic": "announcer",
}

STYLE_TO_CATEGORY = {
    "professional": "play_by_play",
    "coach": "tactical",
    "announcer": "contextual",
}

COMMENTARY_STYLE_OPTIONS = list(RETAINED_STYLES)


def normalize_commentary_style_for_ui(raw: object) -> str:
    normalized = normalize_commentary_style(str(raw or "professional"))
    mapped = STYLE_COMPATIBILITY_MAP.get(normalized, normalized)
    if mapped not in RETAINED_STYLES:
        return "professional"
    return mapped


from tournament_platform.services.commentary_service import (
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    CommentaryLanguage,
    CommentaryMode,
    CommentaryIntensity,
    ImportanceLevel,
    SpokenScoreState,
    CommentaryLine,
    ScoreMoment,
    log_commentary_event,
)
from tournament_platform.app.services.commentary_voice.piper_runtime import is_piper_available
from tournament_platform.app.services.ui_feedback import render_sound_toggle, play_cue
from tournament_platform.app.services.voice_tts import TTSMode
from tournament_platform.app.components.spoken_commentary import speak_commentary, speak_commentary_audio_file
from tournament_platform.app.services.commentary_voice.piper_voice import get_piper_engine, PiperTTSError
from tournament_platform.app.services.commentary_voice.piper_runtime import find_piper_voices
from tournament_platform.app.services.commentary.commentary_engine import CommentaryEngine
from tournament_platform.app.services.audio_cues import tts_mode_options, apply_tts_selection, build_test_tts_message, maybe_speak_tts

logger = logging.getLogger(__name__)

_commentary_service = CommentaryService()


# ============================================================================
# Accepted Commentary Event Registry
# ============================================================================

@dataclass
class AcceptedCommentaryEvent:
    event_id: str
    match_id: str | None
    event_type: str
    created_at: float
    score_a: int
    score_b: int
    player_a: str
    player_b: str
    server: str | None
    importance: Literal["routine", "notable", "critical"]
    category: Literal["play_by_play", "tactical", "contextual"]
    context: dict | None = None


class CommentaryEventRegistry:
    def __init__(self, maxlen: int = 20) -> None:
        self._events: deque[AcceptedCommentaryEvent] = deque(maxlen=maxlen)

    def record(self, event: AcceptedCommentaryEvent) -> None:
        self._events.append(event)

    def recent(self, n: int = 5) -> list[AcceptedCommentaryEvent]:
        return list(self._events)[-n:]

    def clear(self) -> None:
        self._events.clear()


_commentary_event_registry = CommentaryEventRegistry()


def classify_importance(event_type: str, context: Any = None) -> str:
    critical_types = {
        "deuce", "advantage", "game_point", "match_point",
        "game_won", "match_won",
    }
    notable_types = {
        "three_point_streak", "lead_change", "score_tied_late", "large_lead",
        "break_point", "set_point",
    }
    if event_type in critical_types:
        return "critical"
    if event_type in notable_types:
        return "notable"
    return "routine"


def _style_to_category(style: str) -> str:
    return STYLE_TO_CATEGORY.get(style, "play_by_play")


# ============================================================================
# Session-state diagnostic log helpers
# ============================================================================

def _append_commentary_log_entry(
    *,
    event_id: str,
    status: str,
    text: str,
    match_id: str | None,
    event_type: str,
    style: str,
    language: str,
    provider: str,
    error: str | None = None,
) -> None:
    entry = {
        "event_id": event_id,
        "created_at": time.time(),
        "match_id": match_id,
        "event_type": event_type,
        "style": style,
        "language": language,
        "provider": provider,
        "text": text,
        "status": status,
        "error": error,
    }
    entries = list(st.session_state.get("commentary_log_entries", []))
    entries.append(entry)
    st.session_state["commentary_log_entries"] = entries[-10:]


def update_commentary_log_status(
    event_id: str,
    status: str,
    error: str | None = None,
) -> None:
    entries = list(st.session_state.get("commentary_log_entries", []))
    for entry in reversed(entries):
        if entry.get("event_id") == event_id:
            entry["status"] = status
            if error is not None:
                entry["error"] = error
            break
    st.session_state["commentary_log_entries"] = entries[-10:]


def _reset_commentary_log_for_match() -> None:
    current_match_id = st.session_state.get("voice_selected_match_id")
    if st.session_state.get("commentary_log_match_id") != current_match_id:
        st.session_state["commentary_log_entries"] = []
        st.session_state["commentary_log_match_id"] = current_match_id


def _get_commentary_settings() -> CommentarySettings:
    """Build CommentarySettings from current session state."""
    style_value = normalize_commentary_style_for_ui(
        st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)
    )
    return CommentarySettings(
        enabled=st.session_state.get("commentary_enabled", False),
        style=CommentaryStyle(style_value),
        verbosity=CommentaryVerbosity(st.session_state.get("commentary_verbosity", CommentaryVerbosity.STANDARD.value)),
        voice=st.session_state.get("commentary_voice", "default"),
        language=st.session_state.get("commentary_language", "en"),
        muted=st.session_state.get("commentary_muted", False),
        mode=CommentaryMode(st.session_state.get("commentary_mode", CommentaryMode.EVERY_POINT.value)),
        intensity=CommentaryIntensity(st.session_state.get("commentary_intensity", CommentaryIntensity.MEDIUM.value)),
        speak_generated=st.session_state.get("commentary_speak_generated", True),
        ollama_rewrite_enabled=st.session_state.get("commentary_ollama_rewrite_enabled", False),
        ollama_model=st.session_state.get("commentary_ollama_model", ""),
        ollama_timeout=float(st.session_state.get("commentary_ollama_timeout", 2.0)),
        voice_profile_id=st.session_state.get("commentary_voice_profile", "browser_default"),
        rate=float(st.session_state.get("commentary_rate", 1.0)),
        pitch=float(st.session_state.get("commentary_pitch", 1.0)),
        volume=float(st.session_state.get("commentary_volume", 1.0)),
    )


_CRITICAL_COOLDOWN_S = 10.0



def _is_critical_moment(moment: ScoreMoment) -> bool:
    return moment in (
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



def _apply_critical_cooldown(settings: CommentarySettings, moment: ScoreMoment) -> CommentarySettings:
    if not _is_critical_moment(moment):
        return settings
    last_moment = st.session_state.get("commentary_last_critical_moment")
    last_ts = st.session_state.get("commentary_last_critical_moment_ts", 0.0)
    now = time.time()
    if last_moment == moment and (now - last_ts) < _CRITICAL_COOLDOWN_S:
        return CommentarySettings(
            enabled=settings.enabled,
            style=settings.style,
            verbosity=CommentaryVerbosity.MINIMAL,
            voice=settings.voice,
            language=settings.language,
            muted=settings.muted,
            mode=settings.mode,
            intensity=CommentaryIntensity.LOW,
            speak_generated=settings.speak_generated,
            ollama_rewrite_enabled=settings.ollama_rewrite_enabled,
            ollama_model=settings.ollama_model,
            ollama_timeout=settings.ollama_timeout,
            voice_profile_id=settings.voice_profile_id,
            rate=settings.rate,
            pitch=settings.pitch,
            volume=settings.volume,
        )
    st.session_state.commentary_last_critical_moment = moment
    st.session_state.commentary_last_critical_moment_ts = now
    return settings



def _synthesize_piper_audio(text: str, voice_profile_id: str) -> Optional[str]:
    from tournament_platform.app.services.commentary_voice.voice_catalog import get_profile
    profile = get_profile(voice_profile_id)
    if not profile or profile.engine != "piper":
        return None
    engine = get_piper_engine()
    if not engine.available:
        return None
    voices = engine.list_voices()
    if not voices:
        return None
    voice_map = {v.id: v for v in voices}
    piper_voice = voice_map.get(profile.voice_id or profile.id)
    if not piper_voice:
        piper_voice = next(iter(voices), None)
    if not piper_voice:
        return None
    try:
        result = engine.synthesize(text, piper_voice, rate=float(st.session_state.get("commentary_rate", 1.0)), volume=float(st.session_state.get("commentary_volume", 1.0)))
        return str(result.audio_path)
    except Exception:
        return None



def play_commentary(
    text: str,
    settings: CommentarySettings,
    event_id: str | None = None,
    importance: str | None = None,
) -> None:
    """Route commentary playback to the selected engine with fallback."""
    if settings.mode == CommentaryMode.VISUAL_ONLY:
        return
    if not text:
        return

    _eid = event_id or str(uuid.uuid4())
    update_commentary_log_status(_eid, "dispatch_requested")

    engine_name = st.session_state.get("commentary_tts_engine", "browser")
    if engine_name != "piper":
        tts_lang = "lt-LT" if settings.language == "lt" else "en-US"
        try:
            speak_commentary(
                text=text,
                key=f"commentary_{_eid}",
                voice=settings.voice,
                lang=tts_lang,
                rate=settings.rate,
                pitch=settings.pitch,
                volume=settings.volume,
                voice_profile_id=settings.voice_profile_id,
            )
            update_commentary_log_status(_eid, "synthesis_completed")
        except Exception as exc:
            update_commentary_log_status(_eid, "synthesis_failed", error=str(exc))
        return

    piper_voice_id = st.session_state.get("commentary_piper_voice_id")
    if not piper_voice_id:
        notify_piper_unavailable_once(
            "No Piper voice selected. Choose a Piper voice in commentary settings, "
            "or use Browser speech.",
            level="info",
        )
        update_commentary_log_status(_eid, "synthesis_failed", error="No Piper voice selected")
        return

    from tournament_platform.app.services.commentary_voice.voice_catalog import get_profile
    profile = get_profile(piper_voice_id)
    if not profile or profile.engine != "piper":
        notify_piper_unavailable_once(
            "Piper voice not found. Browser speech is available as a fallback.",
            level="info",
        )
        update_commentary_log_status(_eid, "synthesis_failed", error="Piper voice not found")
        return

    engine = get_piper_engine()
    if not engine.available:
        notify_piper_unavailable_once(
            "Piper local TTS is not available in this environment. "
            "Browser speech is available as a fallback.",
            level="info",
        )
        update_commentary_log_status(_eid, "synthesis_failed", error="Piper engine unavailable")
        return

    voices = engine.list_voices()
    voice_map = {v.id: v for v in voices}
    piper_voice = voice_map.get(piper_voice_id)
    if not piper_voice:
        notify_piper_unavailable_once(
            "Piper voice model not found. Browser speech is available as a fallback.",
            level="info",
        )
        update_commentary_log_status(_eid, "synthesis_failed", error="Piper voice model not found")
        return

    try:
        result = engine.synthesize(
            text,
            piper_voice,
            rate=float(settings.rate),
            volume=float(settings.volume),
        )
        speak_commentary_audio_file(result.audio_path, key=f"piper_{_eid}")
        st.session_state.last_commentary_engine = "piper"
        st.session_state.last_commentary_voice_id = piper_voice_id
        st.session_state.last_commentary_audio_path = str(result.audio_path)
        update_commentary_log_status(_eid, "synthesis_completed")
    except PiperTTSError as exc:
        st.warning(f"Piper synthesis failed: {exc}. Falling back to browser speech.")
        update_commentary_log_status(_eid, "synthesis_failed", error=str(exc))
        tts_lang = "lt-LT" if settings.language == "lt" else "en-US"
        try:
            speak_commentary(
                text=text,
                key=f"commentary_{_eid}",
                voice=settings.voice,
                lang=tts_lang,
                rate=settings.rate,
                pitch=settings.pitch,
                volume=settings.volume,
                voice_profile_id=settings.voice_profile_id,
            )
            update_commentary_log_status(_eid, "synthesis_completed")
        except Exception as fb_exc:
            update_commentary_log_status(_eid, "playback_failed", error=str(fb_exc))
        st.session_state.last_commentary_engine = "browser"
        st.session_state.last_commentary_voice_id = None
        st.session_state.last_commentary_audio_path = None



def _event_type_to_tt(event_type: str, state: Any) -> TTEventType:
    if event_type in ("point_a", "point_b", "point_scored"):
        return TTEventType.POINT_WON
    if event_type == "undo":
        return TTEventType.POINT_LOST
    if event_type == "serve":
        return TTEventType.SERVE_POINT
    if event_type == "deuce":
        return TTEventType.DEUCE
    if event_type == "advantage":
        return TTEventType.ADVANTAGE
    if event_type == "game_point":
        return TTEventType.GAME_POINT
    if event_type == "match_point":
        return TTEventType.MATCH_POINT
    if event_type == "set_win":
        return TTEventType.GAME_WON
    if event_type == "match_win":
        return TTEventType.MATCH_WON
    if event_type == "manual_score_change":
        return TTEventType.MANUAL_SCORE_CHANGE
    if event_type == "voice_score_confirmed":
        return TTEventType.VOICE_SCORE_CONFIRMED
    if event_type == "voice_score_rejected":
        return TTEventType.VOICE_SCORE_REJECTED
    return TTEventType.POINT_WON



def _build_local_commentary(
    event_type: str,
    state: Any,
    previous_state: Optional[Any],
    settings: Any,
    event_id: str,
) -> CommentaryLine:
    """Generate commentary using the local template engine and wrap it in a CommentaryLine."""
    tt_evt = _event_type_to_tt(event_type, state)
    player_a = getattr(state, "player_a", "Player A")
    player_b = getattr(state, "player_b", "Player B")
    player = player_a
    opponent = player_b
    if event_type in ("point_b",):
        player = player_b
        opponent = player_a

    serving_player = getattr(state, "serving_player", "") or player_a

    evt_data = CommentaryEventData(
        event_type=tt_evt,
        player=player,
        opponent=opponent,
        serving_player=serving_player,
        language=str(settings.language or "en"),
        style=normalize_commentary_style(getattr(settings, "style", CommentaryStyle.NEUTRAL.value)),
        score=f"{getattr(state, 'score_a', 0)} to {getattr(state, 'score_b', 0)}",
        game_score=f"{getattr(state, 'score_a', 0)}–{getattr(state, 'score_b', 0)}",
        match_score=f"{getattr(state, 'sets_a', 0)} to {getattr(state, 'sets_b', 0)}",
    )

    ctx = MatchContextBuilder.from_spoken_score_state(state)
    detail = st.session_state.get("commentary_detail", "standard")
    fast_score_change = False  # could be set externally when rapid scoring is detected

    engine = CommentaryEngine()
    generated = engine.generate_commentary(
        evt_data,
        ctx,
        spoken_enabled=bool(getattr(settings, "enabled", False)),
        fast_score_change=fast_score_change,
        detail=detail,
    )

    text = generated.final_text or generated.text or ""
    should_speak = generated.should_speak
    priority = 2
    if tt_evt in (TTEventType.GAME_WON, TTEventType.MATCH_WON, TTEventType.DEUCE, TTEventType.ADVANTAGE, TTEventType.GAME_POINT, TTEventType.MATCH_POINT):
        priority = 3

    line = CommentaryLine(
        text=text,
        event_type=event_type,
        priority=priority,
        should_speak=should_speak,
        dedupe_key=f"{event_type}:{event_id}",
        event_id=event_id,
        generated_text=generated.generated_text,
        final_text=generated.final_text,
        template_language=generated.language,
        template_style=generated.style,
        base_template=generated.base_template,
        used_fallback=generated.used_fallback,
        fallback_reason=None,
        mixed_language_detected=generated.mixed_language_detected,
        used_ollama=False,
        ollama_rejected_reason=None,
        tts_language_code=generated.tts_language_code,
        cache_key=None,
        cache_hit=False,
        selected_language=evt_data.language,
        normalized_language=generated.language,
        event_id_str=tt_evt.value,
    )
    line._local_commentary = generated
    return line



def _build_and_store_commentary(
    event_type: str,
    state: Any,
    previous_state: Optional[Any] = None,
) -> None:
    """
    Build a commentary line and store it in session_state.pending_commentary
    if it should be spoken (respects dedupe and settings).
    """
    event_id = str(uuid.uuid4())
    settings = _get_commentary_settings()

    spoken_state = SpokenScoreState.from_match_state(state)
    prev_spoken = SpokenScoreState.from_match_state(previous_state) if previous_state else None

    engine_choice = st.session_state.get("commentary_engine", "legacy")

    if engine_choice == "local":
        line = _build_local_commentary(
            event_type=event_type,
            state=state,
            previous_state=previous_state,
            settings=settings,
            event_id=event_id,
        )
    else:
        moment = _commentary_service.classify_score_moment(spoken_state, prev_spoken)
        settings = _apply_critical_cooldown(settings, moment)

        line = _commentary_service.build_score_commentary(
            event_type=event_type,
            state=spoken_state,
            settings=settings,
            event_id=event_id,
            previous_state=prev_spoken,
        )

    if line.final_text and settings.language != "en":
        tts_lang = "lt-LT" if settings.language == "lt" else "en-US"
        line.tts_language_code = tts_lang

    should_speak = _commentary_service.should_speak_commentary(
        last_event_id=st.session_state.get("last_commentary_event_id"),
        current_event_id=event_id,
        settings=settings,
    )
    if not should_speak and engine_choice == "local":
        # Local engine already encodes speak intent in GeneratedCommentary.should_speak,
        # but we still gate with the legacy dedupe/disabled checks.
        local_line = getattr(line, "_local_commentary", None)
        if local_line is not None:
            should_speak = local_line.should_speak

    if should_speak:
        st.session_state.pending_commentary = line
        st.session_state.last_commentary_event_id = event_id
        st.session_state.last_commentary_text = line.text
        st.session_state.pending_local_audio = None
        st.session_state.last_commentary_debug = {
            "selected_language": getattr(line, "selected_language", settings.language),
            "normalized_language": getattr(line, "normalized_language", settings.language),
            "event_id": getattr(line, "event_id", event_id),
            "event_id_str": getattr(line, "event_id_str", event_type),
            "template_language": getattr(line, "template_language", ""),
            "template_style": getattr(line, "template_style", ""),
            "base_template": getattr(line, "base_template", ""),
            "generated_text": getattr(line, "generated_text", ""),
            "final_text": getattr(line, "final_text", ""),
            "used_fallback": getattr(line, "used_fallback", False),
            "fallback_reason": getattr(line, "fallback_reason", None),
            "mixed_language_detected": getattr(line, "mixed_language_detected", False),
            "used_ollama": getattr(line, "used_ollama", False),
            "ollama_rejected_reason": getattr(line, "ollama_rejected_reason", None),
            "spoken": getattr(line, "should_speak", True),
            "tts_language_code": getattr(line, "tts_language_code", "en-US"),
            "cache_key": getattr(line, "cache_key", None),
            "cache_hit": getattr(line, "cache_hit", False),
        }
        _append_commentary_log_entry(
            event_id=event_id,
            status="generated",
            text=line.text,
            match_id=str(st.session_state.get("voice_selected_match_id") or "none"),
            event_type=event_type,
            style=settings.style.value,
            language=settings.language,
            provider="legacy" if engine_choice == "legacy" else "local",
        )
    else:
        st.session_state.pending_commentary = None
        st.session_state.pending_local_audio = None



def _emit_set_win_commentary(game_event: dict, *, speak: bool) -> bool:
    """Emit set_win commentary for a finished game with dedupe and mode gating.

    Returns True if commentary was emitted, False otherwise.
    """
    match_id = str(st.session_state.get("voice_selected_match_id") or "none")
    game_number = int(game_event.get("game_number", 1))
    winner = game_event.get("winner", "")
    game_score = game_event.get("game_score", "")
    dedupe_key = f"{match_id}:set_win:{game_number}:{winner}:{game_score}"

    emitted_keys = st.session_state.get("commentary_emitted_game_keys", [])
    if dedupe_key in emitted_keys:
        return False

    settings = _get_commentary_settings()
    if not settings.enabled or settings.muted:
        return False

    engine_choice = st.session_state.get("commentary_engine", "legacy")

    if engine_choice == "local":
        from tournament_platform.app.services.commentary.event_schema import CommentaryEventData, TTEventType
        from tournament_platform.app.services.commentary.match_context import MatchContextBuilder

        player_a = game_event.get("player_a", winner)
        player_b = game_event.get("loser", player_a)
        serving_player = player_a

        evt_data = CommentaryEventData(
            event_type=TTEventType.GAME_WON,
            player=winner,
            opponent=player_b,
            serving_player=serving_player,
            language=str(settings.language or "en"),
            style=normalize_commentary_style(getattr(settings, "style", CommentaryStyle.NEUTRAL.value)),
            game_score=game_score,
            match_score=game_event.get("match_score", ""),
            completed_games=game_event.get("completed_games", []),
        )

        state = st.session_state.match_manager.state
        ctx = MatchContextBuilder.from_spoken_score_state(state)
        if ctx.completed_games:
            ctx.current_game = len(ctx.completed_games) + 1

        detail = st.session_state.get("commentary_detail", "standard")
        engine = CommentaryEngine()
        generated = engine.generate_commentary(
            evt_data,
            ctx,
            spoken_enabled=settings.enabled and not settings.muted,
            detail=detail,
        )

        text = generated.final_text or generated.text or ""
        priority = 3
        should_speak = speak and generated.should_speak

        line = CommentaryLine(
            text=text,
            event_type="set_win",
            priority=priority,
            should_speak=should_speak,
            dedupe_key=dedupe_key,
            event_id=str(uuid.uuid4()),
            generated_text=generated.generated_text,
            final_text=generated.final_text,
            template_language=generated.language,
            template_style=generated.style,
            base_template=generated.base_template,
            used_fallback=generated.used_fallback,
            fallback_reason=None,
            mixed_language_detected=generated.mixed_language_detected,
            used_ollama=False,
            ollama_rejected_reason=None,
            tts_language_code=generated.tts_language_code,
            cache_key=None,
            cache_hit=False,
            selected_language=evt_data.language,
            normalized_language=generated.language,
            event_id_str="game_won",
        )
        line._local_commentary = generated
    else:
        should_gen = _commentary_service.should_generate(
            "set_win",
            ImportanceLevel.CRITICAL,
            settings.mode,
            settings.intensity,
        )
        if not should_gen:
            return False

        line = _commentary_service.build_set_win_commentary(game_event, settings)
        line.should_speak = speak and settings.mode not in (CommentaryMode.OFF, CommentaryMode.VISUAL_ONLY)

    debug_info = {
        "game_number": game_number,
        "winner": winner,
        "loser": game_event.get("loser", ""),
        "game_score": game_score,
        "match_score": game_event.get("match_score", ""),
        "completed_games": game_event.get("completed_games", []),
        "dedupe_key": dedupe_key,
        "event_id": getattr(line, "event_id", ""),
        "event_id_str": getattr(line, "event_id_str", "set_win"),
        "selected_language": getattr(line, "selected_language", settings.language),
        "normalized_language": getattr(line, "normalized_language", ""),
        "template_language": getattr(line, "template_language", ""),
        "template_style": getattr(line, "template_style", ""),
        "base_template": getattr(line, "base_template", ""),
        "generated_text": getattr(line, "generated_text", ""),
        "final_text": getattr(line, "final_text", ""),
        "used_fallback": getattr(line, "used_fallback", False),
        "fallback_reason": getattr(line, "fallback_reason", None),
        "mixed_language_detected": getattr(line, "mixed_language_detected", False),
        "used_ollama": getattr(line, "used_ollama", False),
        "ollama_rejected_reason": getattr(line, "ollama_rejected_reason", None),
        "spoken": getattr(line, "should_speak", True),
        "tts_language_code": getattr(line, "tts_language_code", "en-US"),
        "cache_key": getattr(line, "cache_key", None),
        "cache_hit": getattr(line, "cache_hit", False),
    }

    try:
        from tournament_platform.models import SessionLocal
        db = SessionLocal()
        log_commentary_event(
            db_session=db,
            tournament_id=st.session_state.get("voice_selected_tournament_id"),
            match_id=int(match_id) if match_id != "none" else None,
            player_a=game_event.get("player_a"),
            player_b=game_event.get("player_b"),
            event_type="set_win",
            source_event_json=json.dumps({
                "game_number": game_number,
                "winner": winner,
                "loser": game_event.get("loser", ""),
                "game_score": game_score,
                "match_score": game_event.get("match_score", ""),
                "completed_games": game_event.get("completed_games", []),
                "language": getattr(line, "normalized_language", settings.language),
                "style": getattr(line, "template_style", "neutral"),
                "dedupe_key": dedupe_key,
            }, default=str),
            score_before_json=None,
            score_after_json=None,
            style=getattr(line, "template_style", "neutral") or "neutral",
            language=getattr(line, "normalized_language", "en") or "en",
            commentary_mode=settings.mode.value,
            intensity=settings.intensity.value,
            template_id=getattr(line, "base_template", None),
            generated_text=getattr(line, "generated_text", "") or "",
            final_text=getattr(line, "final_text", "") or "",
            used_ollama=getattr(line, "used_ollama", False),
            ollama_model=getattr(_commentary_service.rewriter, "model", None) if _commentary_service.rewriter else None,
            ollama_cache_hit=getattr(line, "cache_hit", False),
            spoken=getattr(line, "should_speak", True),
            tts_mode="browser",
            latency_ms=None,
            error=None,
            cache_key=getattr(line, "cache_key", None),
        )
    except Exception:
        pass

    st.session_state.pending_commentary = line
    st.session_state.last_commentary_event_id = getattr(line, "event_id", "")
    st.session_state.last_commentary_text = line.text
    st.session_state.last_set_win_text = getattr(line, "final_text", "")
    st.session_state.last_commentary_debug = debug_info
    st.session_state.commentary_emitted_game_keys = emitted_keys + [dedupe_key]
    _append_commentary_log_entry(
        event_id=getattr(line, "event_id", ""),
        status="generated",
        text=line.text,
        match_id=match_id if match_id != "none" else None,
        event_type="set_win",
        style=settings.style.value,
        language=settings.language,
        provider="legacy" if st.session_state.get("commentary_engine", "legacy") == "legacy" else "local",
    )
    return True



def _reconcile_finished_games() -> None:
    """Emit set_win commentary for every finished game exactly once per game."""
    _e = st.session_state.match_manager.engine
    games = list(_e.round_scores)
    mid = st.session_state.get("voice_selected_match_id")
    match_id = str(mid) if mid else "none"
    _mm = st.session_state.match_manager

    for i, (a, b) in enumerate(games):
        game_number = i + 1
        winner_label = "A" if a > b else "B"
        winner_name = _mm.state.player_a if winner_label == "A" else _mm.state.player_b
        loser_name = _mm.state.player_b if winner_label == "A" else _mm.state.player_a
        game_score = f"{a}\u2013{b}"
        match_score = f"{_e.games_won_a}\u2013{_e.games_won_b}"
        completed_games = [f"{x}\u2013{y}" for x, y in games]

        _emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": game_number,
            "winner": winner_name,
            "loser": loser_name,
            "game_score": game_score,
            "match_score": match_score,
            "completed_games": completed_games,
            "language": st.session_state.get("commentary_language", "en"),
            "style": normalize_commentary_style(st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)),
            "match_id": match_id,
            "player_a": _mm.state.player_a,
            "player_b": _mm.state.player_b,
        }, speak=True)

    # Emit match_won commentary when the match is complete.
    if _e.match_status == "match_won":
        winner_name = _mm.state.player_a if _e.games_won_a > _e.games_won_b else _mm.state.player_b
        loser_name = _mm.state.player_b if _e.games_won_a > _e.games_won_b else _mm.state.player_a
        match_score = f"{_e.games_won_a}\u2013{_e.games_won_b}"
        completed_games = [f"{x}\u2013{y}" for x, y in games]
        dedupe_key = f"{match_id}:match_won:{winner_name}:{match_score}"

        emitted_keys = st.session_state.get("commentary_emitted_game_keys", [])
        if dedupe_key not in emitted_keys:
            if st.session_state.get("commentary_engine") == "local":
                from tournament_platform.app.services.commentary.event_schema import CommentaryEventData, TTEventType
                from tournament_platform.app.services.commentary.match_context import MatchContextBuilder

                evt_data = CommentaryEventData(
                    event_type=TTEventType.MATCH_WON,
                    player=winner_name,
                    opponent=loser_name,
                    serving_player=winner_name,
                    language=str(st.session_state.get("commentary_language", "en")),
                    style=normalize_commentary_style(st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)),
                    match_score=match_score,
                    completed_games=completed_games,
                )
                state = _mm.state
                ctx = MatchContextBuilder.from_spoken_score_state(state)
                ctx.games_won_a = _e.games_won_a
                ctx.games_won_b = _e.games_won_b
                ctx.completed_games = completed_games

                engine = CommentaryEngine()
                generated = engine.generate_commentary(
                    evt_data,
                    ctx,
                    spoken_enabled=True,
                    detail=st.session_state.get("commentary_detail", "standard"),
                )
                text = generated.final_text or generated.text or ""
                line = CommentaryLine(
                    text=text,
                    event_type="match_won",
                    priority=3,
                    should_speak=True,
                    dedupe_key=dedupe_key,
                    event_id=str(uuid.uuid4()),
                    generated_text=generated.generated_text,
                    final_text=generated.final_text,
                    template_language=generated.language,
                    template_style=generated.style,
                    base_template=generated.base_template,
                    used_fallback=generated.used_fallback,
                    fallback_reason=None,
                    mixed_language_detected=generated.mixed_language_detected,
                    used_ollama=False,
                    ollama_rejected_reason=None,
                    tts_language_code=generated.tts_language_code,
                    cache_key=None,
                    cache_hit=False,
                    selected_language=evt_data.language,
                    normalized_language=generated.language,
                    event_id_str="match_won",
                )
                line._local_commentary = generated
                st.session_state.pending_commentary = line
                st.session_state.last_commentary_event_id = line.event_id
                st.session_state.last_commentary_text = line.text
                _append_commentary_log_entry(
                    event_id=line.event_id,
                    status="generated",
                    text=line.text,
                    match_id=match_id if match_id != "none" else None,
                    event_type="match_won",
                    style=normalize_commentary_style(st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)),
                    language=st.session_state.get("commentary_language", "en"),
                    provider="local",
                )
            st.session_state.commentary_emitted_game_keys = emitted_keys + [dedupe_key]



def render_commentary_settings() -> None:
    """Render the commentary settings UI."""
    if "webrtc_diag_available" not in st.session_state:
        st.session_state.webrtc_diag_available = False

    st.session_state.setdefault("commentary_log_entries", [])
    st.session_state.setdefault("commentary_log_match_id", None)
    _reset_commentary_log_for_match()

    with st.expander("🔊 Spoken Commentary", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.commentary_enabled = st.toggle(
                 "Generate commentary",
                 value=st.session_state.get("commentary_enabled", False),
                 help="Turn spoken commentary on or off.",
            )
            _current_style = normalize_commentary_style_for_ui(
                st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)
            )
            st.session_state.commentary_style = st.selectbox(
                "Style",
                options=list(RETAINED_STYLES),
                index=list(RETAINED_STYLES).index(_current_style),
                help="Professional = play-by-play, Coach = tactical, Announcer = contextual.",
            )
            _engine_options = ["legacy", "local"]
            _engine_labels = {"legacy": "Legacy", "local": "Local template engine"}
            _current_engine = st.session_state.get("commentary_engine", "legacy")
            _engine_idx = _engine_options.index(_current_engine) if _current_engine in _engine_options else 0
            st.session_state.commentary_engine = st.selectbox(
                "Commentary engine",
                options=_engine_options,
                format_func=lambda k: _engine_labels.get(k, k),
                index=_engine_idx,
                help="Choose the commentary generation path. Legacy uses the existing templates; Local uses the new TT template bank.",
            )
        with col2:
            st.session_state.commentary_verbosity = st.selectbox(
                "Verbosity",
                options=[v.value for v in CommentaryVerbosity],
                 index=[v.value for v in CommentaryVerbosity].index(st.session_state.get("commentary_verbosity", CommentaryVerbosity.STANDARD.value)),
            )
            _detail_options = ["short", "standard", "tactical"]
            _detail_labels = {"short": "Short", "standard": "Standard", "tactical": "Tactical"}
            _current_detail = st.session_state.get("commentary_detail", "standard")
            _detail_idx = _detail_options.index(_current_detail) if _current_detail in _detail_options else 1
            st.session_state.commentary_detail = st.selectbox(
                "Commentary detail",
                options=_detail_options,
                format_func=lambda k: _detail_labels.get(k, k),
                index=_detail_idx,
                help="Short = minimal output. Standard = normal play-by-play. Tactical = include tactical commentary when available.",
            )

        # --- Generated commentary subsection ---
        with st.expander("Generated commentary", expanded=True):
            col_gc1, col_gc2 = st.columns(2)
            with col_gc1:
                _lang_options = {
                    "English": "en",
                    "Lithuanian": "lt",
                }
                _current_lang = st.session_state.get("commentary_language", "en")
                _normalized_current = CommentaryService._normalize_language(_current_lang)
                _lang_values = list(_lang_options.values())
                _selected_idx = _lang_values.index(_normalized_current) if _normalized_current in _lang_values else 0
                _selected_label = st.selectbox(
                    "Language",
                    options=list(_lang_options.keys()),
                    index=_selected_idx,
                    key="commentary_language_select",
                )
                st.session_state.commentary_language = _lang_options[_selected_label]
            with col_gc2:
                _freq_options = [m.value for m in CommentaryMode]
                _freq_labels = {
                    "off": "Off",
                    "visual_only": "Visual only",
                    "important_only": "Key moments",
                    "after_every_game": "After every game",
                    "every_point": "Every point",
                    "spoken": "Spoken commentary",
                }
                _mode_display = [_freq_labels.get(v, v) for v in _freq_options]
                _current_mode = st.session_state.get("commentary_mode", CommentaryMode.EVERY_POINT.value)
                _mode_idx = _freq_options.index(_current_mode) if _current_mode in _freq_options else 0
                _new_mode_label = st.selectbox(
                    "Frequency",
                    options=_mode_display,
                    index=_mode_idx,
                    key="commentary_mode_select",
                )
                _new_mode = _freq_options[_mode_display.index(_new_mode_label)]
                if _new_mode != _current_mode:
                    st.session_state.commentary_mode = _new_mode
                    st.rerun()

            _int_col, _speak_col = st.columns(2)
            with _int_col:
                _int_options = [i.value for i in CommentaryIntensity]
                _current_int = st.session_state.get("commentary_intensity", CommentaryIntensity.MEDIUM.value)
                _int_idx = _int_options.index(_current_int) if _current_int in _int_options else 1
                st.session_state.commentary_intensity = st.selectbox(
                    "Intensity",
                    options=_int_options,
                    index=_int_idx,
                    key="commentary_intensity_select",
                )
            with _speak_col:
                st.session_state.commentary_speak_generated = st.checkbox(
                    "Speak generated commentary",
                    value=st.session_state.get("commentary_speak_generated", True),
                    key="commentary_speak_generated_checkbox",
                )

        # --- Score feedback subsection ---
        with st.expander("Score feedback", expanded=False):
            render_sound_toggle()

            _tts = st.session_state.voice_tts_adapter
            _tts_mode_values, _tts_options = tts_mode_options()
            _tts_idx = _tts_mode_values.index(_tts.mode.value) if _tts.mode.value in _tts_mode_values else 0
            _new_tts_label = st.selectbox(
                "TTS mode",
                options=_tts_options,
                index=_tts_idx,
                key="tts_mode_select",
                help="Spoken score announcements (e.g. 'Tomas Z leads 5 to 3'). Choose how often the scoreboard speaks.",
            )
            _new_tts_mode = _tts_mode_values[_tts_options.index(_new_tts_label)]
            if _new_tts_mode != _tts.mode.value:
                apply_tts_selection(_tts, _new_tts_mode)
                st.rerun()

            st.divider()

            if st.button("🔊 Test sound", key="audio_test_sound", use_container_width=True):
                if st.session_state.get("sound_cues_enabled", False):
                    play_cue("point")
                if _tts.enabled and _tts.mode not in (TTSMode.OFF, TTSMode.VISUAL_ONLY):
                    maybe_speak_tts(build_test_tts_message(st.session_state.match_manager), "increment")

            st.caption(
                "If nothing plays, click once or interact with the scoreboard — "
                "browsers may block audio until your first click. Ensure the tab isn't muted."
            )

            if not st.session_state.get("sound_cues_enabled", False) and not _tts.enabled:
                st.info("Audio is off. Scores still update as text.")

        # --- TTS provider subsection ---
        with st.expander("TTS provider", expanded=False):
            _piper_ok = is_piper_available()
            _engine_options = ["browser", "piper"]
            _engine_labels = {
                "browser": "Browser speech",
                "piper": "Piper local voices" + ("" if _piper_ok else " (unavailable)"),
            }
            _current_engine = st.session_state.get("commentary_tts_engine", "browser")
            _engine_idx = _engine_options.index(_current_engine) if _current_engine in _engine_options else 0
            _new_engine = st.selectbox(
                "Engine",
                options=_engine_options,
                format_func=lambda e: _engine_labels.get(e, e),
                index=_engine_idx,
                key="commentary_tts_engine_select",
                help=(
                    "Browser speech is recommended for Streamlit Cloud. "
                    "Piper local is optional for local desktop use."
                ),
            )
            st.session_state.commentary_tts_engine = _new_engine

            if _new_engine == "piper":
                if not _piper_ok:
                    st.info(
                        "Piper local TTS is not available in this environment. "
                        "Browser speech is available as a fallback."
                    )
                else:
                    piper_voices = find_piper_voices()
                    if not piper_voices:
                        st.info(
                            "No Piper voices found. Add `.onnx` and `.onnx.json` files to "
                            "`tournament_platform/assets/tts/piper/voices/` to enable local voices."
                        )
                    else:
                        _piper_voice_options = [v.id for v in piper_voices]
                        _piper_voice_labels = {v.id: v.label for v in piper_voices}
                        _current_piper_voice = st.session_state.get("commentary_piper_voice_id")
                        _pv_idx = _piper_voice_options.index(_current_piper_voice) if _current_piper_voice in _piper_voice_options else 0
                        _new_pv = st.selectbox(
                            "Piper voice",
                            options=_piper_voice_options,
                            format_func=lambda vid: _piper_voice_labels.get(vid, vid),
                            index=_pv_idx,
                            key="commentary_piper_voice_select",
                        )
                        st.session_state.commentary_piper_voice_id = _new_pv

                        _speed_col, _vol_col = st.columns(2)
                        with _speed_col:
                            st.session_state.commentary_rate = st.slider(
                                "Piper speed",
                                min_value=0.8,
                                max_value=1.2,
                                step=0.05,
                                value=float(st.session_state.get("commentary_rate", 1.0)),
                                key="piper_rate_slider",
                            )
                        with _vol_col:
                            st.session_state.commentary_volume = st.slider(
                                "Piper volume",
                                min_value=0.0,
                                max_value=1.0,
                                step=0.05,
                                value=float(st.session_state.get("commentary_volume", 1.0)),
                                key="piper_volume_slider",
                            )
                        if st.button("🔊 Test Piper voice", use_container_width=True, key="test_piper_voice_button"):
                            settings = _get_commentary_settings()
                            play_commentary(
                                text="Game point for Red. 10 to 8.",
                                settings=settings,
                                event_id=str(uuid.uuid4()),
                            )

            _rate_col, _pitch_col = st.columns(2)
            with _rate_col:
                st.session_state.commentary_rate = st.slider(
                    "Rate",
                    min_value=0.5,
                    max_value=2.0,
                    step=0.05,
                    value=float(st.session_state.get("commentary_rate", 1.0)),
                    key="commentary_rate_slider",
                )
            with _pitch_col:
                st.session_state.commentary_pitch = st.slider(
                    "Pitch",
                    min_value=0.5,
                    max_value=2.0,
                    step=0.05,
                    value=float(st.session_state.get("commentary_pitch", 1.0)),
                    key="commentary_pitch_slider",
                )
            st.session_state.commentary_volume = st.slider(
                "Volume",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                value=float(st.session_state.get("commentary_volume", 1.0)),
                key="commentary_volume_slider",
            )
            if st.button("🔊 Test voice", use_container_width=True, key="test_voice_button"):
                settings = _get_commentary_settings()
                play_commentary(
                    text="Game point for Red. 10 to 8.",
                    settings=settings,
                    event_id=str(uuid.uuid4()),
                )

        # --- Ollama rewrite ---
        with st.expander("🤖 Local Ollama rewrite", expanded=False):
            st.session_state.commentary_ollama_rewrite_enabled = st.checkbox(
                "Use local Ollama to rewrite commentary",
                value=st.session_state.get("commentary_ollama_rewrite_enabled", False),
                key="commentary_ollama_rewrite_checkbox",
                help="Requires Ollama running locally. Disabled by default.",
            )
            if st.session_state.commentary_ollama_rewrite_enabled:
                _default_model = st.session_state.get("commentary_ollama_model", "") or "llama3:latest"
                st.session_state.commentary_ollama_model = st.text_input(
                    "Ollama model",
                    value=_default_model,
                    key="commentary_ollama_model_input",
                )
                st.session_state.commentary_ollama_timeout = st.number_input(
                    "Timeout (seconds)",
                    min_value=0.5,
                    max_value=10.0,
                    step=0.5,
                    value=float(st.session_state.get("commentary_ollama_timeout", 2.0)),
                    key="commentary_ollama_timeout_input",
                )

        # --- Audio diagnostics ---
        with st.expander("🩺 Audio diagnostics", expanded=False):
            _piper_ok = is_piper_available()
            if "webrtc_diag_available" not in st.session_state:
                st.session_state.webrtc_diag_available = False

            def _debug_value(value: Any, max_len: int = 300) -> str:
                if value is None:
                    return "—"
                text = str(value).replace("\n", " ").strip()
                if len(text) > max_len:
                    return text[:max_len] + "…"
                return text

            _diag_webrtc = (
                "installed" if st.session_state.get("webrtc_diag_available") else "missing"
            )
            _diag_piper = "available" if _piper_ok else "missing"
            _diag_engine = st.session_state.get("commentary_tts_engine", "browser")
            _diag_voice_input = (
                "live microphone" if st.session_state.get("voice_scoring_enabled")
                else "push-to-talk"
            )
            _diag_browser_fallback = (
                "enabled" if _diag_engine in ("browser", "auto") or not _piper_ok
                else "disabled"
            )
            _debug_items = [
                ("streamlit-webrtc", _diag_webrtc),
                ("Piper local", _diag_piper),
                ("selected TTS mode", _diag_engine),
                ("selected voice input mode", _diag_voice_input),
                ("browser speech fallback", _diag_browser_fallback),
            ]
            st.markdown(
                "\n".join(
                    f"- {label}: **{_debug_value(value)}**"
                    for label, value in _debug_items
                )
            )

        # --- Recent commentary events (diagnostic ring buffer) ---
        with st.expander("🩺 Recent commentary events (last 10)", expanded=False):
            _entries = st.session_state.get("commentary_log_entries", [])
            if not _entries:
                st.caption("No commentary events yet.")
            else:
                for _i, _entry in enumerate(reversed(_entries[-10:]), 1):
                    _ts = time.strftime("%H:%M:%S", time.localtime(_entry.get("created_at", 0)))
                    _status = _entry.get("status", "unknown")
                    _style = _entry.get("style", "—")
                    _provider = _entry.get("provider", "—")
                    _text = _entry.get("text", "")
                    _error = _entry.get("error")
                    st.caption(f"**{_i}. {_ts} · {_style} · {_provider} · {_status}**")
                    if _text:
                        st.caption(f'  "{_text}"')
                    if _error:
                        st.caption(f'  ⚠ {_error}')

        # --- Commentary debug (moved from standalone panel) ---
        _debug = st.session_state.get("last_commentary_debug")
        if _debug:
            with st.expander("🐛 Commentary debug", expanded=False):
                for k, v in _debug.items():
                    st.caption(f"**{k}**: `{v}`")



def render_pending_commentary() -> None:
    """Render the pending commentary line (speech + text preview) and clear it."""
    pending = st.session_state.get("pending_commentary")
    if not pending:
        st.session_state.pending_local_audio = None
        return

    settings = _get_commentary_settings()
    if settings.enabled and not settings.muted and pending.should_speak:
        play_commentary(
            text=pending.text,
            settings=settings,
            event_id=pending.event_id,
        )

    if pending.text:
        st.caption(f"🔊 {pending.text}")

    st.session_state.pending_commentary = None
    st.session_state.pending_local_audio = None



def render_commentary_debug() -> None:
    """Render the commentary debug panel."""
    debug = st.session_state.get("last_commentary_debug")
    if not debug:
        return
    with st.expander("🐛 Commentary debug", expanded=False):
        for k, v in debug.items():
            st.caption(f"**{k}**: `{v}`")



def render_commentary_log() -> None:
    """Show recent commentary events from the session-state ring buffer."""
    _match_id = st.session_state.get("voice_selected_match_id")
    _reset_commentary_log_for_match()
    entries = st.session_state.get("commentary_log_entries", [])
    if not entries:
        st.caption("No commentary events yet.")
        return
    st.markdown("**Recent commentary**")
    for entry in reversed(entries[-10:]):
        _ts = time.strftime("%H:%M:%S", time.localtime(entry.get("created_at", 0)))
        _status = entry.get("status", "unknown")
        _style = entry.get("style", "—")
        _provider = entry.get("provider", "—")
        _text = entry.get("text", "")
        _error = entry.get("error")
        st.caption(f"**{_ts} · {_style} · {_provider} · {_status}**")
        if _text:
            st.caption(f'  "{_text}"')
        if _error:
            st.caption(f'  ⚠ {_error}')


# ============================================================================
# Helper Functions
# ============================================================================


