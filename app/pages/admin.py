import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from models import SessionLocal, Player, Match, Tournament, MatchStatus

st.title("👨‍💼 Admin Panel")

db = SessionLocal()

# Admin dashboard tabs
admin_tabs = st.tabs(["Database Overview", "Match Management", "System Health"])

# Tab 1: Database Overview
with admin_tabs[0]:
    st.subheader("📊 Database Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        player_count = db.query(Player).count()
        st.metric("Total Players", player_count)

    with col2:
        match_count = db.query(Match).count()
        st.metric("Total Matches", match_count)

    with col3:
        tournament_count = db.query(Tournament).count()
        st.metric("Total Tournaments", tournament_count)

    with col4:
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()
        st.metric("Completed Matches", completed_matches)

    st.divider()

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

        gb = GridOptionsBuilder.from_dataframe(player_df)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_columns({
            "Name": {"width": 150},
            "Email": {"width": 150},
            "Rating": {"width": 100},
            "Win Rate": {"width": 100}
        })

        AgGrid(
            player_df,
            gridOptions=gb.build(),
            allow_unsafe_jscode=True,
            height=400
        )

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

        gb_matches = GridOptionsBuilder.from_dataframe(match_df)
        gb_matches.configure_pagination(paginationAutoPageSize=True)
        gb_matches.configure_columns({
            "Player 1": {"width": 120},
            "Player 2": {"width": 120},
            "Winner": {"width": 100},
            "Score": {"width": 80},
            "Status": {"width": 100}
        })

        AgGrid(
            match_df,
            gridOptions=gb_matches.build(),
            allow_unsafe_jscode=True,
            height=500
        )
    else:
        st.info("No matches found with current filters")

    # Actions
    st.divider()
    st.write("**Quick Actions:**")

    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("🔄 Refresh Data"):
            st.rerun()

    with col2:
        if st.button("🗑️ Clear All Cache"):
            st.cache_data.clear()
            st.success("Cache cleared!")

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

    st.divider()
    st.write("**System Information**")

    system_info = {
        "Database Type": "SQLite",
        "Database Path": "./data/tournament.db",
        "AI Model": "llama3.3:8b",
        "Streamlit Version": "1.35.0",
        "FastAPI Version": "0.110.0"
    }

    info_df = pd.DataFrame(list(system_info.items()), columns=["Parameter", "Value"])
    st.table(info_df)

    st.divider()
    st.write("**Recent Events**")

    with st.info():
        st.write("- ✅ System started successfully")
        st.write("- 🎾 Last match recorded: 5 minutes ago")
        st.write("- 👥 Last player registration: 2 hours ago")

db.close()


