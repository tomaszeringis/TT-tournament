import logging
import os
import requests
from typing import Optional, Any, Union, List, Dict
import streamlit as st
import pandas as pd
import streamlit_shadcn_ui as ui

from tournament_platform.config import settings
from tournament_platform.models import MatchStatus, DATABASE_URL, DATABASE_PATH

logger = logging.getLogger(__name__)


# ============================================================================
# Status Badge Helpers
# ============================================================================

def get_status_badge_variant(status: str) -> str:
    """
    Get the badge variant for a match status.

    Args:
        status: Match status string (pending, active, completed)

    Returns:
        Badge variant string for streamlit_shadcn_ui
    """
    if status == "completed":
        return "default"
    elif status == "active":
        return "outline"
    return "secondary"


def render_status_badge(status: str, key: Optional[str] = None) -> None:
    """
    Render a status badge with consistent styling.

    Args:
        status: Match status string (pending, active, completed)
        key: Optional unique key for Streamlit widget
    """
    variant = get_status_badge_variant(status)
    ui.badges(badge_list=[(status, variant)], key=key)


# ============================================================================
# Database Error Handling
# ============================================================================

def render_database_error(error: Exception, context: str = "database") -> None:
    """
    Render a standardized database error message with debug information.

    Args:
        error: The exception that occurred
        context: User-friendly context description (e.g., "dashboard data", "tournament")
    """
    st.error(f"❌ Unable to load {context}. The database may be unavailable.")
    with st.expander("🔍 Debug Information"):
        st.write(f"**Error:** `{error}`")
        st.write(f"**Database URL:** `{DATABASE_URL}`")
        st.write(f"**Database Path:** `{DATABASE_PATH}`")
        try:
            st.write(f"**File Exists:** `{os.path.exists(DATABASE_PATH)}`")
        except Exception:
            st.write("**File Exists:** `Unable to check`")
        try:
            st.write(f"**Current Working Directory:** `{os.getcwd()}`")
        except Exception:
            st.write("**Current Working Directory:** `Unable to determine`")
    st.info("Please ensure the database file is accessible and not locked by another process.")


def render_database_connection_error(error: Exception) -> None:
    """
    Render a standardized database connection error message.

    Args:
        error: The exception that occurred
    """
    st.error(f"❌ Database connection error: {error}")
    with st.expander("🔍 Debug Information"):
        st.write(f"**Database URL:** `{DATABASE_URL}`")
        st.write(f"**Database Path:** `{DATABASE_PATH}`")
        try:
            st.write(f"**File Exists:** `{os.path.exists(DATABASE_PATH)}`")
        except Exception:
            st.write("**File Exists:** `Unable to check`")
        try:
            st.write(f"**Current Working Directory:** `{os.getcwd()}`")
        except Exception:
            st.write("**Current Working Directory:** `Unable to determine`")
    st.info("Please ensure the database file is accessible and not locked by another process.")
    st.stop()


# ============================================================================
# Match Display Helpers
# ============================================================================

def format_match_label(player1: Optional[str], player2: Optional[str]) -> str:
    """
    Format a match label showing two players.

    Args:
        player1: First player name or None
        player2: Second player name or None

    Returns:
        Formatted match label string
    """
    p1 = player1 or "TBD"
    p2 = player2 or "TBD"
    return f"{p1} vs {p2}"


def format_match_score(score: Optional[str]) -> str:
    """
    Format a match score for display.

    Args:
        score: Match score string or None

    Returns:
        Formatted score string
    """
    return score or "-"


# ============================================================================
# Player Display Helpers
# ============================================================================

def format_player_label(name: str, rating: Optional[int] = None) -> str:
    """
    Format a player label with optional rating.

    Args:
        name: Player name
        rating: Optional player rating

    Returns:
        Formatted player label string
    """
    if rating is not None:
        return f"{name} (Rating: {rating})"
    return name


# ============================================================================
# Metric Card Helpers
# ============================================================================

