"""
Participants Panel component for Streamlit UI.

Reusable participant management that can be embedded in Events & Draws or other pages.
Provides player registration form and player list.
"""

import streamlit as st
from typing import Optional

from tournament_platform.models import SessionLocal, Player, Tournament, TournamentParticipant
from tournament_platform.app.utils import render_database_connection_error
from tournament_platform.config import settings
from tournament_platform.app.services.registration_service import (
    get_registration_link,
    get_registration_stats,
    list_pending_duplicates,
    merge_participant_into_player,
    approve_duplicate_as_new,
    dismiss_duplicate_review,
    set_registration_token,
    clear_registration_token,
    validate_registration_token,
)
from tournament_platform.app.design_system import render_chip, render_qr_code


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


def _get_tournament_selector() -> Optional[int]:
    """Render a tournament selector and return the selected tournament id, or None."""
    try:
        db = SessionLocal()
        tournaments = db.query(Tournament).order_by(Tournament.name.asc()).all()
        db.close()
    except Exception as e:
        st.error(f"Error loading tournaments: {e}")
        return None

    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        return None

    options = {t.name: t.id for t in tournaments}
    selected_name = st.selectbox(
        "Select Tournament",
        options=list(options.keys()),
        key="participants_tournament_select",
    )
    return options[selected_name]


def render_registration_controls(tournament: Tournament) -> None:
    """Render self-serve registration controls for a tournament.

    Includes:
    - Open/close registration toggle
    - Registration link and QR code
    - Check-in stats chips
    """
    st.subheader("🎫 Self-Serve Registration")

    col_toggle, col_spacer = st.columns([1, 3])
    with col_toggle:
        current_open = bool(tournament.registration_open)
        new_open = st.toggle(
            "Registration Open",
            value=current_open,
            key=f"reg_toggle_{tournament.id}",
            help="Allow players to self-register via the public link",
        )
        if new_open != current_open:
            db = SessionLocal()
            try:
                if new_open and not tournament.public_registration_token_hash:
                    token = set_registration_token(db, tournament.id)
                    st.toast(f"Registration opened. Token: {token[:8]}...", icon="🔑")
                elif new_open and tournament.public_registration_token_hash:
                    tournament.registration_open = True
                    db.add(tournament)
                    db.commit()
                    st.toast("Registration opened.", icon="✅")
                else:
                    clear_registration_token(db, tournament.id)
                    st.toast("Registration closed.", icon="🔒")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update registration: {e}")
            finally:
                db.close()

    if not tournament.registration_open:
        st.caption("Registration is currently closed. Turn on the toggle to generate a shareable link.")
        return

    if not tournament.public_registration_token_hash:
        st.warning("Registration is open but no token is set. Generating one now...")
        db = SessionLocal()
        try:
            token = set_registration_token(db, tournament.id)
            st.rerun()
        except Exception as e:
            st.error(f"Failed to generate token: {e}")
        finally:
            db.close()
        return

    link = get_registration_link("REGISTRATION_TOKEN", tournament.id)
    db = SessionLocal()
    try:
        stats = get_registration_stats(db, tournament.id)
    finally:
        db.close()

    st.markdown("**Shareable Link**")
    st.code(link, language=None)
    if st.button("📋 Copy Link", key=f"copy_reg_link_{tournament.id}"):
        st.toast("Link copied to clipboard!", icon="✅")

    try:
        render_qr_code(link, scale=4)
        st.caption("Scan to open the registration page on a phone/tablet.")
    except Exception:
        pass

    st.divider()
    st.markdown("**Registration Stats**")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Registered", stats.registered_count)
    col2.metric("Checked In", stats.checked_in_count)
    col3.metric("Duplicate Review", stats.duplicate_pending_count, delta_color="inverse" if stats.duplicate_pending_count == 0 else "off")
    col4.metric("Bracket Eligible", stats.bracket_eligible_count)


def render_duplicate_review_panel(tournament: Tournament) -> None:
    """Render the operator duplicate review panel for a tournament."""
    st.subheader("🔁 Duplicate Review")

    db = SessionLocal()
    try:
        pending = list_pending_duplicates(db, tournament.id)
        stats = get_registration_stats(db, tournament.id)
    finally:
        db.close()

    if stats.duplicate_pending_count == 0:
        st.success("No pending duplicate reviews.")
        return

    st.warning(f"{stats.duplicate_pending_count} participant(s) pending duplicate review.")

    for p in pending:
        with st.container(border=True):
            st.markdown(f"**{p.display_name}**")
            st.caption(f"Participant ID: {p.id} | Player ID: {p.player_id} | Source: {p.registration_source or 'unknown'}")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("✅ Approve as new", key=f"dup_approve_{p.id}"):
                    db2 = SessionLocal()
                    try:
                        approve_duplicate_as_new(db2, p.id)
                        st.toast(f"Approved {p.display_name} as new player.", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Approval failed: {e}")
                    finally:
                        db2.close()
            with col2:
                if st.button("🗑️ Dismiss review", key=f"dup_dismiss_{p.id}"):
                    db2 = SessionLocal()
                    try:
                        dismiss_duplicate_review(db2, p.id)
                        st.toast(f"Dismissed review for {p.display_name}.", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Dismiss failed: {e}")
                    finally:
                        db2.close()
            with col3:
                st.caption("Use Participants tab to merge if needed.")


def render_participants_panel(tournament_id: Optional[int] = None) -> None:
    """
    Render the complete participants management panel.
    This is the main entry point for embedding participants functionality.

    Args:
        tournament_id: Optional tournament context for registration controls.
    """
    if settings.ENABLE_SELF_REGISTRATION:
        active_tournament_id = tournament_id
        if active_tournament_id is None:
            active_tournament_id = _get_tournament_selector()

        if active_tournament_id is not None:
            try:
                db = SessionLocal()
                tournament = db.query(Tournament).filter(Tournament.id == active_tournament_id).first()
                db.close()
                if tournament:
                    render_registration_controls(tournament)
                    st.divider()
                    render_duplicate_review_panel(tournament)
            except Exception as e:
                st.error(f"Error loading tournament registration data: {e}")

    render_player_registration_section()

    if settings.ENABLE_CSV_BULK_IMPORT:
        st.divider()
        with st.expander("📥 CSV Bulk Import", expanded=False):
            from tournament_platform.app.components.csv_import_panel import render_csv_import_panel
            render_csv_import_panel()

    if settings.ENABLE_SELF_REGISTRATION:
        st.divider()
        render_approval_queue()
