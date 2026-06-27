import os
import streamlit as st
import streamlit_authenticator as stauth
import yaml

from tournament_platform.config import settings

st.set_page_config(page_title="TT Platform", layout="wide")

# Auth Load
config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(config_path) as file:
    config = yaml.load(file, Loader=yaml.SafeLoader)

# Override auth config with environment-backed settings
config['cookie']['name'] = settings.AUTH_COOKIE_NAME
config['cookie']['key'] = settings.AUTH_COOKIE_KEY
config['cookie']['expiry_days'] = settings.AUTH_COOKIE_EXPIRY_DAYS

# Allow credentials to be overridden via Streamlit secrets (for production)
# Streamlit secrets take precedence over config.yaml
# Use try/except to handle missing secrets.toml gracefully
try:
    if hasattr(st, 'secrets') and 'credentials' in st.secrets:
        config['credentials'] = dict(st.secrets['credentials'])
except Exception:
    # No secrets file found or other error, use config.yaml credentials
    pass

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
    # Use absolute paths based on this file's location so they work from any CWD
    app_dir = os.path.dirname(__file__)
    page_dashboard = st.Page(os.path.join(app_dir, "pages", "dashboard.py"), title="Dashboard", icon="📊")
    page_rankings = st.Page(os.path.join(app_dir, "pages", "rankings.py"), title="Rankings", icon="🏆")
    page_tournament = st.Page(os.path.join(app_dir, "pages", "tournament_setup.py"), title="Tournament Setup", icon="⚙️")
    page_admin = st.Page(os.path.join(app_dir, "pages", "admin.py"), title="Admin", icon="👨‍💼")
    page_voice_rules = st.Page(os.path.join(app_dir, "pages", "voice_rules_chat.py"), title="Voice Rules Chat", icon="🎤")
    page_voice_scorekeeper = st.Page(os.path.join(app_dir, "pages", "voice_scorekeeper.py"), title="Voice Scorekeeper", icon="🔊")

    navigation = st.navigation([page_dashboard, page_rankings, page_tournament, page_admin, page_voice_rules, page_voice_scorekeeper])
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
