import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import importlib.metadata
from datetime import datetime, timezone
from sqlalchemy import text

from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus, DATABASE_PATH, engine
from tournament_platform.services.ai_engine import AIEngine
from tournament_platform.services.player_stats import get_player_statistics
from tournament_platform.app.utils import (
    render_interactive_table,
    api_request,
    render_database_connection_error,
    render_status_badge,
    format_match_label,
)
from tournament_platform.config import settings

st.title("👨‍💼 Admin Panel")
st.space("medium")

try:
    db = SessionLocal()
except Exception as e:
    render_database_connection_error(e)

# Admin dashboard tabs
admin_tabs = st.tabs(["Database Overview", "Match Management", "System Health"])

# Tab 1: Database Overview
with admin_tabs[0]:
    st.subheader("📊 Database Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        player_count = db.query(Player).count()
        ui.metric_card(title="Total Players", content=str(player_count), key="admin_p_count")

    with col2:
        match_count = db.query(Match).count()
        ui.metric_card(title="Total Matches", content=str(match_count), key="admin_m_count")

    with col3:
        tournament_count = db.query(Tournament).count()
        ui.metric_card(title="Total Tournaments", content=str(tournament_count), key="admin_t_count")

    with col4:
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()
        ui.metric_card(title="Completed Matches", content=str(completed_matches), key="admin_c_count")

    st.space("medium")

    # Detailed statistics
    st.write("**Detailed Player Statistics:**")

    # Use optimized aggregate query for player statistics
    player_stats = get_player_statistics(db)
    if player_stats:
        player_df = pd.DataFrame(player_stats)

        # itables for player stats
        render_interactive_table(player_df.drop(columns=["ID"]))
    else:
        st.info("No players found in database")

# Tab 2: Match Management
with admin_tabs[1]:
    st.subheader("🎾 Match Management")

    # Filter matches
    col1, col2 = st.columns([1, 1])

    with col1:
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "pending", "active", "completed"]
        )

    with col2:
        tournament_filter = st.selectbox(
            "Filter by Tournament",
            ["All"] + [t.name for t in db.query(Tournament).all()]
        )

    # Get filtered matches
    query = db.query(Match)

    if status_filter != "All":
        query = query.filter(Match.status == MatchStatus[status_filter])

    if tournament_filter != "All":
        tournament = db.query(Tournament).filter(Tournament.name == tournament_filter).first()
        if tournament:
            query = query.filter(Match.tournament_id == tournament.id)

    matches = query.all()

    if matches:
        match_data = []
        st.write("**Recent Activity:**")
        # Show top 10 matches with badges for status
        for m in matches[:10]:
            m_cols = st.columns([4, 1])
            with m_cols[0]:
                st.write(f"{m.player1} vs {m.player2} | Tournament: {m.tournament.name if m.tournament else 'N/A'}")
            with m_cols[1]:
                render_status_badge(m.status.value, key=f"admin_status_{m.id}")
        
        st.space("medium")
        for m in matches:
            match_data.append({
                "ID": m.id,
                "Player 1": m.player1,
                "Player 2": m.player2,
                "Winner": m.winner or "TBD",
                "Score": m.score or "-",
                "Status": m.status.value if m.status else "pending",
                "Tournament": m.tournament.name if m.tournament else "N/A"
            })

        match_df = pd.DataFrame(match_data)

        # itables for matches
        render_interactive_table(match_df.drop(columns=["ID"]))
    else:
        st.info("No matches found with current filters")

    # Actions
    st.space("medium")
    st.write("**Quick Actions:**")

    col1, col2 = st.columns([1, 1])

    with col1:
        if ui.button("🔄 Refresh Data", key="admin_refresh_btn"):
            st.rerun()

    with col2:
        if ui.button("🗑️ Clear All Cache", key="admin_clear_btn"):
            st.cache_data.clear()
            st.toast("Cache cleared!", icon="✅")

# Helper functions for system health checks
def get_package_version(package_name: str) -> str:
    """Get the installed version of a package, or 'unknown' if not found."""
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"

