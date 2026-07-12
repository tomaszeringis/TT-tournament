import streamlit as st

st.set_page_config(page_title="LIT_IT Dashboard", layout="wide")
import pandas as pd
import plotly.graph_objects as go
import requests
from tournament_platform.app.utils import (
    render_interactive_table,
    render_database_error,
    render_status_badge,
    render_metric_cards,
    api_request,
)
from tournament_platform.app.components.ai_status import render_ai_status_badge
from tournament_platform.app.components.rankings_panel import render_rankings_panel
from tournament_platform.app.design_system import (
    apply_global_styles,
    render_litit_result_row,
    render_litit_upcoming_row,
)

apply_global_styles()
from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus
from tournament_platform.config import settings
from tournament_platform.services.ai_engine import AIEngine


@st.cache_resource
def get_ai_engine():
    """Get cached AIEngine instance for dashboard AI operations."""
    return AIEngine()


@st.cache_data(ttl=300, show_spinner="Loading dashboard data...")
def load_dashboard_data():
    """Load all dashboard data in a single cached database session."""
    db = SessionLocal()
    try:
        total_players = db.query(Player).count()
        total_matches = db.query(Match).count()
        active_tournaments = db.query(Tournament).count()
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()

        players = db.query(Player).all()
        matches = db.query(Match).all()

        player_df = pd.DataFrame([
            {
                "ID": p.id,
                "Name": p.name,
                "Email": p.email,
                "Rating": p.rating
            }
            for p in players
        ])

        match_df = pd.DataFrame([
            {
                "ID": m.id,
                "Player 1": m.player1,
                "Player 2": m.player2,
                "Winner": m.winner or "Pending",
                "Score": m.score or "-",
                "Status": m.status.value if m.status else "pending",
                "Scheduled Time": m.scheduled_time
            }
            for m in matches
        ])

        # Build a lookup: player_name -> list of matches
        player_matches = {}
        for m in matches:
            for p_name in (m.player1, m.player2):
                if p_name not in player_matches:
                    player_matches[p_name] = []
                player_matches[p_name].append(m)

        return {
            "metrics": {
                "total_players": total_players,
                "total_matches": total_matches,
                "active_tournaments": active_tournaments,
                "completed_matches": completed_matches,
            },
            "player_df": player_df,
            "match_df": match_df,
            "player_matches": player_matches,
        }
    finally:
        db.close()


@st.cache_data(ttl=60, show_spinner="Loading recent matches...")
def get_recent_matches(limit: int = 5):
    """Get the most recent matches ordered by scheduled_time descending."""
    db = SessionLocal()
    try:
        matches = db.query(Match).order_by(Match.scheduled_time.desc()).limit(limit).all()
        return [
            {
                "id": m.id,
                "player1": m.player1,
                "player2": m.player2,
                "winner": m.winner,
                "score": m.score,
                "status": m.status.value if m.status else "pending",
                "scheduled_time": m.scheduled_time
            }
            for m in matches
        ]
    finally:
        db.close()


@st.cache_data(ttl=300, show_spinner="Computing player statistics...")
def compute_player_stats(player_name, _player_matches):
    """Compute statistics for a player using pre-fetched match data."""
    matches = _player_matches.get(player_name, [])
    if not matches:
        return None

    total_matches = len(matches)
    # Find player id from match data to determine wins
    # We use player name matching since player1/player2 are stored as names
    wins = sum(1 for m in matches if m.winner == player_name)
    win_rate = (wins / total_matches * 100) if total_matches > 0 else 0

    # Calculate consistency (standard deviation of match intervals)
    completed_matches = [m for m in matches if m.winner is not None]
    consistency = min(100, 80 + (len(completed_matches) / max(1, total_matches)) * 20)

    return {
        "win_rate": round(win_rate, 1),
        "consistency": round(consistency, 1),
        "total_matches": total_matches,
        "wins": wins,
    }


