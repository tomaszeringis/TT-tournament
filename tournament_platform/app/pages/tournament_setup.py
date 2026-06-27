import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import requests
import asyncio
from datetime import datetime

from tournament_platform.services.speech_service import record_audio, SpeechReporter
from tournament_platform.services.ai_engine import AIEngine, validate_and_map_to_match
from tournament_platform.services.tournament_engine import TournamentFactory, TournamentContext, KnockoutStrategy, RoundRobinStrategy
from tournament_platform.services.bracket_manager import TournamentState
from tournament_platform.app.components.interactive_bracket import interactive_bracket
from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus, TournamentType, DATABASE_URL, DATABASE_PATH
from tournament_platform.app.utils import render_database_connection_error, render_status_badge, format_match_label

@st.cache_resource
def get_speech_reporter():
    return SpeechReporter(model_size="base")

@st.cache_resource
def get_ai_engine():
    return AIEngine()

st.title("⚙️ Tournament Setup")
st.space("medium")

try:
    db = SessionLocal()
except Exception as e:
    render_database_connection_error(e)

# Sidebar for creating tournaments
with st.sidebar:
    st.subheader("📝 Create New Tournament")

    tournament_name = st.text_input("Tournament Name")
    tournament_desc = st.text_area("Description")
    
    # Format selection using radio buttons
    format_selection = st.radio(
        "Tournament Format",
        options=["Single Elimination", "Round Robin"],
        help="Choose the competition structure"
    )
    
    # Dynamic configuration options
    if format_selection == "Single Elimination":
        st.checkbox("Seed Players (by rating)", value=True, key="seed_players")
    else:
        st.number_input("Best of X (Match length)", min_value=1, max_value=7, value=3, key="best_of")

    # Player selection for initial generation
    all_players = db.query(Player).all()
    player_names = [p.name for p in all_players]
    selected_players = st.multiselect(
        "Select Participants",
        options=player_names,
        default=player_names[:8] if len(player_names) >= 8 else player_names
    )

    if ui.button("🏆 Create Tournament", key="create_tournament_btn"):
        if not tournament_name:
            st.toast("Please enter a tournament name", icon="⚠️")
        elif len(selected_players) < 2:
            st.toast("Please select at least 2 players", icon="⚠️")
        else:
            try:
                # Map UI selection to Strategy objects
                strategies = {
                    "Single Elimination": KnockoutStrategy(),
                    "Round Robin": RoundRobinStrategy()
                }
                
                selected_strategy = strategies[format_selection]
                context = TournamentContext(selected_strategy)

                is_knockout = format_selection == "Single Elimination"
                t_type = TournamentType.knockout if is_knockout else TournamentType.round_robin
                
                new_tournament = Tournament(
                    name=tournament_name,
                    description=tournament_desc,
                    tournament_type=t_type
                )
                db.add(new_tournament)
                db.flush() # Get the new ID
                
                # Generate matches immediately using the Strategy Context
                context.run_generation(selected_players, new_tournament.id, db)
                
                db.commit()
                st.toast(f"✅ Tournament '{tournament_name}' created with matches!", icon="🏆")
                st.rerun()
            except Exception as e:
                db.rollback()
                st.error(f"Error creating tournament: {e}")

# Main content area
tab_reporting, tab_tournaments = st.tabs(["🎾 Match Reporting", "🏆 Active Tournaments"])

