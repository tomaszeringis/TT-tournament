import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import asyncio
import os
from datetime import datetime

from tournament_platform.services.speech_service import record_audio, SpeechReporter
from tournament_platform.services.ai_engine import AIEngine, validate_and_map_to_match
from tournament_platform.services.tournament_engine import TournamentFactory, TournamentContext, KnockoutStrategy, RoundRobinStrategy
from tournament_platform.services.bracket_manager import TournamentState
from tournament_platform.app.components.interactive_bracket import interactive_bracket
from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus, TournamentType
from tournament_platform.app.utils import render_database_connection_error, render_status_badge, format_match_label, api_request
from tournament_platform.app.components.player_registration import render_player_registration_section, get_all_players
from tournament_platform.app.components.ai_status import render_ai_status_badge
from tournament_platform.config import settings
from tournament_platform.services.settings import (
    ENABLE_VOICE_ENTRY,
    ENABLE_RULES_ASSISTANT,
    SPEECH_MODEL_SIZE,
)


@st.cache_resource
def get_speech_reporter():
    return SpeechReporter(model_size=SPEECH_MODEL_SIZE)


@st.cache_resource
def get_ai_engine():
    return AIEngine()


def render_tournament_creation():
    """
    Render the tournament creation form in the sidebar.
    Uses st.form to prevent unnecessary reruns on widget changes.
    """
    st.subheader("📝 Create New Tournament")
    
    with st.form("tournament_creation_form", clear_on_submit=True):
        tournament_name = st.text_input(
            "Tournament Name",
            help="Enter a unique name for your tournament"
        )
        tournament_desc = st.text_area(
            "Description",
            help="Optional description of the tournament format or rules"
        )
        
        # Format selection using radio buttons
        format_selection = st.radio(
            "Tournament Format",
            options=["Single Elimination", "Round Robin"],
            help="Choose the competition structure"
        )
        
        # Dynamic configuration options
        if format_selection == "Single Elimination":
            seed_players = st.checkbox(
                "Seed Players (by rating)",
                value=True,
                key="seed_players"
            )
        else:
            best_of = st.number_input(
                "Best of X (Match length)",
                min_value=1,
                max_value=7,
                value=3,
                key="best_of",
                help="Number of games needed to win a match"
            )
        
        # Player selection for initial generation
        db = SessionLocal()
        all_players = db.query(Player).all()
        player_names = [p.name for p in all_players]
        selected_players = st.multiselect(
            "Select Participants",
            options=player_names,
            default=player_names[:8] if len(player_names) >= 8 else player_names,
            help="Choose at least 2 players to create a tournament"
        )
        
        submitted = st.form_submit_button("🏆 Create Tournament")
        
        if submitted:
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
                    db.flush()  # Get the new ID
                    
                    # Generate matches immediately using the Strategy Context
                    context.run_generation(selected_players, new_tournament.id, db)
                    
                    db.commit()
                    st.toast(f"✅ Tournament '{tournament_name}' created with matches!", icon="🏆")
                    st.rerun()
                except Exception as e:
                    db.rollback()
                    st.error(f"Error creating tournament: {e}")
                finally:
                    db.close()


def render_ai_chat_sidebar():
    """
    Render the AI chat interface in the sidebar.
    """
    st.divider()
    st.subheader("🤖 Ask AI Assistant")
    st.caption("Get instant answers to rules and tournament questions.")
    
    ai_question = st.text_input(
        "Ask about rules or tournaments:",
        key="sidebar_ai_question",
        label_visibility="collapsed"
    )
    
    if st.button("Ask", key="sidebar_ask_btn") and ai_question:
        with st.status("Thinking...", expanded=False) as status:
            try:
                ai_engine = get_ai_engine()
                answer = ai_engine.referee_answer(ai_question)
                status.update(label="Answer ready", state="complete", expanded=False)
                st.success(f"**Answer:** {answer}")
            except Exception as e:
                status.update(label="Error occurred", state="error", expanded=False)
                st.error(f"Error: {e}")
    
    # Quick question buttons
    quick_q1 = st.button("📜 Tournament rules?", key="quick_rules")
    quick_q2 = st.button("👤 How to register?", key="quick_register")
    
    if quick_q1 or quick_q2:
        question = "Tournament rules?" if quick_q1 else "How to register a player?"
        with st.status("Thinking...", expanded=False) as status:
            try:
                ai_engine = get_ai_engine()
                answer = ai_engine.referee_answer(question)
                status.update(label="Answer ready", state="complete", expanded=False)
                st.info(f"**{question}**\n\n{answer}")
            except Exception as e:
                status.update(label="Error occurred", state="error", expanded=False)
                st.error(f"Error: {e}")