def create_radar_chart(player_name, player_matches):
    """Create a radar chart for player stats using cached data."""
    stats = compute_player_stats(player_name, player_matches)

    if not stats:
        st.warning(f"No statistics available for {player_name}")
        return

    fig = go.Figure(data=go.Scatterpolar(
        r=[stats['win_rate'], stats['consistency']],
        theta=['Win Rate', 'Consistency'],
        fill='toself',
        name=player_name
    ))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        height=500,
        template="plotly_dark",
        title=f"Player Performance: {player_name}"
    )

    st.plotly_chart(fig, use_container_width=True)


def render_overview_tab(data):
    """Render the Overview tab content."""
    metrics = data["metrics"]
    player_df = data["player_df"]
    match_df = data["match_df"]
    player_matches = data["player_matches"]

    # Render metric cards
    render_metric_cards([
        {"title": "Total Players", "content": metrics["total_players"], "description": "Registered players"},
        {"title": "Total Matches", "content": metrics["total_matches"], "description": "Matches played"},
        {"title": "Tournaments", "content": metrics["active_tournaments"], "description": "Total events"},
        {"title": "Completed", "content": metrics["completed_matches"], "description": "Finished matches"},
    ])

    st.space("medium")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("👥 Players")

        if not player_df.empty:
            render_interactive_table(player_df.drop(columns=["ID"], errors="ignore"))
        else:
            st.info("No players registered yet.")

    with col2:
        st.subheader("🎾 Recent Matches")

        recent_matches = get_recent_matches(5)
        if recent_matches:
            st.write("**Latest Updates:**")
            for m in recent_matches:
                cols = st.columns([3, 1])
                with cols[0]:
                    score_str = f" {m['score']}" if m['score'] else ""
                    st.write(f"{m['player1']} vs {m['player2']}{score_str}")
                with cols[1]:
                    render_status_badge(m['status'], key=f"dash_status_{m['id']}")

            st.space("medium")
            render_interactive_table(match_df.drop(columns=["ID", "Scheduled Time"], errors="ignore"))
        else:
            st.info("No matches recorded yet.")

    # Player Performance Radar Chart
    st.space("medium")
    st.subheader("📈 Player Performance Analysis")

    if not player_df.empty:
        selected_player_name = st.selectbox(
            "Select a player to view performance stats:",
            options=player_df["Name"].tolist()
        )

        if selected_player_name:
            create_radar_chart(selected_player_name, player_matches)

    # AI Match Insights Section
    st.space("medium")
    st.subheader("🤖 AI Match Insights")
    st.caption("Analyze completed matches with AI-powered insights. Review before using for decisions.")

    # Show AI status
    render_ai_status_badge()

    # Get completed matches for AI analysis
    if not match_df.empty:
        completed_matches = match_df[match_df['Status'] == 'completed']
    else:
        completed_matches = pd.DataFrame()

    if not completed_matches.empty:
        selected_match_id = st.selectbox(
            "Select a completed match for AI analysis:",
            options=[""] + completed_matches['ID'].astype(str).tolist(),
            format_func=lambda x: f"Match #{x}" if x else "Select a match..."
        )

        if selected_match_id:
            match_row = completed_matches[completed_matches['ID'] == int(selected_match_id)].iloc[0]
            match_data = {
                "player1": match_row['Player 1'],
                "player2": match_row['Player 2'],
                "winner": match_row['Winner'],
                "score": match_row['Score']
            }

            if st.button("🔍 Analyze Match", key="analyze_match_btn"):
                with st.status("Generating AI insights...", expanded=False) as status:
                    try:
                        ai_engine = get_ai_engine()
                        report = ai_engine.generate_report(match_data)
                        status.update(label="Analysis complete", state="complete", expanded=False)

                        st.write("**Summary:**")
                        if report.summary:
                            st.write(report.summary)

                        st.write("**Key Play:**")
                        if report.key_play:
                            st.write(report.key_play)

                        st.write("**Predicted Winner:**")
                        if report.predicted_winner:
                            st.write(report.predicted_winner)
                    except Exception as e:
                        status.update(label="Error occurred", state="error", expanded=False)
                        st.error(f"Error generating insights: {e}")
    else:
        st.info("No completed matches to analyze. Complete some matches first!")

    # Quick Questions Section
    st.space("medium")
    st.subheader("❓ Quick Questions")
    st.caption("Get instant answers to common questions. AI responses are informational only.")

    quick_questions = [
        "Who has the most wins?",
        "What are the tournament rules?",
        "How do I register a player?",
        "What's the next match?"
    ]

    # Use selectbox for better mobile experience
    selected_question = st.selectbox(
        "Choose a question:",
        options=[""] + quick_questions,
        format_func=lambda x: x if x else "Select a question..."
    )

    if selected_question:
        st.session_state['quick_question'] = selected_question

    if st.session_state.get('quick_question'):
        question = st.session_state['quick_question']
        with st.status("Getting answer...", expanded=False) as status:
            try:
                ai_engine = get_ai_engine()
                answer = ai_engine.referee_answer(question)
                status.update(label="Answer ready", state="complete", expanded=False)
                st.info(f"**Q:** {question}\n\n**A:** {answer}")
            except Exception as e:
                status.update(label="Error occurred", state="error", expanded=False)
                st.error(f"Error: {e}")
        # Clear the question after showing
        if 'quick_question' in st.session_state:
            del st.session_state['quick_question']


