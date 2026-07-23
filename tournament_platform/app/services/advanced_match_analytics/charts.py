from typing import Any, Dict, List, Optional

from tournament_platform.app.services.advanced_match_analytics.schemas import AdvancedMatchInsight

try:
    import plotly.express as px
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _PLOTLY_AVAILABLE = False

from tournament_platform.app.services.advanced_match_analytics.formatter import format_insight


def win_probability_chart(insight: AdvancedMatchInsight, player_a_name: str = "Player A", player_b_name: str = "Player B"):
    if not _PLOTLY_AVAILABLE:
        return None
    timeline = insight.win_probability_timeline
    if not timeline:
        fig = go.Figure()
        fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    x = [p.point_index for p in timeline]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[p.probability_a for p in timeline],
            mode="lines+markers",
            name=f"{player_a_name} win probability",
            line=dict(color="#0066FF"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[p.probability_b for p in timeline],
            mode="lines+markers",
            name=f"{player_b_name} win probability",
            line=dict(color="#FF6D00"),
        )
    )
    for px_idx in insight.pressure_point_indices:
        if px_idx < len(x):
            fig.add_vline(
                x=x[px_idx],
                line_dash="dot",
                line_color="red",
                opacity=0.4,
                annotation_text="Pressure",
                annotation_position="top",
            )
    fig.update_layout(
        title="Win Probability Timeline",
        xaxis_title="Point",
        yaxis_title="Probability",
        yaxis=dict(range=[0, 1]),
        hovermode="x unified",
        template="plotly_white",
    )
    return fig


def domination_chart(insight: AdvancedMatchInsight, player_a_name: str = "Player A", player_b_name: str = "Player B"):
    if not _PLOTLY_AVAILABLE:
        return None
    timeline = insight.domination_timeline
    if not timeline:
        fig = go.Figure()
        fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    x = [p.point_index for p in timeline]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[p.score_domination for p in timeline],
            mode="lines",
            name="Score domination",
            line=dict(color="#1f77b4", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[p.momentum_domination for p in timeline],
            mode="lines",
            name="Momentum domination",
            line=dict(color="#ff7f0e", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[p.pressure_domination for p in timeline],
            mode="lines",
            name="Pressure domination",
            line=dict(color="#2ca02c", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[p.global_domination for p in timeline],
            mode="lines",
            name="Global domination",
            line=dict(color="#d62728", width=3),
        )
    )
    for px_idx in insight.pressure_point_indices:
        if px_idx < len(x):
            fig.add_vline(
                x=x[px_idx],
                line_dash="dot",
                line_color="red",
                opacity=0.4,
            )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Domination Index Timeline",
        xaxis_title="Point",
        yaxis_title="Domination",
        yaxis=dict(range=[-1, 1]),
        hovermode="x unified",
        template="plotly_white",
    )
    return fig


def momentum_chart(insight: AdvancedMatchInsight, player_a_name: str = "Player A", player_b_name: str = "Player B"):
    if not _PLOTLY_AVAILABLE:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[player_a_name, player_b_name],
            y=[
                insight.momentum_summary.get("max_streak_a", 0),
                insight.momentum_summary.get("max_streak_b", 0),
            ],
            name="Max Streak",
            marker_color=["#0066FF", "#FF6D00"],
        )
    )
    fig.update_layout(
        title="Max Scoring Streaks",
        yaxis_title="Points",
        template="plotly_white",
    )
    return fig