def render_ai_match_reporting():
    """
    Render the AI-powered match reporting section.
    Preserves session state for parsed results across reruns.
    """
    st.subheader("🎤 Report Match Result (AI-Powered)")
    st.caption("AI will parse your match result. Please review and confirm before submitting to the database.")
    
    # Initialize session state for AI match reporting flow
    if 'ai_match_transcript' not in st.session_state:
        st.session_state['ai_match_transcript'] = None
    if 'ai_match_parsed' not in st.session_state:
        st.session_state['ai_match_parsed'] = None
    if 'ai_match_error' not in st.session_state:
        st.session_state['ai_match_error'] = None
    
    # Step 1: Input - Record or type match result
    st.markdown("**Step 1: Provide Match Result**")
    col_input, col_text = st.columns([1, 2])
    
    with col_input:
        if ui.button("🎙️ Record Match Result", key="record_match_btn"):
            st.session_state.ai_match_transcript = None
            st.session_state.ai_match_parsed = None
            st.session_state.ai_match_error = None
            
            with st.status("Recording...", expanded=True) as status:
                try:
                    # Use asyncio.run to call the async record_audio
                    audio_path = asyncio.run(record_audio())
                    status.update(label="Recording complete", state="complete", expanded=False)
                    
                    with st.status("Transcribing...", expanded=True) as trans_status:
                        reporter = get_speech_reporter()
                        transcript = reporter.transcribe_audio(audio_path)
                        st.session_state.ai_match_transcript = transcript
                        trans_status.update(label="Transcription complete", state="complete", expanded=False)
                    
                    with st.status("Parsing with AI...", expanded=True) as parse_status:
                        ai_engine = get_ai_engine()
                        parsed_result_pydantic = ai_engine.parse_match_result(transcript)
                        st.session_state.ai_match_parsed = parsed_result_pydantic
                        parse_status.update(label="Parsing complete", state="complete", expanded=False)
                    
                    # Cleanup temp file
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                        
                except Exception as e:
                    st.session_state.ai_match_error = f"Error during audio processing: {e}"
                    status.update(label="Error occurred", state="error", expanded=True)
    
    with col_text:
        # Manual text input fallback
        text_input = st.text_area(
            "Or type match result (e.g., 'Alice beat Bob 3-1')",
            value=st.session_state.ai_match_transcript or "",
            key="manual_match_text",
            height=100,
            help="Type a match result in natural language"
        )
        
        if st.button("🔍 Parse Text", key="parse_text_btn") and text_input:
            st.session_state.ai_match_transcript = text_input
            st.session_state.ai_match_parsed = None
            st.session_state.ai_match_error = None
            
            with st.status("Parsing with AI...", expanded=True) as status:
                try:
                    ai_engine = get_ai_engine()
                    parsed_result_pydantic = ai_engine.parse_match_result(text_input)
                    st.session_state.ai_match_parsed = parsed_result_pydantic
                    status.update(label="Parsing complete", state="complete", expanded=False)
                except Exception as e:
                    st.session_state.ai_match_error = f"Error parsing match result: {e}"
                    status.update(label="Error occurred", state="error", expanded=True)
    
    # Step 2: Review - Show parsed result for human confirmation
    if st.session_state.ai_match_parsed:
        st.divider()
        st.markdown("**Step 2: Review AI-Parsed Result**")
        st.caption("Please verify the AI correctly understood the match. Edit if needed before submitting.")
        
        parsed = st.session_state.ai_match_parsed
        
        # Check for validation issues
        if not parsed.player_a or not parsed.player_b:
            st.warning("⚠️ AI could not identify both players. Please check the transcript and edit below.")
        
        # Review card with all parsed data
        with st.container(border=True):
            st.markdown(f"**Player A:** {parsed.player_a or 'Not detected'}")
            st.markdown(f"**Player B:** {parsed.player_b or 'Not detected'}")
            st.markdown(f"**Score:** {parsed.player_a_score} - {parsed.player_b_score}")
            st.markdown(f"**Winner:** {parsed.winner or 'Not detected'}")
        
        # Step 3: Edit and Submit
        st.markdown("**Step 3: Confirm or Edit**")
        st.caption("Review the match details and click Submit to save to the database.")
        
        with st.form("ai_match_form"):
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                p1 = st.text_input("Player A", value=parsed.player_a or "")
            with col_p2:
                p2 = st.text_input("Player B", value=parsed.player_b or "")
            
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                s1 = st.number_input("Player A Score", min_value=0, max_value=10, value=parsed.player_a_score or 0, key="ai_score_a")
            with col_s2:
                s2 = st.number_input("Player B Score", min_value=0, max_value=10, value=parsed.player_b_score or 0, key="ai_score_b")
            
            # Validate winner
            winner_options = ["Select winner", p1, p2] if p1 and p2 else ["Select Players First"]
            winner_index = 0
            if parsed.winner in winner_options:
                winner_index = winner_options.index(parsed.winner)
            
            winner = st.selectbox("Winner", winner_options, index=winner_index)
            score = f"{s1}-{s2}"
            
            # Tournament selection
            db = SessionLocal()
            tournaments = db.query(Tournament).all()
            tournament_options = {t.name: t.id for t in tournaments}
            selected_tournament = st.selectbox(
                "Tournament (optional)",
                options=["None"] + list(tournament_options.keys())
            )
            
            # Validation warning
            if p1 and p2 and winner != "Select winner":
                if winner != p1 and winner != p2:
                    st.warning("⚠️ Winner must be one of the players")
            
            submitted = st.form_submit_button("📤 Submit Result")
            
            if submitted:
                # Validate all required fields
                if not p1 or not p2:
                    st.error("Please provide both player names")
                elif winner == "Select winner":
                    st.error("Please select a winner")
                elif winner != p1 and winner != p2:
                    st.error("Winner must be one of the players")
                else:
                    try:
                        payload = {
                            "player1": p1,
                            "player2": p2,
                            "score": score,
                            "winner": winner,
                            "tournament_id": tournament_options.get(selected_tournament) if selected_tournament != "None" else None
                        }
                        
                        with st.status("Submitting result...", expanded=False) as status:
                            response = api_request(
                                "post",
                                "/api/report",
                                json=payload,
                                error_context="match result submission"
                            )
                            
                            if response is not None:
                                st.session_state.ai_match_transcript = None
                                st.session_state.ai_match_parsed = None
                                st.session_state.ai_match_error = None
                                if 'parsed_result' in st.session_state:
                                    del st.session_state['parsed_result']
                                status.update(label="Result submitted!", state="complete", expanded=False)
                                st.success("✅ Match result submitted successfully!")
                                st.rerun()
                    except Exception as e:
                        st.error(f"Connection error: {e}")
                    finally:
                        db.close()
    
    # Show error if any
    if st.session_state.ai_match_error:
        st.error(st.session_state.ai_match_error)
    
    # Clear button
    if st.session_state.ai_match_parsed or st.session_state.ai_match_error:
        if st.button("🔄 Start Over", key="clear_ai_match"):
            st.session_state.ai_match_transcript = None
            st.session_state.ai_match_parsed = None
            st.session_state.ai_match_error = None
            st.rerun()


