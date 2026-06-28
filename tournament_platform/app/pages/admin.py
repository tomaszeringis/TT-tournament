import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import importlib.metadata
from datetime import datetime, timezone
from sqlalchemy import text

from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus, engine
from tournament_platform.services.player_stats import get_player_statistics
from tournament_platform.services.test_data_cleanup_service import (
    preview_test_data_cleanup,
    cleanup_test_data,
)
from tournament_platform.app.utils import (
    render_interactive_table,
    api_request,
    render_database_connection_error,
    render_status_badge,
    format_match_label,
)
from tournament_platform.config import settings


@st.cache_data(ttl=30, show_spinner="Loading database summary...")
def get_database_summary():
    """Get cached database summary counts."""
    db = SessionLocal()
    try:
        return {
            "player_count": db.query(Player).count(),
            "match_count": db.query(Match).count(),
            "tournament_count": db.query(Tournament).count(),
            "completed_matches": db.query(Match).filter(Match.status == MatchStatus.completed).count(),
        }
    finally:
        db.close()


@st.cache_data(ttl=60, show_spinner="Loading player statistics...")
def get_cached_player_statistics():
    """Get cached player statistics DataFrame."""
    db = SessionLocal()
    try:
        stats = get_player_statistics(db)
        if stats:
            return pd.DataFrame(stats)
        return pd.DataFrame()
    finally:
        db.close()


@st.cache_data(ttl=30, show_spinner="Loading tournament list...")
def get_cached_tournaments():
    """Get cached list of tournament names."""
    db = SessionLocal()
    try:
        return [t.name for t in db.query(Tournament).all()]
    finally:
        db.close()


st.title("👨‍💼 Admin Panel")
st.space("medium")

try:
    db = SessionLocal()
except Exception as e:
    render_database_connection_error(e)

# Admin dashboard tabs
admin_tabs = st.tabs(["Database Overview", "Match Management", "System Health", "Danger Zone"])

