"""
Public Tournament Self-Serve Registration and Check-In.

This module is designed to be imported and called from ``main.py`` when
``?public=1&register=1`` is detected in the query parameters. No auth or
navigation is rendered here.

IMPORTANT: This module does NOT call ``st.set_page_config``. ``main.py`` must
call it before importing/running this module.
"""

import streamlit as st

from tournament_platform.config import settings
from tournament_platform.models import SessionLocal
from tournament_platform.app.design_system import apply_global_styles, BRAND
from tournament_platform.app.services.registration_service import (
    get_registration_link,
    validate_registration_token,
    register_player,
    find_duplicate_candidates_for_registration,
    check_in_player,
    force_register_player,
)
from tournament_platform.app.components.brand import icon_path


def render_public_registration() -> None:
    """Render the sign-in-free tournament registration/check-in page."""
    apply_global_styles()

    st.markdown(
        f"<h1 style='text-align: center;'>🏓 {BRAND['name']} — Registration</h1>",
        unsafe_allow_html=True,
    )

    query_params = st.query_params
    tournament_id = query_params.get("tournament")
    token = query_params.get("token", "")

    if not tournament_id:
        st.error("Missing tournament parameter.")
        st.stop()

    try:
        tournament_id_int = int(tournament_id)
    except (ValueError, TypeError):
        st.error("Invalid tournament parameter.")
        st.stop()

    db = SessionLocal()
    try:
        tournament = validate_registration_token(db, tournament_id_int, token)
        if not tournament:
            st.error("Invalid registration link or registration is closed.")
            st.stop()

        if not tournament.registration_open:
            st.warning("Registration is currently closed for this tournament.")
            st.stop()

        tournament_name = tournament.name
        registration_open = bool(tournament.registration_open)
    finally:
        db.close()

    if "reg_state" not in st.session_state:
        st.session_state["reg_state"] = "form"

    reg_state = st.session_state["reg_state"]
    st.caption(f"Tournament: **{tournament_name}**")

    if reg_state == "form":
        with st.form("public_registration_form", clear_on_submit=True):
            display_name = st.text_input(
                "Display name *",
                max_chars=64,
                placeholder="How should we display you?",
            )
            department = st.text_input(
                "Department / team (optional)",
                max_chars=120,
                placeholder="e.g. Engineering",
            )
            email = st.text_input(
                "Email (optional)",
                max_chars=120,
                placeholder="you@example.com",
            )
            employee_id = st.text_input(
                "Employee ID (optional)",
                max_chars=120,
                placeholder="e.g. EMP-123",
            )
            submitted = st.form_submit_button("Register / Check in", use_container_width=True)

        if submitted:
            if not display_name or not display_name.strip():
                st.error("Display name is required.")
            else:
                db2 = SessionLocal()
                try:
                    result = register_player(
                        db2,
                        tournament_id_int,
                        display_name.strip(),
                        department=department.strip() if department else None,
                        email=email.strip() if email else None,
                        employee_id=employee_id.strip() if employee_id else None,
                        source="public_self_serve",
                    )
                finally:
                    db2.close()

                action = result.get("action", "duplicate_blocked")
                participant = result.get("participant")
                duplicates = result.get("duplicates", [])

                if action == "checked_in_existing" and participant:
                    st.session_state["reg_participant"] = participant
                    st.session_state["reg_state"] = "success"
                    st.rerun()
                elif action == "created_new" and participant:
                    st.session_state["reg_participant"] = participant
                    st.session_state["reg_state"] = "success"
                    st.rerun()
                elif duplicates:
                    st.session_state["reg_form_values"] = {
                        "display_name": display_name.strip(),
                        "department": department.strip() if department else None,
                        "email": email.strip() if email else None,
                        "employee_id": employee_id.strip() if employee_id else None,
                    }
                    st.session_state["reg_duplicates"] = duplicates
                    st.session_state["reg_state"] = "duplicate"
                    st.rerun()
                else:
                    st.error("Registration failed. Please contact the operator.")

    elif reg_state == "duplicate":
        duplicates = st.session_state.get("reg_duplicates", [])
        st.warning("⚠️ Possible duplicate found")
        for dup in duplicates:
            st.markdown(
                f"- **{dup['display_name']}** — {dup['reason']} ({dup['confidence']} confidence)"
            )

        form_values = st.session_state.get("reg_form_values", {})
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("✅ This is me / check in existing", use_container_width=True, key="dup_me"):
                top_dup = duplicates[0]
                db3 = SessionLocal()
                try:
                    participant = check_in_player(db3, tournament_id_int, top_dup["player_id"])
                finally:
                    db3.close()
                if participant:
                    st.session_state["reg_participant"] = participant
                    st.session_state["reg_state"] = "success"
                    st.rerun()
                else:
                    st.error("Failed to check in existing player.")

        with col2:
            allow_new = True
            block_reason = ""
            if duplicates and duplicates[0]["confidence"] == "high":
                allow_new = False
                block_reason = "This name is already in use. Please contact the operator if this is a new player."
            if allow_new and st.button("🆕 This is a new player", use_container_width=True, key="dup_new"):
                db4 = SessionLocal()
                try:
                    flagged = bool(duplicates and duplicates[0]["confidence"] == "medium")
                    new_participant = force_register_player(
                        db4,
                        tournament_id_int,
                        form_values.get("display_name", ""),
                        department=form_values.get("department"),
                        email=form_values.get("email"),
                        employee_id=form_values.get("employee_id"),
                        source="public_self_serve",
                        duplicate_status="pending_review" if flagged else None,
                    )
                finally:
                    db4.close()

                if new_participant:
                    st.session_state["reg_participant"] = new_participant
                    st.session_state["reg_state"] = "success"
                    st.rerun()
                else:
                    st.error("Failed to create new registration.")

        with col3:
            if st.button("📞 Ask operator", use_container_width=True, key="dup_operator"):
                st.info("Your registration is pending operator review.")

        if allow_new is False:
            st.caption(block_reason)

        if st.button("← Back to form", key="dup_back"):
            st.session_state["reg_state"] = "form"
            st.rerun()

    elif reg_state == "success":
        participant = st.session_state.get("reg_participant")
        if participant:
            st.success("✅ You are checked in!")
            st.markdown(f"**Your display name:** {participant.display_name}")
            st.markdown("**You are in the bracket pool.**")
        else:
            st.success("✅ Registration complete.")

        if st.button("Register another player", key="reg_another"):
            st.session_state["reg_state"] = "form"
            st.session_state.pop("reg_participant", None)
            st.session_state.pop("reg_duplicates", None)
            st.rerun()
