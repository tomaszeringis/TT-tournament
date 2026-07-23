from typing import Any, Dict, List

from tournament_platform.app.services.advanced_match_analytics.schemas import AdvancedMatchInsight


def format_insight(insight: AdvancedMatchInsight, player_a_name: str = "Player A", player_b_name: str = "Player B") -> Dict[str, Any]:
    return {
        "title": _title(insight, player_a_name, player_b_name),
        "summary": insight.narrative_summary,
        "domination_index": insight.global_domination,
        "domination_winner": insight.domination_winner,
        "biggest_momentum_swing": insight.biggest_momentum_swing,
        "pressure_points_won_a": insight.pressure_points_won_a,
        "total_pressure_points": insight.total_pressure_points,
        "longest_run_player": insight.longest_run_player,
        "longest_run": insight.longest_run,
        "win_probability_timeline": [
            {
                "point_index": p.point_index,
                "probability_a": p.probability_a,
                "probability_b": p.probability_b,
                "score_a": p.score_a,
                "score_b": p.score_b,
            }
            for p in insight.win_probability_timeline
        ],
        "domination_timeline": [
            {
                "point_index": p.point_index,
                "score_domination": p.score_domination,
                "momentum_domination": p.momentum_domination,
                "pressure_domination": p.pressure_domination,
                "global_domination": p.global_domination,
            }
            for p in insight.domination_timeline
        ],
        "pressure_summary": insight.pressure_summary,
        "momentum_summary": insight.momentum_summary,
        "shot_diversity_summary": insight.shot_diversity_summary,
        "key_turning_points": insight.key_turning_points,
        "warnings": insight.warnings,
    }


def _title(insight: AdvancedMatchInsight, player_a_name: str, player_b_name: str) -> str:
    if insight.global_domination > 0.3:
        return f"{player_a_name} Advanced Post-Match Analytics"
    if insight.global_domination < -0.3:
        return f"{player_b_name} Advanced Post-Match Analytics"
    return "Advanced Post-Match Analytics"
