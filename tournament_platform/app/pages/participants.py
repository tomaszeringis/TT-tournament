"""
Participants page - Redirect Wrapper

This page has been consolidated into Events & Draws.
Use the Participants tab on the Events & Draws page for player registration and management.

This file is kept as a redirect for backward compatibility.
"""

import streamlit as st

st.title("Participants (Moved)")
st.caption("Participant management has been moved to the Events & Draws page.")

st.info("👥 **Participants** functionality is now available in the **Events & Draws** page under the **Participants** tab.")
st.info("Please use the navigation menu to go to **Events & Draws**.")

if st.button("Go to Events & Draws", type="primary"):
    st.switch_page("pages/events_draws.py")
