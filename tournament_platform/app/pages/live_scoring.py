"""
Live Scoring Page (Compatibility Wrapper)

This page is deprecated. Use the Voice Scorekeeper page instead, which now includes
game-by-game scoring functionality.

This file is kept for backward compatibility and redirects users to the Voice Scorekeeper.
"""

import streamlit as st

# Redirect to Voice Scorekeeper
st.switch_page("pages/voice_scorekeeper.py")


# ============================================================================
# Session State Initialization
# ============================================================================

if 'live_scoring_match_id' not in st.session_state:
    st.session_state.live_scoring_match_id = None
if 'live_scoring_tournament_id' not in st.session_state:
    st.session_state.live_scoring_tournament_id = None
if 'live_scoring_p1_id' not in st.session_state:
    st.session_state.live_scoring_p1_id = None
if 'live_scoring_p1_name' not in st.session_state:
    st.session_state.live_scoring_p1_name = None
if 'live_scoring_p2_id' not in st.session_state:
    st.session_state.live_scoring_p2_id = None
if 'live_scoring_p2_name' not in st.session_state:
    st.session_state.live_scoring_p2_name = None


# ============================================================================
# Helper Functions
# ============================================================================

@st.cache_data(ttl=60)
def fetch_tournaments() -> List[Dict]:
    """Return all tournaments as plain dicts for selectbox options."""
    db = SessionLocal()
    try:
        tournaments = db.query(Tournament).order_by(Tournament.name).all()
        return [
            {"id": t.id, "name": t.name, "type": t.tournament_type.value if t.tournament_type else None}
            for t in tournaments
        ]
    finally:
        db.close()


@st.cache_data(ttl=30)
def fetch_matches(tournament_id: int, statuses: Optional[List[str]] = None) -> List[Dict]:
    """Fetch scorable matches for a tournament via the API."""
    params = {"limit": 100}
    if statuses:
        params["statuses"] = ",".join(statuses)
    response = api_client.get(
        f"/api/tournaments/{tournament_id}/matches/active",
        params=params,
    )
    if response and isinstance(response, dict):
        return response.get("matches", [])
    return []


def format_match_label(match: Dict) -> str:
    """Format a match dict into a human-readable label for the selector."""
    parts = []
    if match.get("round_number") is not None:
        parts.append(f"Round {match['round_number']}")
    if match.get("location"):
        parts.append(f"Table {match['location']}")
    p1 = match.get("player1_name") or "TBD"
    p2 = match.get("player2_name") or "TBD"
    parts.append(f"{p1} vs {p2}")
    status = match.get("status", "unknown")
    parts.append(status)
    return " | ".join(parts)


def validate_score(score_a: int, score_b: int) -> Optional[str]:
    """
    Validate match scores.
    
    Returns an error message if invalid, None if valid.
    """
    if score_a < 0 or score_b < 0:
        return "Scores cannot be negative"
    if score_a > 10 or score_b > 10:
        return "Scores cannot exceed 10"
    if score_a == score_b:
        return "Scores cannot be equal - there must be a winner"
    return None


def submit_match_result(match_id: int, score: str, winner: str) -> bool:
    """
    Submit match result via the API.
    
    Returns True if successful, False otherwise.
    """
    response = api_client.report_match_legacy(match_id, score, winner)
    return response is not None


# ============================================================================
# Page UI
# ============================================================================

st.title("📊 Live Scoring")
st.caption("Select an active match and enter the score manually.")

# Tournament selector
tournaments = fetch_tournaments()
if not tournaments:
    st.info("No tournaments found. Create a tournament first in the Events & Draws page.")
    st.stop()

tournament_options = {t["name"]: t["id"] for t in tournaments}
selected_tournament_name = st.selectbox(
    "Select Tournament",
    options=list(tournament_options.keys()),
    key="live_scoring_tournament",
)

tournament_id = tournament_options[selected_tournament_name]
st.session_state.live_scoring_tournament_id = tournament_id

# Match selector
matches = fetch_matches(tournament_id, statuses=["active", "pending"])
if not matches:
    st.info("No active or pending matches found for this tournament.")
    st.stop()

# Filter out incomplete matches (missing players)
scorable_matches = [m for m in matches if not m.get("incomplete", False)]
if not scorable_matches:
    st.info("No scorable matches found (all matches may be missing players).")
    st.stop()

match_labels = [format_match_label(m) for m in scorable_matches]
selected_match_label = st.selectbox(
    "Select Match",
    options=match_labels,
    key="live_scoring_match",
)

# Find selected match
selected_match = None
for i, label in enumerate(match_labels):
    if label == selected_match_label:
        selected_match = scorable_matches[i]
        break

if not selected_match:
    st.error("Could not find selected match")
    st.stop()

# Display match info
st.divider()
col_p1, col_p2 = st.columns(2)
with col_p1:
    st.markdown(f"**{selected_match.get('player1_name', 'TBD')}**")
with col_p2:
    st.markdown(f"**{selected_match.get('player2_name', 'TBD')}**")

# Score entry form
st.divider()
st.subheader("Enter Score")

with st.form("live_scoring_form"):
    score_col1, score_col2 = st.columns(2)
    
    with score_col1:
        score_a = st.number_input(
            "Player 1 Score",
            min_value=0,
            max_value=10,
            value=0,
            key="live_score_a",
        )
    
    with score_col2:
        score_b = st.number_input(
            "Player 2 Score",
            min_value=0,
            max_value=10,
            value=0,
            key="live_score_b",
        )
    
    # Winner selection
    p1_name = selected_match.get("player1_name", "")
    p2_name = selected_match.get("player2_name", "")
    
    if p1_name and p2_name:
        winner = st.selectbox(
            "Winner",
            options=[p1_name, p2_name],
            key="live_winner",
        )
    else:
        winner = None
        st.warning("Cannot determine winner - player names not available")
    
    submitted = st.form_submit_button("📤 Submit Result", use_container_width=True)
    
    if submitted:
        # Validate scores
        error = validate_score(score_a, score_b)
        if error:
            st.error(f"❌ {error}")
        elif not winner:
            st.error("❌ Please select a winner")
        else:
            score_str = f"{score_a}-{score_b}"
            with st.status("Submitting result...", expanded=False) as status:
                success = submit_match_result(selected_match["match_id"], score_str, winner)
                if success:
                    status.update(label="Result submitted!", state="complete", expanded=False)
                    st.success("✅ Match result submitted successfully!")
                    # Clear cache to refresh match list
                    fetch_matches.clear()
                    st.rerun()
                else:
                    status.update(label="Submission failed", state="error", expanded=False)
                    st.error("❌ Failed to submit match result. Check API connection.")

# Refresh button
st.divider()
if st.button("🔄 Refresh Matches", use_container_width=True):
    fetch_matches.clear()
    fetch_tournaments.clear()
    st.rerun()