def render_metric_cards(metrics: List[Dict[str, str]], columns: int = 4) -> None:
    """
    Render a row of metric cards.

    Args:
        metrics: List of dicts with 'title', 'content', and optional 'description' keys
        columns: Number of columns to use (default: 4)
    """
    cols = st.columns(columns)
    for i, metric in enumerate(metrics):
        with cols[i % columns]:
            ui.metric_card(
                title=metric.get("title", ""),
                content=str(metric.get("content", "")),
                description=metric.get("description", ""),
                key=f"metric_{i}"
            )


# ============================================================================
# Existing Functions
# ============================================================================

def render_interactive_table(
    df: pd.DataFrame,
    title: Optional[str] = None,
    searchable: bool = True,
    sortable: bool = True,
    height: Optional[int] = None,
) -> None:
    """
    Render an interactive table using native Streamlit components.

    Uses st.dataframe for optimal theme compatibility, accessibility, and responsiveness.
    Provides built-in sorting and column-based filtering.

    Args:
        df: DataFrame to display.
        title: Optional title to display above the table.
        searchable: Enable search functionality (default: True).
        sortable: Enable column sorting (default: True). Note: st.dataframe always
                  provides sorting; this parameter is for future extensibility.
        height: Optional height in pixels. If None, uses Streamlit's responsive default.
    """
    if df is None or df.empty:
        st.info("No data to display.")
        return

    if title:
        st.markdown(f"**{title}**")

    # Use st.dataframe for native Streamlit table with built-in features
    # - Full column sorting (click column headers)
    # - Column filtering (click filter icon next to column names)
    # - Responsive design (adapts to container width)
    # - Theme-aware styling (light/dark mode compatible)
    # - Keyboard navigation and screen reader support
    if height is not None:
        st.dataframe(
            df,
            use_container_width=True,
            height=height,
            hide_index=True,
        )
    else:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


def api_request(
    method: str,
    endpoint: str,
    error_context: str = "API request",
    timeout: float = 10.0,
    parse_json: bool = False,
    **kwargs,
) -> Optional[Union[requests.Response, Any]]:
    """
    Make an API request with centralized error handling.

    Uses the configured API_BASE_URL, adds a timeout, and handles
    connection errors, timeouts, non-2xx responses, and invalid JSON.

    Shows user-friendly st.error messages on failure and logs full
    details for developers.

    Args:
        method: HTTP method (get, post, put, delete, etc.)
        endpoint: API endpoint path (e.g., "/health")
        error_context: User-friendly context for error messages
        timeout: Request timeout in seconds
        parse_json: If True, parse and return JSON response body
        **kwargs: Additional arguments passed to requests.request

    Returns:
        Response object if parse_json=False, parsed JSON if parse_json=True,
        or None on failure.
    """
    url = f"{settings.API_BASE_URL}{endpoint}"
    kwargs.setdefault("timeout", timeout)

    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()

        if parse_json:
            try:
                return response.json()
            except (requests.exceptions.JSONDecodeError, ValueError) as e:
                logger.error(
                    "Invalid JSON response during %s: %s | body: %s",
                    error_context,
                    url,
                    response.text[:200],
                    exc_info=True,
                )
                st.error("❌ Received an invalid response from the server.")
                return None

        return response

    except requests.exceptions.ConnectionError:
        logger.error("Connection error during %s: %s", error_context, url, exc_info=True)
        st.error("❌ Cannot connect to the server. Please check your network connection.")
    except requests.exceptions.Timeout:
        logger.error(
            "Timeout during %s: %s (timeout=%ss)", error_context, url, timeout, exc_info=True
        )
        st.error("❌ Request timed out. The server is taking too long to respond.")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "unknown"
        logger.error(
            "HTTP %s during %s: %s | response: %s",
            status,
            error_context,
            url,
            (e.response.text[:200] if e.response is not None else "no response"),
            exc_info=True,
        )
        st.error(f"❌ Server returned an error (status: {status}).")
    except Exception as e:
        logger.error("Unexpected error during %s: %s | %s", error_context, url, e, exc_info=True)
        st.error("❌ An unexpected error occurred. Please try again.")

    return None