def render_bracket(tournament, all_players):
    """
    Render the interactive bracket visualization for a tournament.
    
    Args:
        tournament: The Tournament object to render
        all_players: List of all Player objects
    """
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
        if p1:
            match_entry["opponent1"]["id"] = p1.id
        if p2:
            match_entry["opponent2"]["id"] = p2.id
        if m.status == MatchStatus.completed:
            try:
                s1, s2 = map(int, m.score.split('-'))
                match_entry["opponent1"]["score"] = s1
                match_entry["opponent2"]["score"] = s2
            except:
                pass
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


def render_standings(tournament):
    """
    Render the round-robin standings for a tournament.
    
    Args:
        tournament: The Tournament object to show standings for
    """
    st.subheader("🏆 Round-Robin Standings")
    
    # Build bracket data for standings calculation
    db = SessionLocal()
    all_players = db.query(Player).all()
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
        if p1:
            match_entry["opponent1"]["id"] = p1.id
        if p2:
            match_entry["opponent2"]["id"] = p2.id
        if m.status == MatchStatus.completed:
            try:
                s1, s2 = map(int, m.score.split('-'))
                match_entry["opponent1"]["score"] = s1
                match_entry["opponent2"]["score"] = s2
            except:
                pass
        matches_data.append(match_entry)
    
    bracket_data = {
        "stages": [{"id": 0, "name": "Main Stage", "type": "single_elimination", "settings": {"size": 8}}],
        "matches": matches_data,
        "participants": [{"id": p.id, "name": p.name} for p in all_players]
    }
    
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
    
    db.close()


def render_tournament_generation(tournament):
    """
    Render the tournament generation controls for a tournament without matches.
    
    Args:
        tournament: The Tournament object to generate matches for
    """
    st.write("**Generate Tournament Bracket**")
    db = SessionLocal()
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
                finally:
                    db.close()
    else:
        st.info("Register players first to generate a bracket")


def render_active_tournaments():
    """
    Render the active tournaments tab with bracket visualization and standings.
    """
    st.subheader("Active Tournaments")
    
    db = SessionLocal()
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
                    
                    # Bracket Visualization
                    st.space("medium")
                    all_players = db.query(Player).all()
                    render_bracket(tournament, all_players)
                    
                    # Show Standings for Round-Robin
                    if tournament.tournament_type == TournamentType.round_robin:
                        st.space("medium")
                        render_standings(tournament)
                else:
                    st.write("No matches yet")
                    st.space("medium")
                    render_tournament_generation(tournament)
    else:
        st.info("No tournaments created yet. Create one using the form on the left!")
    
    db.close()


# Main page
st.title("⚙️ Tournament Setup")
st.space("medium")

# Player Registration (moved to top)
st.space("medium")
render_player_registration_section()

# Initialize AI review session state
if 'show_ai_review' not in st.session_state:
    st.session_state['show_ai_review'] = True

# Show AI status
render_ai_status_badge()

# Sidebar for creating tournaments
with st.sidebar:
    render_tournament_creation()
    render_ai_chat_sidebar()

# Main content area
tab_reporting, tab_tournaments = st.tabs(["🎾 Match Reporting", "🏆 Active Tournaments"])

with tab_reporting:
    render_ai_match_reporting()

with tab_tournaments:
    render_active_tournaments()
