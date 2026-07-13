"""
Schedule / Calendar Board

A calendar view of tournament matches for planning and scheduling.
Shows matches organized by date/time in a grid format.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from tournament_platform.models import SessionLocal
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_public_schedule,
)
from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.app.components.tour import render_tour


@st.cache_data(ttl=60, show_spinner="Loading tournaments...")
def load_tournaments() -> List[Dict[str, Any]]:
    """Load all tournaments from the database."""
    db = SessionLocal()
    try:
        return list_tournaments(db)
    finally:
        db.close()


@st.cache_data(ttl=30, show_spinner="Loading schedule...")
def load_schedule(tournament_id: int) -> List[Dict[str, Any]]:
    """Load matches for a tournament."""
    db = SessionLocal()
    try:
        return get_public_schedule(db, tournament_id=tournament_id)
    finally:
        db.close()


def render_schedule_tab(tournament_id: int, start_date, days_ahead: int) -> None:
    """Render the schedule/calendar board content for a tournament.

    This is a ``set_page_config``-free renderer suitable for embedding inside
    other pages (e.g. as an Admin tab). It expects the caller to provide the
    tournament id and date-range parameters.
    """
    selected_id = tournament_id

    # Load schedule
    try:
        matches = load_schedule(selected_id)
    except Exception as e:
        st.error(f"Failed to load schedule: {e}")
        return

    if not matches:
        st.info("No matches scheduled yet. Generate a tournament bracket first.")
        return

    # Filter matches by date range
    end_date = start_date + timedelta(days=days_ahead)
    filtered_matches = []
    for m in matches:
        scheduled = m.get("scheduled_time")
        if scheduled:
            try:
                match_date = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).date()
                if start_date <= match_date <= end_date:
                    filtered_matches.append(m)
            except Exception:
                pass

    if not filtered_matches:
        st.info(f"No matches scheduled between {start_date} and {end_date}.")
        return

    # Group matches by date
    matches_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for m in filtered_matches:
        scheduled = m.get("scheduled_time")
        if scheduled:
            try:
                match_date = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).date()
                date_str = match_date.strftime("%Y-%m-%d")
                if date_str not in matches_by_date:
                    matches_by_date[date_str] = []
                matches_by_date[date_str].append(m)
            except Exception:
                pass

    # Sort dates
    sorted_dates = sorted(matches_by_date.keys())

    # Display matches by date
    for date_str in sorted_dates:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_name = date_obj.strftime("%A")
        st.subheader(f"{day_name}, {date_str}")

        day_matches = matches_by_date[date_str]
        # Sort by time
        day_matches.sort(key=lambda m: m.get("scheduled_time", ""))

        for m in day_matches:
            p1 = m.get("player1", "?")
            p2 = m.get("player2", "?")
            scheduled = m.get("scheduled_time", "")
            time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"
            location = m.get("location", "No table")
            call_status = m.get("call_status", "not_called")
            status = m.get("status", "pending")

            # Status color
            if status == "completed":
                status_icon = "🟢"
            elif call_status == "active":
                status_icon = "🔴"
            elif call_status == "called":
                status_icon = "🟡"
            else:
                status_icon = "🔵"

            with st.container(border=True):
                col_time, col_match, col_table, col_status = st.columns([1, 3, 2, 1])

                with col_time:
                    st.markdown(f"**{time_str}**")

                with col_match:
                    st.markdown(f"{p1} vs {p2}")

                with col_table:
                    st.markdown(f"📍 Table {location}")

                with col_status:
                    st.markdown(f"{status_icon} {call_status.title()}")

    # Export option
    st.divider()
    st.subheader("📤 Export Schedule")

    if st.button("Download as CSV", key=f"schedule_download_csv_{selected_id}"):
        # Create CSV data
        csv_data = []
        for m in filtered_matches:
            csv_data.append({
                "Date": m.get("scheduled_time", "").split("T")[0] if m.get("scheduled_time") else "",
                "Time": m.get("scheduled_time", "").split("T")[1][:5] if m.get("scheduled_time") else "",
                "Player 1": m.get("player1", ""),
                "Player 2": m.get("player2", ""),
                "Table": m.get("location", ""),
                "Status": m.get("call_status", ""),
            })

        df = pd.DataFrame(csv_data)
        csv = df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"tournament_{selected_id}_schedule.csv",
            mime="text/csv",
            key=f"schedule_download_csv_btn_{selected_id}",
        )


def render_schedule_board() -> None:
    """Render the standalone schedule/calendar board page.

    Thin wrapper that owns ``set_page_config`` + the tournament selector and
    delegates the actual rendering to :func:`render_schedule_tab`. Retained so
    the module stays runnable as a standalone page / deep-link even though it is
    no longer registered in the navigation.
    """
    st.set_page_config(
        page_title="LIT_IT Schedule Board",
        page_icon="📅",
        layout="wide",
    )

    apply_global_styles()

    from tournament_platform.app.components.page_header import render_page_header

    render_page_header(
        title="LIT_IT Schedule Board",
        description="View and plan tournament matches by date/time",
        icon="📅",
    )
    render_tour("schedule_board")

    # Load tournaments
    try:
        tournaments = load_tournaments()
    except Exception as e:
        st.error(f"Failed to load tournaments: {e}")
        st.stop()

    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        st.stop()

    # Tournament selector
    tournament_options = {t["name"]: t["id"] for t in tournaments}
    selected_name = st.selectbox(
        "Select Tournament",
        options=list(tournament_options.keys()),
        index=0,
        key="schedule_tournament_select",
    )
    selected_id = tournament_options[selected_name]

    # Date range selector
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Start Date",
            value=datetime.now(timezone.utc).date(),
            key="schedule_start_date",
        )
    with col2:
        days_ahead = st.number_input(
            "Days to Show",
            min_value=1,
            max_value=30,
            value=7,
            key="schedule_days_ahead",
        )

    render_schedule_tab(selected_id, start_date, days_ahead)


if __name__ == "__main__":
    render_schedule_board()