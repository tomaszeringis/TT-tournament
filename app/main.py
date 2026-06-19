import streamlit as st
import streamlit_authenticator as stauth
import yaml
import requests
import pandas as pd
import plotly.graph_objects as go
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import SessionLocal, Player, Match, Tournament, MatchStatus

st.set_page_config(page_title="TT Platform", layout="wide")

# Auth Load
config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(config_path) as file:
    config = yaml.load(file, Loader=yaml.SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

name, authentication_status, username = authenticator.login('main')

if authentication_status:
    st.title("🏓 Company Tournament Dashboard")
    st.space("medium")
    
    # Multi-page navigation using st.navigation (Streamlit 1.35+)
    page_dashboard = st.Page("pages/dashboard.py", title="Dashboard", icon="📊")
    page_rankings = st.Page("pages/rankings.py", title="Rankings", icon="🏆")
    page_tournament = st.Page("pages/tournament_setup.py", title="Tournament Setup", icon="⚙️")
    page_admin = st.Page("pages/admin.py", title="Admin", icon="👨‍💼")

    navigation = st.navigation([page_dashboard, page_rankings, page_tournament, page_admin])
    navigation.run()

    # Show logout button in sidebar
    with st.sidebar:
        st.divider()
        if st.button("🚪 Logout"):
            authenticator.logout()
            st.info("Logged out successfully!")

elif authentication_status == False:
    st.error('❌ Username/password is incorrect')
elif authentication_status == None:
    st.warning('⚠️ Please enter your credentials')
