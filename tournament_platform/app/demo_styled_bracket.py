import streamlit as st
from components.interactive_bracket import interactive_bracket
import json

st.set_page_config(page_title="Professional Bracket Demo", layout="wide")

st.title("Professional Tournament Bracket")
st.markdown("""
This demo showcases the **enhanced styling**, **theme detection**, and **responsive layout** of the bracket component.
It automatically adapts to Streamlit's Light and Dark modes.
""")

# Sample data
bracket_data = {
    "stages": [
        {
            "id": 0,
            "tournamentId": 0,
            "name": "Champions League",
            "type": "single_elimination",
            "number": 1,
            "settings": {"size": 8}
        }
    ],
    "matches": [
        # Round 1
        {"id": 0, "stageId": 0, "groupId": 0, "roundId": 0, "number": 1, "opponent1": {"id": 1, "score": 2}, "opponent2": {"id": 2, "score": 1}, "status": 4},
        {"id": 1, "stageId": 0, "groupId": 0, "roundId": 0, "number": 2, "opponent1": {"id": 3, "score": 0}, "opponent2": {"id": 4, "score": 3}, "status": 4},
        {"id": 2, "stageId": 0, "groupId": 0, "roundId": 0, "number": 3, "opponent1": {"id": 5, "score": 1}, "opponent2": {"id": 6, "score": 2}, "status": 4},
        {"id": 3, "stageId": 0, "groupId": 0, "roundId": 0, "number": 4, "opponent1": {"id": 7, "score": 3}, "opponent2": {"id": 8, "score": 2}, "status": 4},
        # Round 2
        {"id": 4, "stageId": 0, "groupId": 0, "roundId": 1, "number": 1, "opponent1": {"id": 1, "score": 1}, "opponent2": {"id": 4, "score": 2}, "status": 4},
        {"id": 5, "stageId": 0, "groupId": 0, "roundId": 1, "number": 2, "opponent1": {"id": 6}, "opponent2": {"id": 7}, "status": 2},
        # Final
        {"id": 6, "stageId": 0, "groupId": 0, "roundId": 2, "number": 1, "opponent1": {"id": 4}, "opponent2": None, "status": 1},
    ],
    "participants": [
        {"id": 1, "name": "Warriors FC"},
        {"id": 2, "name": "Strikerz"},
        {"id": 3, "name": "Shadows"},
        {"id": 4, "name": "Gladiators"},
        {"id": 5, "name": "Titans"},
        {"id": 6, "name": "Stormers"},
        {"id": 7, "name": "Dragons"},
        {"id": 8, "name": "Knights"}
    ]
}

col1, col2 = st.columns([3, 1])

with col1:
    st.subheader("Interactive Bracket View")
    clicked_match = interactive_bracket(bracket_data, height=500, key="pro_bracket")

with col2:
    st.subheader("Match Control")
    if clicked_match:
        st.info(f"Selected Match ID: {clicked_match['id']}")
        
        # Determine player names
        p1_id = clicked_match.get('opponent1', {}).get('id') if clicked_match.get('opponent1') else None
        p2_id = clicked_match.get('opponent2', {}).get('id') if clicked_match.get('opponent2') else None
        
        participants = {p['id']: p['name'] for p in bracket_data['participants']}
        p1_name = participants.get(p1_id, "TBD")
        p2_name = participants.get(p2_id, "TBD")
        
        st.write(f"**{p1_name}** vs **{p2_name}**")
        
        score1 = clicked_match.get('opponent1', {}).get('score', 0) if clicked_match.get('opponent1') else 0
        score2 = clicked_match.get('opponent2', {}).get('score', 0) if clicked_match.get('opponent2') else 0
        
        st.write(f"Current Score: `{score1} - {score2}`")
        
        if st.button("Open Report Modal"):
            st.toast("Modal would open here to report result.", icon="🏓")
    else:
        st.write("Click a match to see details.")

st.sidebar.title("Configuration")
st.sidebar.info("""
**Professional Features:**
- **Theme Sync**: Colors match your Streamlit theme.
- **Hover Effects**: Matches highlight on hover.
- **Responsive**: Fits within Streamlit columns.
- **Custom Scrollbar**: Matches Streamlit's look.
""")

if st.sidebar.checkbox("Show Raw Data"):
    st.json(bracket_data)
