"""
Rankings page - Redirect Wrapper

This page has been consolidated into Dashboard.
Use the Rankings tab on the Dashboard page for leaderboard and rating history.

This file is kept as a redirect for backward compatibility.
"""

import streamlit as st

st.title("Rankings (Moved)")
st.caption("Rankings have been moved to the Dashboard page.")

st.info("🏆 **Rankings** functionality is now available in the **Dashboard** page under the **Rankings** tab.")
st.info("Please use the navigation menu to go to **Dashboard**.")

if st.button("Go to Dashboard", type="primary"):
    st.switch_page("pages/dashboard.py")
