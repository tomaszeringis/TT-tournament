"""
Voice Service Layer (Phase 8)

Extracts the core voice scoring pipeline behind a service boundary so it can be
used by both the Streamlit UI and future FastAPI/WebSocket/PWA clients.

Design:
- Stateless service methods that accept explicit inputs and return outputs.
- No Streamlit dependencies.
- All state mutations go through MatchManager (existing rules unchanged).
- Feature-flagged: respects VOICE_ENABLE_* flags from settings.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.app.services.voice_parser import VoiceParser, VoiceScoreEvent
from tournament_platform.models import VoiceEvent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult
from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice_asr import LocalASR, LocalASRError
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor
from tournament_platform.app.services.voice_speaker import SpeakerTagger
from tournament_platform.app.services.voice_tts import TTSConfirmationAdapter, TTSMode
from tournament_platform.app.services.voice_llm import LLMInterpreter, LLMInterpreterError
from tournament_platform.services.settings import (
    VOICE_ENABLE_SPEAKER_ID,
    VOICE_ENABLE_TTS_CONFIRMATION,
    VOICE_ENABLE_LLM_INTERPRETER,
    VOICE_TTS_MODE,
    VOICE_SPEAKER_MODE,
    VOICE_SPEAKER_REQUIRE,
    VOICE_ASR_VOCAB_FILE,
    VOICE_DEBUG_EVENTS,
    VOICE_ENABLE_CONFIRMATION,
    VOICE_DATASET_OPT_IN,
)

logger = logging.getLogger(__name__)


class VoiceServiceError(Exception):
    """Raised when the voice service cannot process a request."""
    pass


class VoiceService:
    """
    Stateless service for voice scoring operations.

    Can be used by:
    - Streamlit UI (current)
    - FastAPI REST endpoints (Phase 8)
    - WebSocket clients (Phase 8)
    - Future PWA/mobile frontends (Phase 8)
    """

    def __init__(
        self,
        match_manager: Optional[MatchManager] = None,
        vocabulary: Optional[VoiceVocabulary] = None,
    ):
        """
        Initialize the voice service.

        Args:
            match_manager: MatchManager instance for a specific match.
                          If None, one will be created for new matches.
            vocabulary: Optional VoiceVocabulary for ASR biasing/post-processing.
        """
        self.match_manager = match_manager
        self.vocabulary = vocabulary or VoiceVocabulary.load(VOICE_ASR_VOCAB_FILE)
        self.parser = VoiceParser()
        self.post_processor = TranscriptPostProcessor(self.vocabulary)
        self.asr = LocalASR(vocabulary=self.vocabulary)
        self.speaker_tagger = SpeakerTagger(mode=VOICE_SPEAKER_MODE) if VOICE_ENABLE_SPEAKER_ID else None
        self.tts_adapter = (
            TTSConfirmationAdapter(enabled=VOICE_ENABLE_TTS_CONFIRMATION, mode=VOICE_TTS_MODE)
            if VOICE_ENABLE_TTS_CONFIRMATION
            else None
        )
        self.llm_interpreter = (
            LLMInterpreter(enabled=VOICE_ENABLE_LLM_INTERPRETER)
            if VOICE_ENABLE_LLM_INTERPRETER
            else None
        )

    def get_match_state(self) -> Dict[str, Any]:
        """
        Return the current match state as a serializable dict.

        Returns:
            Dict with score_a, score_b, player_a, player_b, etc.
        """
        if self.match_manager is None:
            raise VoiceServiceError("No active match")
        state = self.match_manager.state
        return {
            "score_a": state.score_a,
            "score_b": state.score_b,
            "player_a": state.player_a,
            "player_b": state.player_b,
            "player_a_id": state.player_a_id,
            "player_b_id": state.player_b_id,
            "current_set": state.current_set,
            "sets_a": state.sets_a,
            "sets_b": state.sets_b,
            "history_count": len(state.match_history),
        }

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio bytes to text using local ASR.

        Args:
            audio_bytes: PCM audio bytes (mono, 16kHz, int16).

        Returns:
            Transcribed text string, or empty string if transcription fails.
        """
        return self.asr.transcribe_chunk(audio_bytes)

    def process_transcript(self, transcript: str) -> Tuple[str, VoiceScoreEvent]:
        """
        Process a transcript through the full voice pipeline.

        Steps:
        1. Post-process transcript with vocabulary corrections.
        2. Parse with deterministic parser.
        3. If unknown/ambiguous and LLM enabled, try LLM fallback.
        4. Attach speaker label if enabled.
        5. Validate through MatchManager.

        Args:
            transcript: Raw ASR transcript text.

        Returns:
            Tuple of (processed_transcript, VoiceScoreEvent).
            The event may have type="unknown" if parsing failed.
        """
        if not transcript or not transcript.strip():
            raise VoiceServiceError("Empty transcript")

        # Phase 6: Post-process transcript
        processed = self.post_processor.process(transcript)

        # Get current scores for deuce validation
        if self.match_manager is None:
            raise VoiceServiceError("No active match")
        score_a = self.match_manager.state.score_a
        score_b = self.match_manager.state.score_b

        # Parse with deterministic parser
        event = self.parser.parse(processed, current_score_a=score_a, current_score_b=score_b)

        # Phase 7: LLM fallback for unknown/ambiguous
        if event.type == "unknown" and self.llm_interpreter is not None:
            try:
                grounded = self._ground_llm_proposal(processed, score_a, score_b)
                if grounded is not None:
                    event = grounded.to_score_event()
            except LLMInterpreterError as e:
                logger.warning("LLM fallback failed: %s", e)

        # Phase 2: Attach speaker label
        if self.speaker_tagger is not None and self.speaker_tagger.mode != "off":
            self.speaker_tagger.attach_label(event)

        # Phase 4: TTS confirmation
        if self.tts_adapter is not None and self.tts_adapter.should_speak(event.type, event.confidence):
            self.tts_adapter.speak(f"Score: {event.score_a} - {event.score_b}")

        return processed, event

    def _ground_llm_proposal(
        self,
        transcript: str,
        current_score_a: int,
        current_score_b: int,
    ) -> Optional[VoiceParseResult]:
        """
        Run LLM fallback and ground the proposal.

        AI grounding invariant (Phase 5):
        - LLM output is converted to a VoiceParseResult with source="llm".
        - All LLM proposals ALWAYS require confirmation (never auto-applied).
        - Hallucination guard: reject entities not present in known match context.

        Args:
            transcript: Processed transcript text.
            current_score_a: Current score for player A.
            current_score_b: Current score for player B.

        Returns:
            VoiceParseResult if the LLM proposal passes grounding, else None.
        """
        if self.llm_interpreter is None:
            return None

        try:
            llm_event = self.llm_interpreter.interpret(transcript, current_score_a, current_score_b)
        except LLMInterpreterError as e:
            logger.warning("LLM grounding: interpretation failed: %s", e)
            return None

        if llm_event.type == "unknown":
            return None

        intent = VoiceIntent.UNKNOWN
        llm_type = llm_event.type.lower()
        if llm_type in ("increment", "score_point"):
            intent = VoiceIntent.SCORE_POINT
        elif llm_type == "set_score":
            intent = VoiceIntent.SET_SCORE
        elif llm_type == "undo":
            intent = VoiceIntent.UNDO
        elif llm_type == "repeat_score":
            intent = VoiceIntent.REPEAT_SCORE
        elif llm_type == "start_match":
            intent = VoiceIntent.START_MATCH
        elif llm_type == "pause_match":
            intent = VoiceIntent.PAUSE_MATCH
        elif llm_type == "resume_match":
            intent = VoiceIntent.RESUME_MATCH
        elif llm_type == "start_next_game":
            intent = VoiceIntent.START_NEXT_GAME
        elif llm_type == "end_game":
            intent = VoiceIntent.END_GAME
        elif llm_type == "timeout_start":
            intent = VoiceIntent.TIMEOUT_START
        elif llm_type == "timeout_end":
            intent = VoiceIntent.TIMEOUT_END
        elif llm_type == "server_check":
            intent = VoiceIntent.SERVER_CHECK
        elif llm_type == "set_server":
            intent = VoiceIntent.SET_SERVER
        elif llm_type in ("confirm", "cancel"):
            intent = VoiceIntent(llm_type)
        if intent == VoiceIntent.UNKNOWN:
            return None

        slots: Dict[str, Any] = {}
        if intent == VoiceIntent.SCORE_POINT:
            slots["player"] = llm_event.player if llm_event.player in ("A", "B") else "A"
        elif intent in (VoiceIntent.SET_SCORE, VoiceIntent.START_MATCH, VoiceIntent.START_NEXT_GAME):
            slots["score_a"] = llm_event.score_a
            slots["score_b"] = llm_event.score_b
        elif intent == VoiceIntent.SET_SERVER:
            slots["player"] = llm_event.player if llm_event.player in ("A", "B") else "A"

        result = VoiceParseResult(
            intent=intent,
            slots=slots,
            confidence=max(0.0, min(1.0, float(llm_event.confidence))),
            safety_level="medium",
            requires_confirmation=True,
            raw_transcript=transcript,
            normalized_text=transcript,
            source="llm",
        )
        return result

    def apply_voice_event(self, event: VoiceScoreEvent) -> Dict[str, Any]:
        """
        Apply a voice event to the current match through MatchManager.

        This is the single funnel for all voice commands. MatchManager
        validates the event against existing scoring rules.

        Args:
            event: VoiceScoreEvent to apply.

        Returns:
            Dict with result status, previous score, new score, and any messages.
        """
        if self.match_manager is None:
            raise VoiceServiceError("No active match")

        # Check speaker requirements (Phase 2)
        if (
            self.speaker_tagger is not None
            and VOICE_SPEAKER_REQUIRE
            and event.speaker_label not in VOICE_SPEAKER_REQUIRE.split(",")
        ):
            return {
                "status": "rejected",
                "reason": "speaker_not_allowed",
                "speaker": event.speaker_label,
                "allowed_speakers": VOICE_SPEAKER_REQUIRE.split(","),
            }

        prev_score = self.match_manager.state.get_score_string()

        try:
            success, message = self.match_manager.apply_voice_event(event)
            new_score = self.match_manager.state.get_score_string()
            return {
                "status": "accepted" if success else "rejected",
                "event_type": event.type,
                "previous_score": prev_score,
                "new_score": new_score,
                "message": message,
                "history_count": len(self.match_manager.state.match_history),
            }

        except Exception as e:
            logger.error("Error applying voice event: %s", e)
            return {
                "status": "error",
                "reason": str(e),
                "previous_score": prev_score,
            }

    def create_match(self, player_a: str, player_b: str, format: str = "best_of_3") -> Dict[str, Any]:
        """
        Create a new match with the given players and format.

        Args:
            player_a: Name of player A.
            player_b: Name of player B.
            format: Match format (e.g., "best_of_3", "best_of_5").

        Returns:
            Dict with match state.
        """
        self.match_manager = MatchManager(player_a=player_a, player_b=player_b)
        return self.get_match_state()

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """
        Return audit log entries from LLM interpreter (if enabled).

        Returns:
            List of audit log dicts.
        """
        if self.llm_interpreter is None:
            return []
        return self.llm_interpreter.get_audit_log()

    def persist_event(self, payload: Dict[str, Any], db: Any = None) -> Optional[Dict[str, Any]]:
        """
        Persist a voice event to the database.

        Args:
            payload: Event data including intent, transcript, slots, confidence, etc.
            db: Optional SQLAlchemy session.

        Returns:
            Dict with persisted event id and status, or None on failure.
        """
        from tournament_platform.app.services.voice.event_log import VoiceEventRepository

        try:
            event = VoiceEventRepository.record(payload, db=db)
            return {
                "status": "persisted",
                "event_id": event.id,
                "intent": event.intent,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
        except Exception as exc:
            logger.error("Failed to persist voice event: %s", exc)
            return None

    def confirm_event(self, event_id: int, db: Any = None) -> Dict[str, Any]:
        """
        Confirm a pending voice event and apply it to the match.

        Args:
            event_id: ID of the pending event to confirm.
            db: Optional SQLAlchemy session.

        Returns:
            Dict with apply result.
        """
        from tournament_platform.app.services.voice.event_log import VoiceEventRepository

        close = False
        if db is None:
            from tournament_platform.models import SessionLocal
            db = SessionLocal()
            close = True
        try:
            event = db.query(VoiceEvent).filter(VoiceEvent.id == event_id).first()
            if not event:
                return {"status": "error", "reason": "event_not_found"}

            if event.status != "pending_confirm":
                return {"status": "error", "reason": f"event_already_{event.status}"}

            event.status = "accepted"
            db.commit()

            score_event = VoiceScoreEvent(
                type=event.intent,
                score_a=None,
                score_b=None,
                player=None,
                raw_text=event.raw_transcript,
                confidence=event.confidence,
                event_id=str(event.id),
                source=event.source or "asr",
                requires_confirmation=True,
            )
            if event.parsed_slots:
                try:
                    slots = json.loads(event.parsed_slots)
                    score_event.score_a = slots.get("score_a")
                    score_event.score_b = slots.get("score_b")
                    score_event.player = slots.get("player")
                except json.JSONDecodeError:
                    pass

            if self.match_manager is None:
                return {"status": "error", "reason": "no_active_match"}

            prev_score = self.match_manager.state.get_score_string()
            success, message = self.match_manager.apply_voice_event(score_event)
            new_score = self.match_manager.state.get_score_string()

            event.score_before = prev_score
            event.score_after = new_score
            db.commit()

            if success:
                VoiceEventRepository.mark_undone(event.id, event.id, db=db)
                return {
                    "status": "accepted",
                    "event_id": event.id,
                    "previous_score": prev_score,
                    "new_score": new_score,
                    "message": message,
                }
            event.status = "rejected"
            event.disposition = message
            db.commit()
            return {
                "status": "rejected",
                "event_id": event.id,
                "previous_score": prev_score,
                "new_score": prev_score,
                "message": message,
            }
        except Exception as exc:
            db.rollback()
            logger.error("Failed to confirm voice event %s: %s", event_id, exc)
            return {"status": "error", "reason": str(exc)}
        finally:
            if close:
                db.close()

    def record_dataset_sample(self, payload: Dict[str, Any], db: Any = None) -> Optional[Dict[str, Any]]:
        """
        Record an opt-in dataset sample for grammar evaluation.

        Args:
            payload: Sample data including transcript, parsed_intent, expected_intent, etc.
            db: Optional SQLAlchemy session.

        Returns:
            Dict with recorded sample id, or None if disabled/failed.
        """
        if not VOICE_DATASET_OPT_IN:
            return None

        from tournament_platform.app.services.voice.event_log import VoiceCommandRepository

        try:
            cmd = VoiceCommandRepository.record(payload, db=db)
            return {
                "status": "recorded",
                "sample_id": cmd.id,
                "transcript": cmd.transcript,
                "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
            }
        except Exception as exc:
            logger.error("Failed to record dataset sample: %s", exc)
            return None
