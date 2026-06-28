import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import asyncio
import os
import requests
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
    ENABLE_RANKING_INTELLIGENCE,
    SPEECH_MODEL_SIZE,
    KEEP_AUDIO_FILES,
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
    
    # Get players data for seeding button (outside form)
    db_temp = SessionLocal()
    all_players = db_temp.query(Player).all()
    player_names = [p.name for p in all_players]
    db_temp.close()
    
    # Seeding suggestion button - OUTSIDE the form
    if ENABLE_RANKING_INTELLIGENCE:
        if st.button("🎯 Suggest Seeding by Rating", key="suggest_seeding_btn"):
            if not all_players:
                st.warning("No players with ratings available for seeding.")
            else:
                sorted_players = sorted(all_players, key=lambda p: p.rating, reverse=True)
                seeded_names = [p.name for p in sorted_players]
                # Filter to only those currently selected, preserving rating order
                current_selection = st.session_state.get("participants_multiselect", [])
                selected_sorted = [name for name in seeded_names if name in current_selection]
                st.session_state["seeded_players"] = selected_sorted
                st.rerun()
    
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
        selected_players = st.multiselect(
            "Select Participants",
            options=player_names,
            default=player_names[:8] if len(player_names) >= 8 else player_names,
            help="Choose at least 2 players to create a tournament",
            key="participants_multiselect"
        )

        # Restore seeded selection if available
        if "seeded_players" in st.session_state and st.session_state["seeded_players"]:
            st.session_state["participants_multiselect"] = st.session_state["seeded_players"]
            st.caption("🔽 Players are ordered by rating (highest first).")
        
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
                    db = SessionLocal()
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


def render_voice_or_text_parser():
    """
    Render the voice recording and text parsing input section.
    Stores parsed result in session state for confirmation.
    """
    st.markdown("**Step 1: Provide Match Result**")
    st.caption("🔒 Audio is processed locally. Temp files are deleted by default. You must confirm before submitting.")
    col_input, col_text = st.columns([1, 2])

    with col_input:
        if ENABLE_VOICE_ENTRY:
            if ui.button("🎙️ Record Match Result", key="record_match_btn"):
                st.session_state.ai_match_transcript = None
                st.session_state.ai_match_parsed = None
                st.session_state.ai_match_error = None

                with st.status("Recording...", expanded=True) as status:
                    try:
                        audio_path = asyncio.run(record_audio())
                        status.update(label="Recording complete", state="complete", expanded=False)

                        with st.status("Transcribing...", expanded=True) as trans_status:
                            reporter = get_speech_reporter()
                            transcript = reporter.transcribe_audio(audio_path)
                            st.session_state.ai_match_transcript = transcript
                            trans_status.update(label="Transcription complete", state="complete", expanded=False)

                        # Parse via safe API endpoint (no DB writes)
                        with st.status("Parsing result...", expanded=True) as parse_status:
                            response = api_request(
                                "post",
                                "/api/match/parse",
                                json={"text": transcript},
                                parse_json=True,
                                error_context="match result parsing"
                            )
                            if response is not None:
                                st.session_state.ai_match_parsed = response
                                parse_status.update(label="Parsing complete", state="complete", expanded=False)
                            else:
                                st.session_state.ai_match_error = "Failed to parse match result"
                                parse_status.update(label="Parse failed", state="error", expanded=True)

                        # Cleanup temp file unless configured to keep
                        if not KEEP_AUDIO_FILES and os.path.exists(audio_path):
                            os.remove(audio_path)

                    except Exception as e:
                        st.session_state.ai_match_error = f"Error during audio processing: {e}"
                        status.update(label="Error occurred", state="error", expanded=True)
        else:
            st.caption("Voice entry is disabled in settings.")

    with col_text:
        text_input = st.text_area(
            "Quick result entry",
            value=st.session_state.ai_match_transcript or "",
            key="manual_match_text",
            height=80,
            placeholder="Alice beat Bob 3-1\nTable 2: Maria defeated Tomas 3 to 2\nBob lost to Alice 1-3",
            help="Type a match result in natural language"
        )

        if st.button("🔍 Parse result", key="parse_text_btn", use_container_width=True):
            if text_input.strip():
                st.session_state.ai_match_transcript = text_input.strip()
                st.session_state.ai_match_parsed = None
                st.session_state.ai_match_error = None

                with st.spinner("Parsing match result..."):
                    try:
                        response = api_request(
                            "post",
                            "/api/match/parse",
                            json={"text": text_input.strip()},
                            parse_json=True,
                            error_context="match result parsing"
                        )
                        if response is not None:
                            st.session_state.ai_match_parsed = response
                        else:
                            st.session_state.ai_match_error = "Failed to parse match result"
                    except Exception as e:
                        st.session_state.ai_match_error = f"Error parsing match result: {e}"
            else:
                st.warning("Please enter a match result first.")


