import os
import streamlit as st
import streamlit_authenticator as stauth
import yaml

from tournament_platform.config import settings
from tournament_platform.app.design_system import GLOBAL_STYLES

st.set_page_config(page_title="TT Platform", layout="wide")

# Apply global design system styles
st.markdown(GLOBAL_STYLES, unsafe_allow_html=True)

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
    # Get user role from config (default to 'user' if not specified)
    user_role = "user"
    if username and username in config.get('credentials', {}).get('usernames', {}):
        user_role = config['credentials']['usernames'][username].get('role', 'user')
    
    # Also check Streamlit secrets for role
    try:
        if hasattr(st, 'secrets') and 'credentials' in st.secrets:
            if username in st.secrets['credentials'].get('usernames', {}):
                user_role = st.secrets['credentials']['usernames'][username].get('role', 'user')
    except Exception:
        pass
    
    st.title("🏓")
    st.space("medium")
    
    # Multi-page navigation using st.navigation (Streamlit 1.35+)
    # Use absolute paths based on this file's location so they work from any CWD
    app_dir = os.path.dirname(__file__)

    # Build navigation with sections
    # Section 1: Home
    home_pages = [
        st.Page(os.path.join(app_dir, "pages", "home.py"), title="Home", icon="🏠"),
    ]

    # Section 2: Setup
    setup_pages = [
        st.Page(os.path.join(app_dir, "pages", "events_draws.py"), title="Events & Draws", icon="🏆"),
        st.Page(os.path.join(app_dir, "pages", "rankings.py"), title="Rankings", icon="🏆"),
        st.Page(os.path.join(app_dir, "pages", "player_profile.py"), title="Player Profile", icon="👤"),
    ]

    # Section 3: Tournament Day
    tournament_day_pages = [
        st.Page(os.path.join(app_dir, "pages", "public_board.py"), title="Public Board", icon="📺"),
        st.Page(os.path.join(app_dir, "pages", "operator_console.py"), title="Match Center", icon="🎛️"),
        st.Page(os.path.join(app_dir, "pages", "schedule_board.py"), title="Schedule", icon="📅"),
        st.Page(os.path.join(app_dir, "pages", "voice_scorekeeper.py"), title="Voice Scorekeeper", icon="🔊"),
    ]

    # Section 4: Insights
    insights_pages = [
        st.Page(os.path.join(app_dir, "pages", "dashboard.py"), title="Dashboard", icon="📊"),
        st.Page(os.path.join(app_dir, "pages", "ai_assistant.py"), title="AI Assistant (Experimental)", icon="🤖"),
    ]

    # Section 5: Admin (only for admin users)
    admin_pages = []
    if user_role == "admin":
        admin_pages.append(
            st.Page(os.path.join(app_dir, "pages", "admin.py"), title="Admin", icon="👨‍💼")
        )

    # Section 6: Experimental (hidden by default)
    experimental_pages = []
    if settings.DEBUG_UI_ENABLED or user_role == "admin":
        experimental_pages.extend([
            st.Page(os.path.join(app_dir, "pages", "video_scorekeeper.py"), title="Video Scorekeeper", icon="🎥"),
            st.Page(os.path.join(app_dir, "pages", "dataset_catalog.py"), title="Dataset Catalog", icon="📊"),
            st.Page(os.path.join(app_dir, "pages", "coaching_lab.py"), title="Coaching Lab", icon="🏓"),
            st.Page(os.path.join(app_dir, "pages", "experiment_dashboard.py"), title="Experiment Dashboard", icon="🧪"),
        ])

    # Combine all pages into sections
    all_pages = [
        *home_pages,
        *setup_pages,
        *tournament_day_pages,
        *insights_pages,
        *admin_pages,
        *experimental_pages,
    ]

    navigation = st.navigation(all_pages)
    navigation.run()

    # Show user info and logout button in sidebar
    with st.sidebar:
        st.divider()
        st.markdown(f"**Logged in as:** {name or username}")
        st.markdown(f"**Role:** {user_role}")
        st.divider()
        if st.button("🚪 Logout"):
            authenticator.logout()
            st.info("Logged out successfully!")

elif authentication_status == False:
    st.error('❌ Username/password is incorrect')
elif authentication_status == None:
    st.warning('⚠️ Please enter your credentials')