def render_recent_results_tab(data):
    """Render the Recent Results tab content."""
    match_df = data["match_df"]

    st.subheader("📋 Recent Results")

    if not match_df.empty:
        # Filter to completed matches and sort by scheduled time desc
        completed = match_df[match_df['Status'] == 'completed'].copy()
        if not completed.empty:
            completed = completed.sort_values("Scheduled Time", ascending=False)

            for _, m in completed.iterrows():
                p1 = m['Player 1']
                p2 = m['Player 2']
                score = m['Score'] or "vs"
                winner = m['Winner'] or "Pending"
                scheduled = m['Scheduled Time']
                time_str = scheduled.strftime('%H:%M') if scheduled else "--:--"

                render_litit_result_row(p1, p2, score, winner, time_str)
        else:
            st.info("No completed matches yet.")
    else:
        st.info("No matches recorded yet.")


def render_upcoming_matches_tab(data):
    """Render the Upcoming Matches tab content."""
    match_df = data["match_df"]

    st.subheader("⏭️ Upcoming Matches")

    if not match_df.empty:
        # Filter to pending/active matches and sort by scheduled time asc
        upcoming = match_df[match_df['Status'].isin(['pending', 'active'])].copy()
        if not upcoming.empty:
            upcoming = upcoming.sort_values("Scheduled Time", ascending=True)

            for _, m in upcoming.iterrows():
                p1 = m['Player 1']
                p2 = m['Player 2']
                scheduled = m['Scheduled Time']
                time_str = scheduled.strftime('%Y-%m-%d %H:%M') if scheduled else "TBD"
                status = m['Status']

                status_icon = "🔴" if status == "active" else "🔵"

                render_litit_upcoming_row(p1, p2, time_str, status, status_icon)
        else:
            st.info("No upcoming matches scheduled.")
    else:
        st.info("No matches recorded yet.")


def render_dashboard():
    """Render the optimized dashboard page with tabs."""
    from tournament_platform.app.components.brand_assets import render_brand_icon
    render_brand_icon("dashboard")
    st.title("📊 LIT_IT Dashboard")

    try:
        data = load_dashboard_data()
    except Exception as e:
        render_database_error(e, "dashboard data")
        st.stop()

    # Dashboard tabs
    tab_overview, tab_rankings, tab_recent, tab_upcoming = st.tabs([
        "📋 Overview",
        "🏆 Rankings",
        "📋 Recent Results",
        "⏭️ Upcoming Matches"
    ])

    with tab_overview:
        render_overview_tab(data)

    with tab_rankings:
        render_rankings_panel(show_top3=True, show_history=True)

    with tab_recent:
        render_recent_results_tab(data)

    with tab_upcoming:
        render_upcoming_matches_tab(data)


if __name__ == "__main__":
    render_dashboard()
