"""
Events & Draws page for Tournament Platform.

This page handles tournament creation, bracket generation, and standings.
Extracted from tournament_setup.py for better separation of concerns.
"""

import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd

from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus, TournamentType
from tournament_platform.services.tournament_engine import TournamentFactory, TournamentContext, KnockoutStrategy, RoundRobinStrategy
from tournament_platform.services.bracket_manager import TournamentState
from tournament_platform.app.components.interactive_bracket import interactive_bracket
from tournament_platform.app.utils import render_status_badge


def render_tournament_creation_wizard():
    """
    Render a full-width guided tournament creation flow.
    Step 1: basics (name, description)
    Step 2: format (Single Elimination / Round Robin)
    Step 3: participants
    Step 4: review and create
    """
    st.subheader("🏆 Create New Tournament")
    
    # Initialize session state for wizard
    if 'wizard_step' not in st.session_state:
        st.session_state['wizard_step'] = 1
    if 'tournament_name' not in st.session_state:
        st.session_state['tournament_name'] = ""
    if 'tournament_desc' not in st.session_state:
        st.session_state['tournament_desc'] = ""
    if 'tournament_format' not in st.session_state:
        st.session_state['tournament_format'] = "Single Elimination"
    if 'tournament_participants' not in st.session_state:
        st.session_state['tournament_participants'] = []
    
    # Get all players for selection
    db = SessionLocal()
    all_players = db.query(Player).all()
    player_names = [p.name for p in all_players]
    db.close()
    
    # Progress indicator
    cols = st.columns(4)
    for i in range(1, 5):
        with cols[i-1]:
            if st.session_state['wizard_step'] >= i:
                st.markdown(f"**{i}. Step {i}**")
            else:
                st.markdown(f"Step {i}")
    
    st.divider()
    
    # Step 1: Basics
    if st.session_state['wizard_step'] == 1:
        st.write("**Step 1: Tournament Basics**")
        st.session_state['tournament_name'] = st.text_input(
            "Tournament Name",
            value=st.session_state['tournament_name'],
            help="Enter a unique name for your tournament"
        )
        st.session_state['tournament_desc'] = st.text_area(
            "Description",
            value=st.session_state['tournament_desc'],
            help="Optional description of the tournament format or rules"
        )
        
        col1, col2 = st.columns([1, 1])
        with col2:
            if st.button("Next →", use_container_width=True):
                if st.session_state['tournament_name']:
                    st.session_state['wizard_step'] = 2
                    st.rerun()
                else:
                    st.error("Please enter a tournament name")
    
    # Step 2: Format
    elif st.session_state['wizard_step'] == 2:
        st.write("**Step 2: Tournament Format**")
        st.session_state['tournament_format'] = st.radio(
            "Choose the competition structure",
            options=["Single Elimination", "Round Robin"],
            index=0 if st.session_state['tournament_format'] == "Single Elimination" else 1,
            help="Single Elimination: knockout bracket. Round Robin: everyone plays everyone."
        )
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("← Back", use_container_width=True):
                st.session_state['wizard_step'] = 1
                st.rerun()
        with col2:
            if st.button("Next →", use_container_width=True):
                st.session_state['wizard_step'] = 3
                st.rerun()
    
    # Step 3: Participants
    elif st.session_state['wizard_step'] == 3:
        st.write("**Step 3: Select Participants**")
        st.session_state['tournament_participants'] = st.multiselect(
            "Choose at least 2 players",
            options=player_names,
            default=st.session_state['tournament_participants'],
            help="Select players to participate in this tournament"
        )
        
        if not player_names:
            st.info("No players registered yet. Register players on the Participants page first.")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("← Back", use_container_width=True):
                st.session_state['wizard_step'] = 2
                st.rerun()
        with col2:
            if st.button("Next →", use_container_width=True):
                if len(st.session_state['tournament_participants']) >= 2:
                    st.session_state['wizard_step'] = 4
                    st.rerun()
                else:
                    st.error("Please select at least 2 players")
    
    # Step 4: Review and Create
    elif st.session_state['wizard_step'] == 4:
        st.write("**Step 4: Review and Create**")
        
        st.info(f"**Name:** {st.session_state['tournament_name']}")
        st.info(f"**Description:** {st.session_state['tournament_desc'] or 'No description'}")
        st.info(f"**Format:** {st.session_state['tournament_format']}")
        st.info(f"**Participants:** {len(st.session_state['tournament_participants'])} players")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("← Back", use_container_width=True):
                st.session_state['wizard_step'] = 3
                st.rerun()
        with col2:
            if st.button("🏆 Create Tournament", use_container_width=True, type="primary"):
                try:
                    db = SessionLocal()
                    
                    # Check if tournament name already exists
                    existing = db.query(Tournament).filter(
                        Tournament.name == st.session_state['tournament_name']
                    ).first()
                    
                    if existing:
                        st.error(f"Tournament '{st.session_state['tournament_name']}' already exists!")
                    else:
                        is_knockout = st.session_state['tournament_format'] == "Single Elimination"
                        t_type = TournamentType.knockout if is_knockout else TournamentType.round_robin
                        
                        new_tournament = Tournament(
                            name=st.session_state['tournament_name'],
                            description=st.session_state['tournament_desc'],
                            tournament_type=t_type
                        )
                        db.add(new_tournament)
                        db.flush()
                        
                        # Generate matches
                        strategies = {
                            "Single Elimination": KnockoutStrategy(),
                            "Round Robin": RoundRobinStrategy()
                        }
                        selected_strategy = strategies[st.session_state['tournament_format']]
                        context = TournamentContext(selected_strategy)
                        context.run_generation(st.session_state['tournament_participants'], new_tournament.id, db)
                        
                        db.commit()
                        st.toast(f"✅ Tournament '{st.session_state['tournament_name']}' created!", icon="🏆")
                        
                        # Reset wizard
                        st.session_state['wizard_step'] = 1
                        st.session_state['tournament_name'] = ""
                        st.session_state['tournament_desc'] = ""
                        st.session_state['tournament_format'] = "Single Elimination"
                        st.session_state['tournament_participants'] = []
                        st.rerun()
                except Exception as e:
                    st.error(f"Error creating tournament: {e}")
                finally:
                    db.close()


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
        standings_df = standings_df.rename(columns={
            "name": "Player",
            "wins": "W",
            "losses": "L",
            "matches_played": "MP",
            "points_for": "PF",
            "points_against": "PA"
        })
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
    st.subheader("🏆 Active Tournaments")
    
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
        st.info("No tournaments created yet. Use the wizard above to create one!")
    
    db.close()


# Main page
st.title("🏆 Events & Draws")
st.space("medium")

# Tabs: Create Tournament and Active Tournaments
tab_create, tab_active = st.tabs(["➕ Create Tournament", "🏆 Active Tournaments"])

with tab_create:
    render_tournament_creation_wizard()

with tab_active:
    render_active_tournaments()