def render_confirmed_result_form(parsed: dict, tournaments: list):
    """
    Render the confirmation panel and editable form for a parsed match result.
    Returns the submitted payload dict or None.
    """
    st.divider()
    st.markdown("**Step 2: Review Parsed Result**")
    st.caption("Verify the parsed match details below. Edit if needed before submitting.")

    # Status and warnings
    status = parsed.get("status", "error")
    if status == "needs_review":
        st.warning("🟡 This result needs review — please verify the details carefully.")
    elif status == "error":
        st.error("🔴 Could not parse the match result. Please enter manually.")
    else:
        st.success("🟢 Result parsed successfully.")

    if parsed.get("warnings"):
        for warning in parsed["warnings"]:
            st.warning(f"⚠️ {warning}")

    # Confirmation card
    with st.container(border=True):
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown(f"**Transcript:** {parsed.get('transcript', '')}")
        with col_t2:
            st.markdown(f"**Confidence:** {parsed.get('confidence', 0):.0%}")
        st.markdown(f"**Player 1:** {parsed.get('player1') or 'Not detected'}")
        st.markdown(f"**Player 2:** {parsed.get('player2') or 'Not detected'}")
        st.markdown(f"**Score:** {parsed.get('score') or 'Not detected'}")
        st.markdown(f"**Winner:** {parsed.get('winner') or 'Not detected'}")

    # Step 3: Edit and Submit
    st.markdown("**Step 3: Confirm or Edit**")
    st.caption("Review the match details and click Submit to save to the database.")

    with st.form("confirmed_match_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            p1 = st.text_input("Player 1", value=parsed.get("player1") or "")
        with col_p2:
            p2 = st.text_input("Player 2", value=parsed.get("player2") or "")

        # Parse score for number inputs
        score_str = parsed.get("score") or "0-0"
        try:
            s1_val, s2_val = map(int, score_str.split("-"))
        except Exception:
            s1_val, s2_val = 0, 0

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            s1 = st.number_input("Player 1 Score", min_value=0, max_value=10, value=s1_val)
        with col_s2:
            s2 = st.number_input("Player 2 Score", min_value=0, max_value=10, value=s2_val)

        # Winner selection
        winner_options = ["Select winner", p1, p2] if p1 and p2 else ["Select Players First"]
        winner_index = 0
        if parsed.get("winner") in winner_options:
            winner_index = winner_options.index(parsed["winner"])
        winner = st.selectbox("Winner", winner_options, index=winner_index)
        score = f"{s1}-{s2}"

        # Tournament selection (preserve existing behavior)
        tournament_options = {t.name: t.id for t in tournaments}
        selected_tournament = st.selectbox(
            "Tournament (optional)",
            options=["None"] + list(tournament_options.keys())
        )

        # Validation warning
        if p1 and p2 and winner != "Select winner":
            if winner != p1 and winner != p2:
                st.warning("⚠️ Winner must be one of the players")

        # Ranking intelligence: upset alert and seeding suggestion
        if ENABLE_RANKING_INTELLIGENCE and p1 and p2 and winner != "Select winner":
            st.space("small")
            # Look up player IDs by name
            db = SessionLocal()
            try:
                p1_obj = db.query(Player).filter(Player.name == p1).first()
                p2_obj = db.query(Player).filter(Player.name == p2).first()
                if p1_obj and p2_obj:
                    winner_obj = db.query(Player).filter(Player.name == winner).first()
                    winner_id = winner_obj.id if winner_obj else None
                    preview_resp = api_request(
                        "post",
                        "/api/ratings/preview-match",
                        json={
                            "player1_id": p1_obj.id,
                            "player2_id": p2_obj.id,
                            "winner_id": winner_id,
                        },
                        parse_json=True,
                        error_context="rating preview",
                    )
                    if preview_resp:
                        if preview_resp.get("upset_possible"):
                            st.warning(
                                f"⚠️ **Possible upset:** {preview_resp.get('explanation', '')}"
                            )
                        else:
                            st.info(f"ℹ️ {preview_resp.get('explanation', '')}")
            except Exception as e:
                st.caption(f"Ranking preview unavailable: {e}")
            finally:
                db.close()

        submitted = st.form_submit_button("📤 Submit confirmed result", use_container_width=True)

        if submitted:
            if not p1 or not p2:
                st.error("Please provide both player names")
                return None
            elif winner == "Select winner":
                st.error("Please select a winner")
                return None
            elif winner != p1 and winner != p2:
                st.error("Winner must be one of the players")
                return None
            else:
                return {
                    "player1": p1,
                    "player2": p2,
                    "score": score,
                    "winner": winner,
                    "tournament_id": tournament_options.get(selected_tournament) if selected_tournament != "None" else None
                }
    return None


def submit_match_result(payload: dict):
    """Submit a confirmed match result payload to /api/report."""
    db = SessionLocal()
    try:
        with st.status("Submitting result...", expanded=False) as status:
            response = api_request(
                "post",
                "/api/report",
                json=payload,
                error_context="match result submission"
            )
            if response is not None:
                status.update(label="Result submitted!", state="complete", expanded=False)
                st.success("✅ Match result submitted successfully!")
                return True
            return False
    except Exception as e:
        st.error(f"Connection error: {e}")
        return False
    finally:
        db.close()


def render_match_reporting_tab(db):
    """
    Render the Match Reporting tab with confirm-before-submit flow.
    """
    st.subheader("🎾 Report Match Result")
    st.caption("Enter or record a match result, review the parsed details, then confirm to submit.")

    # Initialize session state
    if 'ai_match_transcript' not in st.session_state:
        st.session_state['ai_match_transcript'] = None
    if 'ai_match_parsed' not in st.session_state:
        st.session_state['ai_match_parsed'] = None
    if 'ai_match_error' not in st.session_state:
        st.session_state['ai_match_error'] = None

    # Step 1: Input
    render_voice_or_text_parser()

    # Step 2 & 3: Review and confirm
    if st.session_state.ai_match_parsed:
        tournaments = db.query(Tournament).all()
        payload = render_confirmed_result_form(st.session_state.ai_match_parsed, tournaments)
        if payload:
            if submit_match_result(payload):
                # Clear session state on success
                st.session_state.ai_match_transcript = None
                st.session_state.ai_match_parsed = None
                st.session_state.ai_match_error = None
                st.rerun()

    # Show error if any
    if st.session_state.ai_match_error:
        st.error(st.session_state.ai_match_error)

    # Clear parsed result button
    if st.session_state.ai_match_parsed or st.session_state.ai_match_error:
        if st.button("🔄 Clear parsed result", key="clear_parsed_result"):
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
    db = SessionLocal()
    try:
        render_match_reporting_tab(db)
    finally:
        db.close()

with tab_tournaments:
    render_active_tournaments()