def check_database_health() -> tuple[bool, str]:
    """Check if database is accessible and return status with details."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, f"Connected ({DATABASE_PATH})"
    except Exception as e:
        return False, f"Error: {str(e)[:50]}"

def check_api_health() -> tuple[bool, str]:
    """Check if FastAPI health endpoint is responding."""
    response = api_request(
        "get",
        "/health",
        error_context="API health check",
        timeout=3.0,
        parse_json=True,
    )
    if response is not None:
        status = response.get("status", "unknown")
        return True, f"Running ({settings.API_BASE_URL}) - {status}"
    return False, f"Unavailable ({settings.API_BASE_URL})"

def check_ollama_health() -> tuple[bool, str]:
    """Check if Ollama is running and model is available."""
    try:
        import ollama
        response = ollama.list()
        if hasattr(response, 'models'):
            model_names = [m.model for m in response.models]
        else:
            model_names = [m.get('name') for m in response.get('models', [])]
        
        if settings.OLLAMA_MODEL in model_names:
            return True, f"Connected - {settings.OLLAMA_MODEL}"
        return True, f"Connected - model not found (configured: {settings.OLLAMA_MODEL})"
    except Exception as e:
        return False, f"Disconnected - {str(e)[:50]}"

def check_teams_webhook() -> tuple[bool, str]:
    """Check if Teams webhook is configured."""
    if settings.TEAMS_WEBHOOK_URL:
        return True, "Configured"
    return False, "Not configured"

def check_azure_config() -> tuple[bool, str]:
    """Check if Azure integration is configured."""
    if settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET:
        return True, "Configured"
    return False, "Not configured"

# Tab 3: System Health
with admin_tabs[2]:
    st.subheader("💚 System Health")

    # Perform real health checks
    db_healthy, db_status = check_database_health()
    api_healthy, api_status = check_api_health()
    ollama_healthy, ollama_status = check_ollama_health()
    teams_configured, teams_status = check_teams_webhook()
    azure_configured, azure_status = check_azure_config()

    col1, col2 = st.columns([1, 1])

    with col1:
        db_icon = "✅" if db_healthy else "❌"
        st.metric("Database Status", f"{db_icon} {'Connected' if db_healthy else 'Disconnected'}", delta=db_status)
        
        api_icon = "✅" if api_healthy else "❌"
        st.metric("API Status", f"{api_icon} {'Running' if api_healthy else 'Unavailable'}", delta=api_status)

    with col2:
        ollama_icon = "✅" if ollama_healthy else "❌"
        st.metric("Ollama Status", f"{ollama_icon} {'Connected' if ollama_healthy else 'Disconnected'}", delta=ollama_status)
        
        teams_icon = "✅" if teams_configured else "⚪"
        st.metric("Teams Webhook", f"{teams_icon} {'Configured' if teams_configured else 'Not configured'}", delta=teams_status)

    st.space("medium")
    st.write("**System Information**")

    # Get current AI engine to show actual model
    try:
        ai_engine = AIEngine()
        current_model = ai_engine.model
    except Exception:
        current_model = settings.OLLAMA_MODEL

    system_info = {
        "Database Type": "SQLite",
        "Database Path": str(DATABASE_PATH),
        "AI Model": current_model,
        "Ollama Host": settings.OLLAMA_HOST,
        "Streamlit Version": get_package_version("streamlit"),
        "FastAPI Version": get_package_version("fastapi"),
        "SQLAlchemy Version": get_package_version("sqlalchemy"),
        "ChromaDB Version": get_package_version("chromadb"),
    }

    info_df = pd.DataFrame(list(system_info.items()), columns=["Parameter", "Value"])
    st.table(info_df)

    st.space("medium")
    st.write("**Optional Integrations**")

    integrations = {
        "Teams Webhook": "✅ Configured" if teams_configured else "⚪ Not configured",
        "Azure Calendar": "✅ Configured" if azure_configured else "⚪ Not configured",
    }

    integrations_df = pd.DataFrame(list(integrations.items()), columns=["Integration", "Status"])
    st.table(integrations_df)

    st.space("medium")
    st.write("**Last Updated**")
    st.caption(f"System health checked at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

db.close()
