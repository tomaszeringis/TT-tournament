"""
Participants Panel component for Streamlit UI.

Reusable participant management that can be embedded in Events & Draws or other pages.
Provides player registration form and player list.
"""

import streamlit as st

from tournament_platform.models import SessionLocal, Player
from tournament_platform.app.utils import render_database_connection_error
from tournament_platform.config import settings


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
            st.info("No players registered yet. Use the form on the left to register players.")
            st.caption("Once you have at least 2 players, you can create a tournament in the Events tab.")

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


def render_approval_queue():
    """Render the organizer approval queue for self-registered (pending) players."""
    st.subheader("✅ Registration Approval")

    try:
        db = SessionLocal()
        pending = db.query(Player).filter(Player.registration_status == "pending").all()
    except Exception as e:
        st.error(f"Error loading pending players: {e}")
        return
    finally:
        db.close()

    if not pending:
        st.info("No pending registrations. Self-registration is off unless enabled.")
        return

    for p in pending:
        with st.container(border=True):
            col_info, col_action = st.columns([3, 1])
            with col_info:
                st.markdown(f"**{p.name}** ({p.email})")
                st.caption(f"Source: {p.import_source or 'unknown'}")
            with col_action:
                if st.button("✅ Approve", key=f"approve_{p.id}"):
                    db = SessionLocal()
                    try:
                        player = db.query(Player).filter(Player.id == p.id).first()
                        if player:
                            player.registration_status = "approved"
                            db.commit()
                            st.toast(f"Approved {player.name}", icon="✅")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Approval failed: {e}")
                    finally:
                        db.close()


def render_participants_panel():
    """
    Render the complete participants management panel.
    This is the main entry point for embedding participants functionality.
    """
    render_player_registration_section()

    if settings.ENABLE_CSV_BULK_IMPORT:
        st.divider()
        with st.expander("📥 CSV Bulk Import", expanded=False):
            from tournament_platform.app.components.csv_import_panel import render_csv_import_panel
            render_csv_import_panel()

    if settings.ENABLE_SELF_REGISTRATION:
        st.divider()
        render_approval_queue()
