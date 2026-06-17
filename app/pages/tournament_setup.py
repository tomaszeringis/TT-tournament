import streamlit as st
import requests
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from models import SessionLocal, Player, Match, Tournament, MatchStatus

st.title("⚙️ Tournament Setup")

db = SessionLocal()

# Sidebar for creating tournaments
with st.sidebar:
    st.subheader("📝 Create New Tournament")

    with st.form("tournament_form"):
        tournament_name = st.text_input("Tournament Name")
        tournament_desc = st.text_area("Description")

        if st.form_submit_button("Create Tournament"):
            if tournament_name:
                try:
                    new_tournament = Tournament(
                        name=tournament_name,
                        description=tournament_desc
                    )
                    db.add(new_tournament)
                    db.commit()
                    st.success(f"✅ Tournament '{tournament_name}' created!")
                except Exception as e:
                    st.error(f"Error creating tournament: {e}")
            else:
                st.warning("Please enter a tournament name")

# Main content area
col1, col2 = st.columns([1, 1])

# Left column: Match Reporting
with col1:
    st.subheader("🎾 Report Match Result")

    with st.form("match_form"):
        p1 = st.text_input("Player 1")
        p2 = st.text_input("Player 2")
        winner = st.selectbox("Winner", ["Select winner", p1, p2] if p1 and p2 else ["Select Players First"])
        score = st.text_input("Score (e.g., 3-0)")

        # Get available tournaments
        tournaments = db.query(Tournament).all()
        tournament_options = {t.name: t.id for t in tournaments}
        selected_tournament = st.selectbox(
            "Tournament",
            options=["None"] + list(tournament_options.keys())
        )

        submitted = st.form_submit_button("📤 Submit Result")

        if submitted:
            if p1 and p2 and score and winner != "Select winner":
                try:
                    payload = {
                        "player1": p1,
                        "player2": p2,
                        "score": score,
                        "winner": winner if winner != "Select winner" else None,
                        "tournament_id": tournament_options.get(selected_tournament) if selected_tournament != "None" else None
                    }

                    response = requests.post("http://localhost:8000/api/report", json=payload)

                    if response.status_code == 200:
                        st.success("✅ Match result submitted successfully!")
                    else:
                        st.error(f"Error: {response.json()}")
                except Exception as e:
                    st.error(f"Connection error: {e}")
            else:
                st.warning("Please fill in all required fields")

# Right column: Active Tournaments
with col2:
    st.subheader("🏆 Active Tournaments")

    tournaments = db.query(Tournament).all()

    if tournaments:
        for tournament in tournaments:
            with st.expander(f"📌 {tournament.name}"):
                st.write(f"**Description:** {tournament.description or 'No description'}")
                st.write(f"**Created:** {tournament.created_at.strftime('%Y-%m-%d')}")

                # Show matches in tournament
                if tournament.matches:
                    st.write("**Matches:**")
                    for match in tournament.matches:
                        st.write(
                            f"- {match.player1} vs {match.player2} | "
                            f"Winner: {match.winner or 'TBD'} | "
                            f"Status: {match.status.value}"
                        )
                else:
                    st.write("No matches yet")
    else:
        st.info("No tournaments created yet. Create one using the form on the left!")

# Player Registration
st.divider()
st.subheader("👥 Player Registration")

col1_players, col2_players = st.columns([1, 1])

with col1_players:
    st.write("**Register New Player**")

    with st.form("player_form"):
        player_name = st.text_input("Player Name")
        player_email = st.text_input("Email")

        if st.form_submit_button("➕ Register Player"):
            if player_name and player_email:
                try:
                    new_player = Player(
                        name=player_name,
                        email=player_email,
                        rating=1200
                    )
                    db.add(new_player)
                    db.commit()
                    st.success(f"✅ Player '{player_name}' registered!")
                except Exception as e:
                    st.error(f"Error registering player: {e}")
            else:
                st.warning("Please fill in all fields")

with col2_players:
    st.write("**Registered Players**")
    players = db.query(Player).all()
    if players:
        player_list = "\n".join([f"- {p.name} ({p.email}) - Rating: {p.rating}" for p in players])
        st.code(player_list)
    else:
        st.info("No players registered yet")

db.close()

