"""
Rankings page - Redirect Wrapper

This page has been consolidated into Dashboard.
Use the Rankings tab on the Dashboard page for leaderboard and rating history.

This file is kept as a redirect for backward compatibility.
"""

import streamlit as st

from tournament_platform.app.design_system import apply_global_styles

st.set_page_config(page_title="LIT_IT Rankings (Moved)", layout="wide")
apply_global_styles()

from tournament_platform.app.components.page_header import render_page_header

render_page_header(
    title="LIT_IT Rankings (Moved)",
    description="Rankings have been moved to the Dashboard page.",
)

st.info("🏆 **Rankings** functionality is now available in the **Dashboard** page under the **Rankings** tab.")
st.info("Please use the navigation menu to go to **Dashboard**.")

if st.button("Go to Dashboard", type="primary"):
    st.switch_page("pages/dashboard.py")
