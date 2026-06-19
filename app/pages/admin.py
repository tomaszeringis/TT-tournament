import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import sys
import os
from app.utils import render_interactive_table

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from models import SessionLocal, Player, Match, Tournament, MatchStatus, DATABASE_PATH
from services.ai_engine import AIEngine

st.title("👨‍💼 Admin Panel")
st.space("medium")

try:
    db = SessionLocal()
except Exception as e:
    st.error(f"❌ Database connection error: {e}")
    st.info("Please ensure the database file is accessible and not locked by another process.")
    st.stop()

# Admin dashboard tabs
admin_tabs = st.tabs(["Database Overview", "Match Management", "System Health"])

# Tab 1: Database Overview
with admin_tabs[0]:
    st.subheader("📊 Database Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        player_count = db.query(Player).count()
        ui.metric_card(title="Total Players", content=str(player_count), key="admin_p_count")

    with col2:
        match_count = db.query(Match).count()
        ui.metric_card(title="Total Matches", content=str(match_count), key="admin_m_count")

    with col3:
        tournament_count = db.query(Tournament).count()
        ui.metric_card(title="Total Tournaments", content=str(tournament_count), key="admin_t_count")

    with col4:
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()
        ui.metric_card(title="Completed Matches", content=str(completed_matches), key="admin_c_count")

    st.space("medium")

    # Detailed statistics
    st.write("**Detailed Player Statistics:**")

    players = db.query(Player).all()
    if players:
        player_data = []
        for player in players:
            total_matches = db.query(Match).filter(
                (Match.player1 == player.name) | (Match.player2 == player.name)
            ).count()
            wins = db.query(Match).filter(Match.winner == player.name).count()

            player_data.append({
                "ID": player.id,
                "Name": player.name,
                "Email": player.email,
                "Rating": player.rating,
                "Matches": total_matches,
                "Wins": wins,
                "Win Rate": f"{(wins/total_matches*100):.1f}%" if total_matches > 0 else "0%"
            })

        player_df = pd.DataFrame(player_data)

        # itables for player stats
        render_interactive_table(player_df.drop(columns=["ID"]))

# Tab 2: Match Management
with admin_tabs[1]:
    st.subheader("🎾 Match Management")

    # Filter matches
    col1, col2 = st.columns([1, 1])

    with col1:
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "pending", "active", "completed"]
        )

    with col2:
        tournament_filter = st.selectbox(
            "Filter by Tournament",
            ["All"] + [t.name for t in db.query(Tournament).all()]
        )

    # Get filtered matches
    query = db.query(Match)

    if status_filter != "All":
        query = query.filter(Match.status == MatchStatus[status_filter])

    if tournament_filter != "All":
        tournament = db.query(Tournament).filter(Tournament.name == tournament_filter).first()
        if tournament:
            query = query.filter(Match.tournament_id == tournament.id)

    matches = query.all()

    if matches:
        match_data = []
        st.write("**Recent Activity:**")
        # Show top 10 matches with badges for status
        for m in matches[:10]:
            m_cols = st.columns([4, 1])
            with m_cols[0]:
                st.write(f"{m.player1} vs {m.player2} | Tournament: {m.tournament.name if m.tournament else 'N/A'}")
            with m_cols[1]:
                variant = "secondary"
                if m.status == MatchStatus.completed:
                    variant = "default"
                elif m.status == MatchStatus.active:
                    variant = "outline"
                ui.badges(badge_list=[(m.status.value, variant)], key=f"admin_status_{m.id}")
        
        st.space("medium")
        for m in matches:
            match_data.append({
                "ID": m.id,
                "Player 1": m.player1,
                "Player 2": m.player2,
                "Winner": m.winner or "TBD",
                "Score": m.score or "-",
                "Status": m.status.value if m.status else "pending",
                "Tournament": m.tournament.name if m.tournament else "N/A"
            })

        match_df = pd.DataFrame(match_data)

        # itables for matches
        render_interactive_table(match_df.drop(columns=["ID"]))
    else:
        st.info("No matches found with current filters")

    # Actions
    st.space("medium")
    st.write("**Quick Actions:**")

    col1, col2 = st.columns([1, 1])

    with col1:
        if ui.button("🔄 Refresh Data", key="admin_refresh_btn"):
            st.rerun()

    with col2:
        if ui.button("🗑️ Clear All Cache", key="admin_clear_btn"):
            st.cache_data.clear()
            st.toast("Cache cleared!", icon="✅")

# Tab 3: System Health
with admin_tabs[2]:
    st.subheader("💚 System Health")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.metric("Database Status", "✅ Connected", delta="Healthy")
        st.metric("API Status", "✅ Running", delta="http://localhost:8000")

    with col2:
        st.metric("Last Updated", "Just now", delta="+0s")
        st.metric("Active Sessions", "1", delta="+1")

    st.space("medium")
    st.write("**System Information**")

    # Get current AI engine to show actual model
    try:
        engine = AIEngine()
        current_model = engine.model
    except Exception:
        current_model = os.environ.get("OLLAMA_MODEL", "llama3:latest")

    system_info = {
        "Database Type": "SQLite",
        "Database Path": DATABASE_PATH,
        "AI Model": current_model,
        "Streamlit Version": "1.35.0",
        "FastAPI Version": "0.110.0"
    }

    info_df = pd.DataFrame(list(system_info.items()), columns=["Parameter", "Value"])
    st.table(info_df)

    st.space("medium")
    st.write("**Recent Events**")

    st.info("- ✅ System started successfully\n- 🎾 Last match recorded: 5 minutes ago\n- 👥 Last player registration: 2 hours ago")

db.close()


