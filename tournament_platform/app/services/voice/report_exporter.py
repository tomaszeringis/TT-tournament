"""
Match Report Exporter (Phase 4)

Generates exportable match reports from verified event logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from tournament_platform.app.services.voice.event_log import VoiceEventRepository
from tournament_platform.app.services.voice.match_summary import MatchSummaryService

logger = logging.getLogger(__name__)


class MatchReportExporter:
    @staticmethod
    def export_match_report(
        match_id: int,
        match_metadata: Optional[Dict[str, Any]] = None,
        include_summary: bool = True,
        include_commentary: bool = False,
    ) -> str:
        summary_service = MatchSummaryService()
        summary = summary_service.generate_match_summary(match_id, match_metadata)

        lines = []
        lines.append("# Match Report")
        lines.append("")
        if match_metadata:
            if match_metadata.get("tournament"):
                lines.append(f"**Tournament:** {match_metadata['tournament']}")
            if match_metadata.get("match_name"):
                lines.append(f"**Match:** {match_metadata['match_name']}")
        lines.append(f"**Players:** {', '.join(summary.players)}")
        lines.append(f"**Final Score:** {summary.final_score}")
        if summary.game_scores:
            lines.append(f"**Game Scores:** {', '.join(summary.game_scores)}")
        lines.append(f"**Winner:** {summary.winner}")
        lines.append("")

        events = VoiceEventRepository.get_by_match(match_id, limit=500)
        accepted = [e for e in events if e.status == "accepted"]
        lines.append(f"**Voice Commands:** {len(accepted)} accepted")
        lines.append("")

        if include_summary and summary.llm_text:
            lines.append("## Summary")
            lines.append("")
            lines.append(summary.llm_text)
            lines.append("")

        if include_commentary:
            lines.append("## Commentary")
            lines.append("")
            for event in accepted[:20]:
                if event.raw_transcript:
                    lines.append(f"- {event.raw_transcript}")
            lines.append("")

        return "\n".join(lines)
