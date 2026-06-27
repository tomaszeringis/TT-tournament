"""
Player Registration component for Streamlit UI.
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


@st.cache_data(ttl=30)
def get_all_players():
    """
    Get all players as a list of dicts.
    
    Returns:
        List of player dictionaries with id, name, and rating.
    """
    try:
        db = SessionLocal()
        players = db.query(Player).order_by(Player.name).all()
        result = [
            {"id": p.id, "name": p.name, "rating": p.rating}
            for p in players
        ]
        db.close()
        return result
    except Exception:
        return []