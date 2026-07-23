import os
import streamlit as st
import streamlit_authenticator as stauth
import yaml

from tournament_platform.config import settings
from tournament_platform.app.design_system import GLOBAL_STYLES, BRAND
from tournament_platform.app.components.brand import render_sidebar_logo, icon_path, PAGE_ICONS
from tournament_platform.app.components.tour import render_tour_dialog
from tournament_platform.app.components.active_context_bar import render_active_context_bar


def main() -> None:
    """Render the Streamlit Tournament Platform UI.

    This module is the Streamlit entrypoint. Everything that touches the
    Streamlit runtime lives inside ``main()`` so the module can be imported
    without starting the UI or any external server. Streamlit Cloud runs this
    via the root ``streamlit_app.py`` entrypoint.
    """
    st.set_page_config(
        page_title="TT Tournament Platform",
        page_icon=icon_path(),
        layout="wide",
    )

    # Public-mode bypass: render the read-only board without auth when
    # the ``public=1`` query parameter is present.
    query_params = st.query_params
    if query_params.get("register") == "1" and query_params.get("public") == "1":
        try:
            from tournament_platform.app.pages.public_registration import render_public_registration
            render_public_registration()
        except Exception as e:
            st.error(f"Failed to render public registration: {e}")
        st.stop()

    if query_params.get("public") == "1":
        try:
            from tournament_platform.app.pages.public_board_readonly import render_public_board_readonly
            render_public_board_readonly()
        except Exception as e:
            st.error(f"Failed to render public board: {e}")
        st.stop()

    render_sidebar_logo()

    if "active_tournament_id" not in st.session_state:
        st.session_state["active_tournament_id"] = None

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

        st.session_state["user_role"] = user_role

        # Navigation

        # Multi-page navigation using st.navigation (Streamlit 1.35+)
        # Use absolute paths based on this file's location so they work from any CWD
        app_dir = os.path.dirname(__file__)

        # Build navigation with consolidated sections (reduced top-level pages)
        app_dir = os.path.dirname(__file__)

        # Home section
        home_pages = [
            st.Page(os.path.join(app_dir, "pages", "home.py"), title="TT Tournament Platform", icon=PAGE_ICONS["home"]),
        ]

        # Tournament (consolidated setup, participants, bracket, results)
        tournament_pages = [
            st.Page(os.path.join(app_dir, "pages", "events_draws.py"), title="Tournament", icon=PAGE_ICONS["tournament"]),
        ]

        # Insights (Dashboard + AI Assistant)
        insights_pages = [
            st.Page(os.path.join(app_dir, "pages", "dashboard.py"), title="Dashboard", icon=PAGE_ICONS["dashboard"]),
            st.Page(os.path.join(app_dir, "pages", "ai_assistant.py"), title="AI Assistant (Experimental)", icon=PAGE_ICONS["ai_assistant"]),
        ]

        # Admin (visible to admin and operator users)
        admin_pages = []
        if user_role in ("admin", "operator"):
            admin_pages.append(
                st.Page(os.path.join(app_dir, "pages", "admin.py"), title="Admin / Operator", icon=PAGE_ICONS["admin"])
            )

        # Experimental extras (kept behind debug flag)
        experimental_pages = []
        if settings.DEBUG_UI_ENABLED or user_role == "admin":
            experimental_pages.extend([
                st.Page(os.path.join(app_dir, "pages", "voice_scorekeeper.py"), title="Voice Scorekeeper", icon=PAGE_ICONS["voice_scorekeeper"]),
                st.Page(os.path.join(app_dir, "pages", "video_scorekeeper.py"), title="Video Scorekeeper", icon=PAGE_ICONS["video_scorekeeper"]),
                st.Page(os.path.join(app_dir, "pages", "dataset_catalog.py"), title="Dataset Catalog", icon=PAGE_ICONS["dataset_catalog"]),
                st.Page(os.path.join(app_dir, "pages", "coaching_lab.py"), title="Coaching Lab", icon=PAGE_ICONS["coaching_lab"]),
                st.Page(os.path.join(app_dir, "pages", "experiment_dashboard.py"), title="Experiment Dashboard", icon=PAGE_ICONS["experiment_dashboard"]),
            ])

        # Combine into final navigation
        all_pages = [
            *home_pages,
            *tournament_pages,
            *insights_pages,
            *admin_pages,
            *experimental_pages,
        ]

        navigation = st.navigation(all_pages)
        navigation.run()

        # Show user info and logout button in sidebar
        with st.sidebar:
            render_active_context_bar()
            st.divider()
            st.markdown(
                f"""
                <div style="padding: 0.25rem 0.25rem 0.5rem; margin-bottom: 0.5rem;">
                    <small style="opacity:0.7; font-size:10px; color:#B0B3B8;">{BRAND['tagline']}</small>
                </div>
                <hr style="border: none; border-top: 1px solid #333436; margin: 0 0 0.75rem;" />
                """,
                unsafe_allow_html=True,
            )
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


if __name__ == "__main__":
    main()
