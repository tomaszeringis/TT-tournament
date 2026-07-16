"""
Voice LLM-Assisted Command Interpretation (Phase 7)

Provides:
- LLMInterpreter: fallback interpreter for ambiguous/unknown voice transcripts.
- Strict output schema ensures LLM-proposed actions are validated through MatchManager.
- Local-first: uses Ollama when available; cloud optional behind config.
- Full audit log of transcript → event → validation.

Design goals:
- Deterministic parser remains primary; LLM is fallback only.
- LLM never writes state directly; all proposals validated through MatchManager.
- Additive only — never changes scoring rules or parser behavior.
- Offline-first — no network calls unless cloud provider explicitly configured.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LLMProposedEvent:
    """
    Strict schema for LLM-proposed voice events.

    The LLM must output JSON conforming to this schema. The interpreter
    validates the output and converts it to a VoiceScoreEvent only if
    it passes validation through MatchManager.
    """

    type: str = "unknown"  # "increment" | "set_score" | "undo" | "unknown"
    score_a: int = 0
    score_b: int = 0
    player: str = "A"  # "A" | "B"
    confidence: float = 0.0
    reasoning: str = ""
    requires_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "player": self.player,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "requires_confirmation": self.requires_confirmation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMProposedEvent":
        return cls(
            type=data.get("type", "unknown"),
            score_a=int(data.get("score_a", 0)),
            score_b=int(data.get("score_b", 0)),
            player=data.get("player", "A"),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
        )


class LLMInterpreterError(Exception):
    """Raised when the LLM interpreter cannot process a transcript."""
    pass


class LLMInterpreter:
    """
    Fallback interpreter for ambiguous/unknown voice transcripts.

    Uses a local LLM (Ollama) to interpret transcripts that the deterministic
    parser cannot handle. The LLM output is constrained to a strict schema
    and validated through MatchManager before any state mutation.

    Features:
    - Local-first (Ollama) with optional cloud provider.
    - Strict JSON schema enforcement.
    - Full audit logging of transcript → LLM proposal → validation result.
    - Never bypasses MatchManager validation.
    """

    def __init__(
        self,
        enabled: bool = False,
        model: Optional[str] = None,
        host: Optional[str] = None,
    ):
        """
        Initialize the LLM interpreter.

        Args:
            enabled: Whether LLM interpretation is enabled.
            model: Ollama model name. Falls back to OLLAMA_MODEL env var.
            host: Ollama host. Falls back to OLLAMA_HOST env var.
        """
        self.enabled = enabled
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3:latest")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self._client = None
        self._audit_log: List[Dict[str, Any]] = []

    def _get_client(self):
        """Lazy-load the Ollama client.

        On Streamlit Cloud (external API bridge mode) the local Ollama client is
        never used; the interpreter is effectively disabled there because Ollama
        is only reachable via the FastAPI bridge.
        """
        if self._client is not None:
            return self._client

        if not self.enabled:
            raise LLMInterpreterError("LLM interpreter is disabled")

        try:
            from tournament_platform.app.services.ai_provider import resolve_provider

            if resolve_provider() == "api_bridge":
                raise LLMInterpreterError(
                    "Local Ollama interpreter is unavailable on Streamlit Cloud; "
                    "use the FastAPI bridge instead."
                )
        except LLMInterpreterError:
            raise
        except Exception:
            pass

        try:
            import ollama
            self._client = ollama
            return self._client
        except ImportError:
            raise LLMInterpreterError(
                "ollama package not installed. Install with: pip install ollama"
            )

    def _build_prompt(self, transcript: str, current_score_a: int, current_score_b: int) -> str:
        """
        Build the system prompt for the LLM.

        The prompt enforces strict JSON output and explains the scoring rules.
        """
        return f"""You are a table tennis scorekeeping assistant. Interpret the user's voice command and output a JSON object with the following schema:

{{
  "type": "increment" | "set_score" | "undo" | "unknown",
  "score_a": <integer>,
  "score_b": <integer>,
  "player": "A" | "B",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "requires_confirmation": <boolean>
}}

Rules:
- "increment": add one point to the specified player.
- "set_score": set both scores explicitly (use only if both numbers are clearly stated).
- "undo": remove the last point.
- "unknown": if you cannot determine the intent, use this type.
- Player A is the first player/team mentioned, Player B is the second.
- Current score: A={current_score_a}, B={current_score_b}.
- If the command is ambiguous or you are unsure, set "requires_confirmation" to true and "confidence" below 0.7.
- Output ONLY valid JSON, no additional text.

User command: "{transcript}"
"""

    def interpret(
        self,
        transcript: str,
        current_score_a: int = 0,
        current_score_b: int = 0,
    ) -> LLMProposedEvent:
        """
        Interpret a transcript using the LLM.

        Args:
            transcript: Raw ASR transcript text.
            current_score_a: Current score for player A.
            current_score_b: Current score for player B.

        Returns:
            LLMProposedEvent with the interpreted command.

        Raises:
            LLMInterpreterError: If the LLM is unavailable or output is invalid.
        """
        if not self.enabled:
            raise LLMInterpreterError("LLM interpreter is disabled")

        if not transcript or not transcript.strip():
            raise LLMInterpreterError("Empty transcript")

        client = self._get_client()
        prompt = self._build_prompt(transcript, current_score_a, current_score_b)

        try:
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict JSON-only assistant for table tennis scoring."},
                    {"role": "user", "content": prompt},
                ],
                format="json",
                options={"temperature": 0.1},
            )

            raw_content = response["message"]["content"].strip()
            logger.debug("LLM raw response: %s", raw_content)

            # Parse JSON
            try:
                data = json.loads(raw_content)
            except json.JSONDecodeError as e:
                raise LLMInterpreterError(f"LLM output is not valid JSON: {e}") from e

            # Validate against strict schema
            event = LLMProposedEvent.from_dict(data)

            # Validate type
            if event.type not in ("increment", "set_score", "undo", "unknown"):
                raise LLMInterpreterError(f"Invalid event type from LLM: {event.type}")

            # Validate confidence range
            if not 0.0 <= event.confidence <= 1.0:
                event.confidence = max(0.0, min(1.0, event.confidence))

            # Log for audit
            self._audit_log.append({
                "transcript": transcript,
                "proposed_event": event.to_dict(),
                "raw_llm_output": raw_content,
            })

            return event

        except Exception as e:
            if isinstance(e, LLMInterpreterError):
                raise
            raise LLMInterpreterError(f"LLM call failed: {e}") from e

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Return the audit log of LLM interpretations."""
        return list(self._audit_log)

    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()
