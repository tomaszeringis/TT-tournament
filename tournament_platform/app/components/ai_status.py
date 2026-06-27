"""
AI Status component for Streamlit UI.
Displays connection status, model availability, and any errors.
"""

import streamlit as st
from tournament_platform.services.ai_utils import get_ai_status


@st.cache_data(ttl=30)
def get_cached_ai_status() -> dict:
    """Get AI status with caching for UI display."""
    return get_ai_status()


def render_ai_status_badge(key: str = "ai_status") -> None:
    """
    Render a compact AI status badge in the UI.
    
    Args:
        key: Unique key for Streamlit component
    """
    status = get_cached_ai_status()
    
    if status["ollama_connected"] and status["model_available"]:
        model_name = status["current_model"]
        if status.get("fallback_model"):
            st.success(f"✅ AI Ready (using {model_name})", icon="🤖")
        else:
            st.success(f"✅ AI Ready ({model_name})", icon="🤖")
    elif status["ollama_connected"]:
        st.warning("⚠️ AI Model Unavailable", icon="🤖")
    else:
        st.error("❌ AI Disconnected", icon="🤖")


def render_ai_status_expander(key: str = "ai_status_detail") -> None:
    """
    Render a detailed AI status expander with troubleshooting info.
    
    Args:
        key: Unique key for Streamlit component
    """
    status = get_cached_ai_status()
    
    with st.expander("🤖 AI System Status", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            if status["ollama_connected"]:
                st.metric("Ollama", "Connected", "✅")
            else:
                st.metric("Ollama", "Disconnected", "❌")
        
        with col2:
            if status["model_available"]:
                st.metric("Model", status["current_model"], "✅")
            else:
                st.metric("Model", "Unavailable", "❌")
        
        if status.get("error"):
            st.error(f"Error: {status['error']}")
        
        if status.get("fallback_model"):
            st.info(f"Using fallback model: {status['fallback_model']}")
        
        st.caption("If AI is disconnected, ensure Ollama is running: `ollama serve`")


def get_ai_status_indicator() -> str:
    """
    Get a simple status indicator string for use in other components.
    
    Returns:
        Status string: "connected", "fallback", or "disconnected"
    """
    status = get_cached_ai_status()
    
    if status["ollama_connected"] and status["model_available"]:
        if status.get("fallback_model"):
            return "fallback"
        return "connected"
    return "disconnected"