"""
Match Summary Service (Phase 4)

Generates factually consistent match summaries from verified event logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from tournament_platform.services.settings import VOICE_ENABLE_LLM_INTERPRETER
from tournament_platform.app.services.voice.event_log import VoiceEventRepository

logger = logging.getLogger(__name__)


@dataclass
class MatchSummary:
    players: List[str]
    tournament: str
    final_score: str
    game_scores: List[str]
    winner: str
    duration_seconds: Optional[float] = None
    milestones: List[str] = None
    voice_command_count: int = 0
    llm_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "players": self.players,
            "tournament": self.tournament,
            "final_score": self.final_score,
            "game_scores": self.game_scores,
            "winner": self.winner,
            "duration_seconds": self.duration_seconds,
            "milestones": self.milestones or [],
            "voice_command_count": self.voice_command_count,
            "llm_text": self.llm_text,
        }


class SummaryValidator:
    @staticmethod
    def validate(facts: Dict[str, Any], events: List[Any]) -> bool:
        score_before = None
        score_after = None
        for event in events:
            if event.status == "accepted":
                if event.score_before and score_before is None:
                    score_before = event.score_before
                if event.score_after:
                    score_after = event.score_after
        if score_after and facts.get("final_score") and facts["final_score"] not in str(score_after):
            return False
        return True


class MatchSummaryService:
    def generate_match_summary(
        self,
        match_id: int,
        match_metadata: Optional[Dict[str, Any]] = None,
    ) -> MatchSummary:
        events = VoiceEventRepository.get_by_match(match_id, limit=500)
        accepted = [e for e in events if e.status == "accepted"]

        metadata = match_metadata or {}
        players = metadata.get("players", ["Player A", "Player B"])
        tournament = metadata.get("tournament", "Unknown Tournament")

        score_events = [e for e in accepted if e.intent in ("set_score", "score_point", "increment")]
        final_score = self._derive_final_score(score_events, metadata)
        game_scores = metadata.get("game_scores", [])
        winner = metadata.get("winner", players[0] if players else "Unknown")
        milestones = self._extract_milestones(score_events)

        summary = MatchSummary(
            players=players,
            tournament=tournament,
            final_score=final_score,
            game_scores=game_scores,
            winner=winner,
            voice_command_count=len(accepted),
            milestones=milestones,
        )

        facts = summary.to_dict()
        if not SummaryValidator.validate(facts, accepted):
            logger.warning("Summary validation failed for match %s", match_id)

        if VOICE_ENABLE_LLM_INTERPRETER:
            summary.llm_text = self._llm_summary(summary)

        return summary

    def _derive_final_score(self, score_events: List[Any], metadata: Dict[str, Any]) -> str:
        if metadata.get("score"):
            return metadata["score"]
        if score_events:
            last = score_events[0]
            if last.score_after:
                return last.score_after
            if last.score_before:
                return last.score_before
        return "0-0"

    def _extract_milestones(self, score_events: List[Any]) -> List[str]:
        milestones = []
        for event in score_events:
            if event.score_after and "," not in event.score_after:
                try:
                    parts = event.score_after.split("-")
                    if len(parts) == 2:
                        a, b = int(parts[0]), int(parts[1])
                        if a >= 10 and b >= 10 and abs(a - b) <= 1:
                            milestones.append("Deuce")
                        elif a == 0 and b >= 10:
                            milestones.append("Game point for Player B")
                        elif b == 0 and a >= 10:
                            milestones.append("Game point for Player A")
                except (ValueError, IndexError):
                    pass
        return milestones

    def _llm_summary(self, summary: MatchSummary) -> Optional[str]:
        facts = summary.to_dict()
        text = (
            f"{facts['players'][0]} vs {facts['players'][1]} in the {facts['tournament']}. "
            f"Final score: {facts['final_score']}. "
            f"Winner: {facts['winner']}."
        )
        return text
