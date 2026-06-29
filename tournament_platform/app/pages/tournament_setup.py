"""
Tournament Setup - Legacy Compatibility Page

This page is deprecated. The functionality has been split into:
- Participants page: Player registration and management
- Events & Draws page: Tournament creation and bracket visualization

This page is kept for backward compatibility and will be removed in a future version.
"""

import streamlit as st

from tournament_platform.models import SessionLocal, Tournament


# Main page - Legacy compatibility page
st.title("⚙️ Tournament Setup (Legacy)")
st.caption("This page is deprecated. Please use the new dedicated pages below.")

st.divider()

# Redirect notice
st.info("👥 **Participants** and **Events & Draws** pages are now available in the navigation menu.")
st.info("This page is kept for backward compatibility and will be removed in a future version.")

# Quick links to new pages
col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/participants.py", label="Go to Participants", icon="👥")
with col2:
    st.page_link("pages/events_draws.py", label="Go to Events & Draws", icon="🏆")

st.divider()

# Show the old content for reference (read-only)
st.subheader("📋 Current Tournaments (Read-only)")
db = SessionLocal()
try:
    tournaments = db.query(Tournament).all()
    if tournaments:
        for t in tournaments:
            st.write(f"- {t.name} ({t.tournament_type.value})")
    else:
        st.info("No tournaments found. Create one on the Events & Draws page.")
finally:
    db.close()