# Tab 1: Database Overview
with admin_tabs[0]:
    st.subheader("📊 Database Overview")
    
    # Use cached summary
    summary = get_database_summary()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        ui.metric_card(title="Total Players", content=str(summary["player_count"]), key="admin_p_count")
    
    with col2:
        ui.metric_card(title="Total Matches", content=str(summary["match_count"]), key="admin_m_count")
    
    with col3:
        ui.metric_card(title="Total Tournaments", content=str(summary["tournament_count"]), key="admin_t_count")
    
    with col4:
        ui.metric_card(title="Completed Matches", content=str(summary["completed_matches"]), key="admin_c_count")
    
    st.space("medium")
    
    # Detailed statistics
    st.write("**Detailed Player Statistics:**")
    
    # Use cached player statistics
    player_df = get_cached_player_statistics()
    if not player_df.empty:
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
        # Use cached tournament list
        tournament_names = get_cached_tournaments()
        tournament_filter = st.selectbox(
            "Filter by Tournament",
            ["All"] + tournament_names
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
        return True, "Connected"
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
        return True, f"Running - {status}"
    return False, "Unavailable"

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
    teams_configured, teams_status = check_teams_webhook()
    azure_configured, azure_status = check_azure_config()
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        db_icon = "✅" if db_healthy else "❌"
        st.metric("Database Status", f"{db_icon} {'Connected' if db_healthy else 'Disconnected'}", delta=db_status)
        
        api_icon = "✅" if api_healthy else "❌"
        st.metric("API Status", f"{api_icon} {'Running' if api_healthy else 'Unavailable'}", delta=api_status)
    
    with col2:
        # Use lightweight AI health check instead of instantiating AIEngine
        try:
            from tournament_platform.services.ai_facade import get_ai_health
            ai_health = get_ai_health()
            ollama_icon = "✅" if ai_health.available else "❌"
            ollama_status = f"Model: {ai_health.model_name}" if ai_health.model_name else "Unavailable"
            if ai_health.error:
                ollama_status = f"Error: {ai_health.error[:30]}"
            st.metric("Ollama Status", f"{ollama_icon} {'Connected' if ai_health.available else 'Disconnected'}", delta=ollama_status)
            
            retrieval_icon = "✅" if ai_health.retrieval_available else "⚪"
            st.metric("Rules Retrieval", f"{retrieval_icon} {'Available' if ai_health.retrieval_available else 'Unavailable'}")
        except Exception as e:
            st.metric("Ollama Status", "❌ Disconnected", delta="Error checking status")
            st.metric("Rules Retrieval", "⚪ Unavailable")
    
    st.space("medium")
    st.write("**System Information**")
    
    # Use lightweight AI health for model info (no heavy AIEngine instantiation)
    try:
        from tournament_platform.services.ai_facade import get_ai_health
        ai_health = get_ai_health()
        model_display = ai_health.model_name or settings.OLLAMA_MODEL
    except Exception:
        model_display = settings.OLLAMA_MODEL
    
    system_info = {
        "Database Type": "SQLite",
        "AI Model": model_display,
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

# Tab 4: Danger Zone
with admin_tabs[3]:
    st.subheader(" Danger Zone")
    st.warning(
        "Actions in this section are destructive and cannot be undone. "
        "Only test/demo/generated data will be affected."
    )
    st.space("medium")

    with st.expander("Remove test/demo generated data", expanded=False):
        st.markdown(
            """
            This tool removes **only** records that are clearly identified as test, demo, or generated data:

            - Tournaments whose name or description matches test/demo patterns
            - Matches belonging to those tournaments
            - Announcements linked to those tournaments or matches
            - Audit logs related to those entities
            - Players whose name/email matches test patterns **and** who are not connected to any real (non-test) tournament or match
            - Rating history for those players
            - Venue tables that are clearly marked as test data and are not used by real matches

            **Real tournaments, real players, real matches, and normal venue tables are never deleted.**
            """
        )
        st.space("small")

        # Preview button
        if st.button("Preview cleanup", key="preview_cleanup_btn"):
            try:
                db = SessionLocal()
                preview = preview_test_data_cleanup(db)
                db.close()

                total_items = sum(v["count"] for v in preview.values())
                if total_items == 0:
                    st.info("No test/demo data found. Nothing to delete.")
                else:
                    st.write(f"**Found {total_items} record(s) that would be deleted:**")
                    for category, data in preview.items():
                        if data["count"] > 0:
                            st.write(f"**{category.replace('_', ' ').title()}:** {data['count']} record(s)")
                            for sample in data["samples"][:5]:
                                if "name" in sample:
                                    st.write(f"  - ID {sample['id']}: {sample['name']}")
                                elif "message" in sample:
                                    st.write(f"  - ID {sample['id']}: {sample['message']}")
                                elif "player1" in sample:
                                    st.write(
                                        f"  - ID {sample['id']}: {sample['player1']} vs {sample['player2']} "
                                        f"(tournament {sample['tournament_id']})"
                                    )
                                elif "action" in sample:
                                    st.write(
                                        f"  - ID {sample['id']}: {sample['action']} on {sample['entity_type']} {sample['entity_id']}"
                                    )
                                else:
                                    st.write(f"  - ID {sample['id']}")
                            if data["count"] > 5:
                                st.write(f"  ... and {data['count'] - 5} more")
            except Exception as e:
                st.error(f"Failed to generate preview: {e}")

        st.space("medium")

        # Confirmation controls
        confirm_checkbox = st.checkbox(
            "I understand this permanently deletes test/demo data.",
            key="confirm_cleanup_checkbox",
        )
        confirm_text = st.text_input(
            'Type "DELETE TEST DATA" to confirm:',
            key="confirm_cleanup_text",
            placeholder="DELETE TEST DATA",
        )

        delete_disabled = not (confirm_checkbox and confirm_text == "DELETE TEST DATA")

        if st.button(
            "Remove test/demo data",
            key="execute_cleanup_btn",
            type="primary",
            disabled=delete_disabled,
        ):
            try:
                db = SessionLocal()
                result = cleanup_test_data(
                    db,
                    confirmed=True,
                    confirmation_text=confirm_text,
                )
                db.close()

                st.success("Test/demo data removed successfully!")
                counts = result.get("deleted_counts", {})
                for table, count in counts.items():
                    if count > 0:
                        st.write(f"- **{table}**: {count} record(s) deleted")
                st.rerun()
            except ValueError as e:
                st.error(f"Cleanup aborted: {e}")
            except Exception as e:
                st.error(f"Cleanup failed: {e}")

    # AI Testing Section
    st.divider()
    st.subheader("🧪 AI Testing")
    st.caption("Test the AI connection and ask questions. This is for admin verification only.")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("🔌 Test AI Connection", key="test_ai_connection"):
            with st.status("Testing AI connection...", expanded=False) as status:
                try:
                    from tournament_platform.services.ai_facade import get_ai_health
                    health = get_ai_health()
                    if health.available:
                        status.update(label="Connection successful", state="complete", expanded=False)
                        st.success(f"✅ AI is working! Model: {health.model_name}")
                    else:
                        status.update(label="Connection failed", state="error", expanded=False)
                        st.error("❌ AI is not connected")
                except Exception as e:
                    status.update(label="Error occurred", state="error", expanded=False)
                    st.error(f"❌ AI connection error: {e}")
    
    with col2:
        test_question = st.text_input(
            "Test question:",
            key="test_ai_question",
            placeholder="e.g., What are the tournament rules?"
        )
        if st.button("❓ Ask Test Question", key="ask_test_question") and test_question:
            with st.status("Getting AI response...", expanded=False) as status:
                try:
                    from tournament_platform.services.ai_facade import answer_rules_question
                    result = answer_rules_question(test_question)
                    status.update(label="Response received", state="complete", expanded=False)
                    st.info(f"**Answer:** {result.answer}")
                except Exception as e:
                    status.update(label="Error occurred", state="error", expanded=False)
                    st.error(f"❌ Error: {e}")

db.close()
