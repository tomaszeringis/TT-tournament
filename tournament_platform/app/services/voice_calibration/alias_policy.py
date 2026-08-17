"""
Voice Calibration — Alias policy service.

Import-safe: no Streamlit, WebRTC, ASR, session state, or scoring imports.
"""

from __future__ import annotations

from typing import Sequence

from tournament_platform.app.services.voice.commands import VoiceCommandGrammar
from tournament_platform.app.services.voice_calibration.models import (
    CalibrationAliasCandidate,
    Collision,
    ValidationResult,
)


class CalibrationAliasPolicy:
    """Stateless service that evaluates alias candidate safety.

    Enforces collision detection, length limits, and explicit confirmation
    requirements without embedding mutable policy into CalibrationSession.
    """

    _MAX_ALIAS_WORDS = 10

    def __init__(self, grammar: VoiceCommandGrammar | None = None) -> None:
        self._grammar = grammar or VoiceCommandGrammar()

    def validate_candidate(self, candidate: CalibrationAliasCandidate) -> ValidationResult:
        """Return whether a candidate alias is acceptable.

        Rejects:
        - empty transcripts
        - transcripts longer than _MAX_ALIAS_WORDS
        - transcripts that resolve to a different command than claimed
        - transcripts that resolve to unknown commands
        - candidates already marked confirmed (require manual review)
        """
        transcript = candidate.transcript.strip()
        if not transcript:
            return ValidationResult(valid=False, reason="empty transcript")

        words = transcript.split()
        if len(words) > self._MAX_ALIAS_WORDS:
            return ValidationResult(valid=False, reason="alias too long")

        if candidate.confirmed:
            return ValidationResult(valid=False, reason="confirmed alias requires manual review")

        parse_result = self._grammar.parse(transcript)
        resolved_id = self._resolve_command_id(parse_result)

        if resolved_id == "unknown":
            return ValidationResult(valid=False, reason="transcript resolves to unknown command")

        if resolved_id != candidate.command_id:
            return ValidationResult(
                valid=False,
                reason=f"transcript resolves to {resolved_id}, not {candidate.command_id}",
            )

        return ValidationResult(valid=True, reason=None)

    def detect_collisions(
        self, candidates: Sequence[CalibrationAliasCandidate]
    ) -> list[Collision]:
        """Find transcripts that map to multiple distinct command IDs.

        Candidates are grouped by (transcript, language). If a transcript
        within a language group resolves to more than one command_id, it
        is a collision.
        """
        groups: dict[tuple[str, str], list[str]] = {}
        for candidate in candidates:
            key = (candidate.transcript.strip().lower(), candidate.language)
            groups.setdefault(key, []).append(candidate.command_id)

        collisions: list[Collision] = []
        for (transcript, _), command_ids in groups.items():
            unique_ids = list(dict.fromkeys(command_ids))
            if len(unique_ids) > 1:
                collisions.append(Collision(transcript=transcript, conflicting_ids=tuple(unique_ids)))

        return collisions

    @staticmethod
    def _resolve_command_id(parse_result) -> str:
        intent = parse_result.intent
        if hasattr(intent, "value"):
            return intent.value
        return str(intent)
