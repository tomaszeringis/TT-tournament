import streamlit as st
from components.interactive_bracket import interactive_bracket

st.set_page_config(page_title="Interactive Bracket Demo", layout="wide")

st.title("Interactive Tournament Bracket")
st.write("Click on a match to report results or view details.")

# Sample data in brackets-manager.js format
if 'bracket_data' not in st.session_state:
    st.session_state.bracket_data = {
        "stages": [
            {
                "id": 0,
                "tournamentId": 0,
                "name": "Elimination Stage",
                "type": "single_elimination",
                "number": 1,
                "settings": {"size": 4}
            }
        ],
        "matches": [
            {
                "id": 0,
                "stageId": 0,
                "groupId": 0,
                "roundId": 0,
                "number": 1,
                "opponent1": {"id": 1, "name": "Alice", "score": 2},
                "opponent2": {"id": 2, "name": "Bob", "score": 1},
                "status": 4 # Completed
            },
            {
                "id": 1,
                "stageId": 0,
                "groupId": 0,
                "roundId": 0,
                "number": 2,
                "opponent1": {"id": 3, "name": "Charlie"},
                "opponent2": {"id": 4, "name": "David"},
                "status": 2 # Ready
            },
            {
                "id": 2,
                "stageId": 0,
                "groupId": 0,
                "roundId": 1,
                "number": 1,
                "opponent1": {"id": 1},
                "opponent2": None,
                "status": 1 # Waiting
            }
        ],
        "participants": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
            {"id": 4, "name": "David"}
        ]
    }

col1, col2 = st.columns([3, 1])

with col1:
    # Use the custom interactive component
    clicked_match = interactive_bracket(st.session_state.bracket_data, key="tournament_bracket")

with col2:
    st.subheader("Match Details")
    if clicked_match:
        st.write(f"**Match ID:** {clicked_match['id']}")
        st.write(f"**Status:** {clicked_match['status']}")
        
        # Determine player names
        p1_id = clicked_match.get('opponent1', {}).get('id') if clicked_match.get('opponent1') else None
        p2_id = clicked_match.get('opponent2', {}).get('id') if clicked_match.get('opponent2') else None
        
        participants = {p['id']: p['name'] for p in st.session_state.bracket_data['participants']}
        p1_name = participants.get(p1_id, "TBD")
        p2_name = participants.get(p2_id, "TBD")
        
        st.write(f"**Match:** {p1_name} vs {p2_name}")
        
        # Form for reporting
        with st.form("report_form"):
            st.write("Report Result")
            new_score1 = st.number_input(f"Score for {p1_name}", min_value=0, value=clicked_match.get('opponent1', {}).get('score', 0) if clicked_match.get('opponent1') else 0)
            new_score2 = st.number_input(f"Score for {p2_name}", min_value=0, value=clicked_match.get('opponent2', {}).get('score', 0) if clicked_match.get('opponent2') else 0)
            
            if st.form_submit_button("Update Result"):
                st.toast(f"Updating match {clicked_match['id']} with score {new_score1}-{new_score2}", icon="✅")
                # In a real app, you would update the DB and then refresh bracket_data
    else:
        st.info("Click a match in the bracket to see details here.")

st.sidebar.markdown("""
### How it works:
1. **Frontend**: `brackets-viewer.js` renders the bracket.
2. **Event**: The `onMatchClick` callback in JS captures the click.
3. **Communication**: `Streamlit.setComponentValue(match)` sends the data to Python.
4. **Backend**: The `interactive_bracket()` function returns the value, triggering a Streamlit rerun.
""")
