"""Runtime diagnostics component for Streamlit UI.

Shows the active runtime mode (Local Streamlit / External API), API configuration
and connection status, and Ollama availability through the FastAPI bridge. This
is intentionally collapsed so it never shows a scary "Unavailable" badge when the
app is running in local Streamlit mode.
"""

from __future__ import annotations

import streamlit as st

from tournament_platform.config.runtime import get_runtime_config
from tournament_platform.app import api_status


@st.cache_data(ttl=10)
def get_runtime_diagnostics() -> dict:
    """Build a diagnostics dict for the current runtime."""
    cfg = get_runtime_config()
    api = api_status.get_api_status(cfg.api_base_url, cfg.api_required, cfg.api_token)
    ollama = api_status.get_ollama_diagnostics(cfg)

    if cfg.mode == "local_streamlit":
        mode_label = "Local Streamlit"
    else:
        mode_label = "External API"

    return {
        "mode": cfg.mode,
        "mode_label": mode_label,
        "api_url_configured": bool(cfg.api_base_url),
        "api_status": api["state"],
        "api_status_label": api["label"],
        "api_ok": api["ok"],
        "ollama_through_api": ollama["through_api"],
        "ollama_available": ollama["available"],
        "ollama_model": ollama["model"],
        "ollama_error": ollama.get("error"),
    }


def render_runtime_diagnostics(key: str = "runtime_diagnostics") -> None:
    """Render a collapsed runtime diagnostics expander."""
    d = get_runtime_diagnostics()

    with st.expander("🔧 Runtime diagnostics", expanded=False):
        st.markdown(f"**Mode:** {d['mode_label']}")
        st.markdown(f"**API URL configured:** {'yes' if d['api_url_configured'] else 'no'}")

        if d["api_url_configured"]:
            if d["api_status"] == "connected":
                st.markdown("**API status:** connected ✅")
            elif d["api_status"] == "local_mode":
                st.markdown("**API status:** local mode")
            else:
                tone = "✅" if d["api_ok"] else "⚠️"
                st.markdown(f"**API status:** {d['api_status_label']} {tone}")
        else:
            st.markdown("**API status:** local mode")

        if d["ollama_through_api"]:
            if d["ollama_available"]:
                st.markdown("**Ollama through API:** connected ✅")
            elif d["ollama_available"] is False:
                st.markdown("**Ollama through API:** unavailable ⚠️")
            else:
                st.markdown("**Ollama through API:** unknown")
        else:
            st.markdown("**Ollama through API:** local mode")

        st.markdown(f"**Ollama model:** {d['ollama_model']}")
