"""
Participants page for Tournament Platform.

This page handles player registration and management.
Extracted from tournament_setup.py for better separation of concerns.
"""

import streamlit as st
import streamlit_shadcn_ui as ui

from tournament_platform.models import SessionLocal, Player
from tournament_platform.app.utils import render_database_connection_error


def render_player_registration_form():
    """
    Render the player registration form.
    
    Returns:
        True if a player was successfully registered, False otherwise.
    """
    try:
        db = SessionLocal()
    except Exception as e:
        render_database_connection_error(e)
        return False
    
    success = False
    
    with st.form("player_form", clear_on_submit=True):
        player_name = st.text_input("Player Name")
        player_email = st.text_input("Email")
        
        if st.form_submit_button("➕ Register Player"):
            if player_name and player_email:
                # Check for duplicate player
                existing = db.query(Player).filter(
                    (Player.name == player_name) | (Player.email == player_email)
                ).first()
                
                if existing:
                    if existing.name == player_name:
                        st.error(f"Player '{player_name}' is already registered.")
                    else:
                        st.error(f"Email '{player_email}' is already registered to '{existing.name}'.")
                else:
                    try:
                        new_player = Player(
                            name=player_name,
                            email=player_email,
                            rating=1200
                        )
                        db.add(new_player)
                        db.commit()
                        st.toast(f"✅ Player '{player_name}' registered!", icon="✅")
                        success = True
                    except Exception as e:
                        st.error(f"Error registering player: {e}")
            else:
                st.toast("Please fill in all fields", icon="⚠️")
    
    db.close()
    return success


def render_player_list():
    """
    Render the list of registered players.
    """
    try:
        db = SessionLocal()
        players = db.query(Player).all()
        
        if players:
            player_list = "\n".join([
                f"- {p.name} ({p.email}) - Rating: {p.rating}" 
                for p in players
            ])
            st.code(player_list)
        else:
            st.info("No players registered yet")
        
        db.close()
    except Exception as e:
        st.error(f"Error loading players: {e}")


def render_player_registration_section():
    """
    Render the complete player registration section.
    This is a convenience function that combines the form and list.
    """
    st.subheader("👥 Player Registration")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.write("**Register New Player**")
        render_player_registration_form()
    
    with col2:
        st.write("**Registered Players**")
        render_player_list()


# Main page
st.title("👥 Participants")
st.space("medium")

# Player Registration Section
render_player_registration_section()