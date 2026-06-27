"""
AI Assistant - Dedicated chat interface for tournament questions.
A first-class AI feature with proper Streamlit chat elements.
Uses the AI facade for a clean, stable service interface.
"""

import streamlit as st
from typing import Optional, List, Dict

from tournament_platform.services.ai_facade import answer_rules_question, AIAnswer
from tournament_platform.app.components.ai_status import render_ai_status_badge, render_ai_status_expander
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player

# Initialize chat history
if 'ai_chat_history' not in st.session_state:
    st.session_state.ai_chat_history = []

# Initialize feedback storage
if 'ai_feedback' not in st.session_state:
    st.session_state.ai_feedback = {}


def get_current_match_context() -> Optional[dict]:
    """Get the current match context from the database."""
    try:
        db = SessionLocal()
        active_match = db.query(Match).filter(
            Match.status == MatchStatus.active
        ).order_by(Match.scheduled_time.desc()).first()

        if active_match:
            p1 = db.query(Player).filter(Player.id == active_match.player1_id).first() if active_match.player1_id else None
            p2 = db.query(Player).filter(Player.id == active_match.player2_id).first() if active_match.player2_id else None
            context = {
                "player1": p1.name if p1 else "Unknown",
                "player2": p2.name if p2 else "Unknown",
                "tournament": active_match.tournament.name if active_match.tournament else None,
                "score": active_match.score,
                "match_id": active_match.id
            }
            db.close()
            return context
        db.close()
    except Exception:
        pass
    return None


# Page UI
st.title("🤖 AI Assistant")

# Page intro explaining capabilities
st.markdown("""
This AI assistant can help you with:
- **Rules questions** - Ask about tournament rules and regulations
- **Standings explanation** - Understand the current tournament standings
- **Match reporting help** - Get guidance on how to report match results
- **Tournament status** - Check on ongoing tournaments and matches
""")

# Show AI status
render_ai_status_badge()

# Sidebar with Assistant capabilities
with st.sidebar:
    st.subheader("💡 Assistant Capabilities")
    st.markdown("""
    - Answer rules questions using RAG
    - Explain tournament standings
    - Help with match reporting
    - Summarize tournament status
    
    **Note:** This assistant provides information only. 
    No database changes are made from chat responses.
    """)
    
    # Clear conversation button
    if st.session_state.ai_chat_history:
        if st.button("🗑️ Clear Conversation", use_container_width=True):
            st.session_state.ai_chat_history = []
            st.session_state.ai_feedback = {}
            st.rerun()

# Display chat history using st.chat_message
for i, message in enumerate(st.session_state.ai_chat_history):
    with st.chat_message(message["role"]):
        st.write(message["content"])
        
        # Show sources for assistant messages
        if message["role"] == "assistant" and message.get("source_details"):
            with st.expander("📚 Sources used", expanded=False):
                for source in message["source_details"]:
                    st.markdown(f"**Source:** {source.get('id', 'Unknown')}")
                    if source.get('metadata'):
                        meta = source['metadata']
                        if meta.get('source'):
                            st.caption(f"Document: {meta.get('source')}")
                        if meta.get('page'):
                            st.caption(f"Page: {meta.get('page')}")
                    st.markdown(f"**Relevance:** {source.get('distance', 'N/A')}")
                    st.markdown("---")
        
        # Show feedback buttons for assistant messages
        if message["role"] == "assistant" and message.get("msg_id"):
            msg_id = message["msg_id"]
            if msg_id not in st.session_state.ai_feedback:
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("👍 Helpful", key=f"helpful_{msg_id}"):
                        st.session_state.ai_feedback[msg_id] = "helpful"
                        st.rerun()
                with col2:
                    if st.button("👎 Not helpful", key=f"not_helpful_{msg_id}"):
                        st.session_state.ai_feedback[msg_id] = "not_helpful"
                        st.rerun()
            else:
                feedback = st.session_state.ai_feedback[msg_id]
                st.caption(f"Feedback: {'👍 Helpful' if feedback == 'helpful' else '👎 Not helpful'}")

# Chat input using st.chat_input
prompt = st.chat_input("Ask a question about tournaments, rules, or standings...")

if prompt:
    # Display user message
    with st.chat_message("user"):
        st.write(prompt)
    
    # Add to chat history
    st.session_state.ai_chat_history.append({
        "role": "user",
        "content": prompt
    })
    
    # Get AI response with status indicator
    with st.chat_message("assistant"):
        with st.status("Thinking...", expanded=False) as status:
            try:
                # Use the facade for a clean interface
                ai_answer: AIAnswer = answer_rules_question(prompt)
                response = ai_answer.answer
                status.update(label="Answer ready", state="complete", expanded=False)
            except Exception as e:
                response = "Sorry, I couldn't process your question. Please ensure Ollama is running and the model is available."
                ai_answer = AIAnswer(answer=response, sources=[], source_details=[], confidence=None, grounded=False)
                status.update(label="Error occurred", state="error", expanded=False)
        
        st.write(response)
        
        # Show sources if available
        if ai_answer.source_details:
            with st.expander("📚 Sources used", expanded=False):
                for source in ai_answer.source_details:
                    st.markdown(f"**Source:** {source.get('id', 'Unknown')}")
                    if source.get('metadata'):
                        meta = source['metadata']
                        if meta.get('source'):
                            st.caption(f"Document: {meta.get('source')}")
                        if meta.get('page'):
                            st.caption(f"Page: {meta.get('page')}")
                    st.markdown(f"**Relevance:** {source.get('distance', 'N/A')}")
                    st.markdown("---")
        
        # Show confidence indicator
        if not ai_answer.grounded:
            st.warning("⚠️ No relevant rules found in the knowledge base. This answer is not grounded in official rules.")
    
    # Add to chat history with source details
    import uuid
    msg_id = str(uuid.uuid4())
    st.session_state.ai_chat_history.append({
        "role": "assistant",
        "content": response,
        "source_details": ai_answer.source_details,
        "msg_id": msg_id
    })

# Detailed status expander
st.divider()
render_ai_status_expander()