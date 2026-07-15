from typing import Any, Dict, List, Optional

from tournament_platform.app.services.match_analytics.analyzer import build_match_insight
from tournament_platform.app.services.match_analytics.commentary_reader import read_key_events
from tournament_platform.app.services.match_analytics.formatter import format_match_insight, render_match_analytics_sections
from tournament_platform.app.services.match_analytics.match_options import (
    MatchAnalyticsOption,
    build_synthetic_engine_from_match,
    format_match_option_label,
    load_completed_match_options,
    parse_game_scores,
)
from tournament_platform.app.services.match_analytics.models import MatchInsight
from tournament_platform.app.services.match_analytics.ai_summary import generate_ai_summary


class MatchAnalyticsService:
    def __init__(
        self,
        player_a_name: str = "Player A",
        player_b_name: str = "Player B",
    ):
        self.player_a_name = player_a_name
        self.player_b_name = player_b_name

    def analyze(self, engine: Any, match_id: Optional[int] = None) -> MatchInsight:
        key_events: List[Any] = []
        if match_id is not None:
            key_events = read_key_events(
                match_id=match_id,
                player_a_name=self.player_a_name,
                player_b_name=self.player_b_name,
            )
        return build_match_insight(
            engine=engine,
            player_a_name=self.player_a_name,
            player_b_name=self.player_b_name,
            key_events=key_events,
        )

    def analyze_db_match(self, match: Any, match_id: Optional[int] = None) -> MatchInsight:
        engine = build_synthetic_engine_from_match(match)
        return self.analyze(engine, match_id=match_id)

    def format(self, insight: MatchInsight) -> Dict[str, Any]:
        return format_match_insight(insight, self.player_a_name, self.player_b_name)

    def render_sections(self, formatted: Dict[str, Any]) -> List[str]:
        return render_match_analytics_sections(formatted)

    def generate_ai_summary(self, insight: MatchInsight, match_id: int, engine: Any) -> str:
        if not hasattr(insight, "game_insights") and not hasattr(insight, "momentum"):
            return ""
        return generate_ai_summary(
            insight=insight,
            match_id=match_id,
            engine=engine,
            player_a_name=self.player_a_name,
            player_b_name=self.player_b_name,
        )