with tab_reporting:
    st.subheader("Report Match Result")

    # Speech Recording Section
    if ui.button("🎙️ Record Match Result", key="record_match_btn"):
        with st.spinner("Recording..."):
            try:
                # Use asyncio.run to call the async record_audio
                audio_path = asyncio.run(record_audio())
                
                with st.spinner("Transcribing and parsing..."):
                    reporter = get_speech_reporter()
                    transcript = reporter.transcribe_audio(audio_path)
                    
                    ai_engine = get_ai_engine()
                    parsed_result_pydantic = ai_engine.parse_match_result(transcript)
                    
                    # Use the helper function to validate and map
                    # Since we want to display it in a form, we'll convert the mapped object back to dict 
                    # if it's a Match instance, or just use it if it's already a dict.
                    mapped_object = validate_and_map_to_match(parsed_result_pydantic.model_dump())
                    
                    if isinstance(mapped_object, Match):
                        match_data = {
                            "player1": mapped_object.player1,
                            "player2": mapped_object.player2,
                            "winner": mapped_object.winner,
                            "score": mapped_object.score
                        }
                    else:
                        match_data = mapped_object

                    # Store in session state to populate form
                    st.session_state['parsed_result'] = match_data
                    st.toast(f"Audio processed! Transcript: {transcript}", icon="🏓")
                    
                # Cleanup temp file
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception as e:
                st.error(f"Error during audio processing: {e}")

    # Initialize form values from session state if available
    initial_values = st.session_state.get('parsed_result', {})
    
    with st.form("match_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            p1 = st.text_input("Player 1", value=initial_values.get("player1", ""))
        with col_p2:
            p2 = st.text_input("Player 2", value=initial_values.get("player2", ""))
        
        winner_options = ["Select winner", p1, p2] if p1 and p2 else ["Select Players First"]
        winner_index = 0
        if initial_values.get("winner") in winner_options:
            winner_index = winner_options.index(initial_values.get("winner"))
            
        winner = st.selectbox("Winner", winner_options, index=winner_index)
        score = st.text_input("Score (e.g., 3-0)", value=initial_values.get("score", ""))

        # Get available tournaments
        tournaments = db.query(Tournament).all()
        tournament_options = {t.name: t.id for t in tournaments}
        selected_tournament = st.selectbox(
            "Tournament",
            options=["None"] + list(tournament_options.keys())
        )

        submitted = st.form_submit_button("📤 Submit Result")
        # Note: streamlit-shadcn-ui button doesn't work as a form submit button
        # so we keep st.form_submit_button for functionality but we could style it
        # or use ui.button outside the form.
        # Given the requirement "Replace my existing st.button components in the 'Match Reporting' tab",
        # I will replace the non-form buttons.

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
                        st.toast("✅ Match result submitted successfully!", icon="✅")
                        # Clear session state after successful submission
                        if 'parsed_result' in st.session_state:
                            del st.session_state['parsed_result']
                    else:
                        st.error(f"Error: {response.json()}")
                except Exception as e:
                    st.error(f"Connection error: {e}")
            else:
                st.toast("Please fill in all required fields", icon="⚠️")

with tab_tournaments:
    st.subheader("Active Tournaments")

    tournaments = db.query(Tournament).all()

    if tournaments:
        for tournament in tournaments:
            with st.expander(f"📌 {tournament.name}"):
                st.write(f"**Type:** {tournament.tournament_type.value.title()}")
                st.write(f"**Description:** {tournament.description or 'No description'}")
                st.write(f"**Created:** {tournament.created_at.strftime('%Y-%m-%d')}")

                # Show matches in tournament
                if tournament.matches:
                    st.write("**Matches:**")
                    # Sort matches by round and index for better display
                    sorted_matches = sorted(tournament.matches, key=lambda m: (m.round_number or 0, m.bracket_index or 0))
                    for match in sorted_matches:
                        cols = st.columns([4, 1])
                        with cols[0]:
                            st.write(
                                f"Round {match.round_number or '?'}: {match.player1} vs {match.player2} | "
                                f"Winner: {match.winner or 'TBD'}"
                            )
                        with cols[1]:
                            render_status_badge(match.status.value, key=f"status_{match.id}")
                else:
                    st.write("No matches yet")
                    
                    # Option to generate bracket
                    st.space("medium")
                    st.write("**Generate Tournament Bracket**")
                    all_players = db.query(Player).all()
                    player_names = [p.name for p in all_players]
                    
                    if player_names:
                        selected_players = st.multiselect(
                            f"Select players for {tournament.name}",
                            options=player_names,
                            default=player_names[:8] if len(player_names) >= 8 else player_names
                        )
                        
                        default_format = "Knockout" if tournament.tournament_type == TournamentType.knockout else "Round-Robin"
                        tournament_format = st.selectbox(
                            "Tournament Format",
                            options=["Knockout", "Round-Robin"],
                            index=0 if default_format == "Knockout" else 1,
                            key=f"format_{tournament.id}"
                        )
                        
                        if ui.button(f"🏆 Generate {tournament_format}", key=f"gen_{tournament.id}"):
                            if len(selected_players) < 2:
                                st.toast("Please select at least 2 players", icon="⚠️")
                            else:
                                try:
                                    # Use Strategy pattern via TournamentContext
                                    strategies = {
                                        "Knockout": KnockoutStrategy(),
                                        "Round-Robin": RoundRobinStrategy()
                                    }
                                    selected_strategy = strategies[tournament_format]
                                    context = TournamentContext(selected_strategy)
                                    context.run_generation(selected_players, tournament.id, db)
                                    
                                    st.toast("✅ Tournament generated successfully!", icon="🏆")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error generating tournament: {e}")
                    else:
                        st.info("Register players first to generate a bracket")

                # Bracket Visualization
                if tournament.matches:
                    st.space("medium")
                    st.subheader("📊 Interactive Bracket")
                    
                    participants = [{"id": p.id, "name": p.name} for p in all_players]
                    matches_data = []
                    for m in tournament.matches:
                        match_entry = {
                            "id": m.id,
                            "number": m.bracket_index or 0,
                            "stageId": 0,
                            "groupId": 0,
                            "roundId": (m.round_number or 1) - 1,
                            "status": 4 if m.status == MatchStatus.completed else 2,
                            "opponent1": {"id": None, "score": None},
                            "opponent2": {"id": None, "score": None}
                        }
                        p1 = next((p for p in all_players if p.name == m.player1), None)
                        p2 = next((p for p in all_players if p.name == m.player2), None)
                        if p1: match_entry["opponent1"]["id"] = p1.id
                        if p2: match_entry["opponent2"]["id"] = p2.id
                        if m.status == MatchStatus.completed:
                            try:
                                s1, s2 = map(int, m.score.split('-'))
                                match_entry["opponent1"]["score"] = s1
                                match_entry["opponent2"]["score"] = s2
                            except: pass
                        matches_data.append(match_entry)

                    bracket_data = {
                        "stages": [{"id": 0, "name": "Main Stage", "type": "single_elimination", "settings": {"size": 8}}],
                        "matches": matches_data,
                        "participants": participants
                    }
                    
                    clicked = interactive_bracket(bracket_data, key=f"bracket_{tournament.id}")
                    if clicked:
                        st.session_state['selected_match_from_bracket'] = clicked
                        st.toast(f"Match selected!")

                    # Show Standings for Round-Robin
                    if tournament.tournament_type == TournamentType.round_robin:
                        st.space("medium")
                        st.subheader("🏆 Round-Robin Standings")
                        ts = TournamentState(data=bracket_data)
                        standings = ts.calculate_standings()
                        
                        if standings:
                            standings_df = pd.DataFrame(standings)
                            # Rename columns for display
                            standings_df = standings_df.rename(columns={
                                "name": "Player",
                                "wins": "W",
                                "losses": "L",
                                "matches_played": "MP",
                                "points_for": "PF",
                                "points_against": "PA"
                            })
                            # Reorder columns and drop ID
                            standings_df = standings_df[["Player", "MP", "W", "L", "PF", "PA"]]
                            st.table(standings_df)
                        else:
                            st.info("No completed matches yet to calculate standings.")
    else:
        st.info("No tournaments created yet. Create one using the form on the left!")

# Player Registration
st.space("medium")
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
                    st.toast(f"✅ Player '{player_name}' registered!", icon="✅")
                except Exception as e:
                    st.error(f"Error registering player: {e}")
            else:
                st.toast("Please fill in all fields", icon="⚠️")

with col2_players:
    st.write("**Registered Players**")
    players = db.query(Player).all()
    if players:
        player_list = "\n".join([f"- {p.name} ({p.email}) - Rating: {p.rating}" for p in players])
        st.code(player_list)
    else:
        st.info("No players registered yet")

db.close()

