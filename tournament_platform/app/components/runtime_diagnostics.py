"""Runtime diagnostics component for Streamlit UI.

Shows the active runtime mode (Local Streamlit / External API), API configuration
and connection status, the Ollama route (API bridge / direct local / fallback),
and Ollama availability through the FastAPI bridge. This is intentionally
collapsed so it never shows a scary "Unavailable" badge by default.
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

    from tournament_platform.app.services.ai_provider import get_runtime_diagnostics as _provider_diag

    prov = _provider_diag()

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
        # Provider-level diagnostics
        "streamlit_cloud": prov["streamlit_cloud"],
        "api_required": prov["api_required"],
        "api_health": prov["api_health"],
        "ollama_route": prov["ollama_route"],
        "hf_token_configured": prov["hf_token_configured"],
        "direct_ollama_allowed": prov["direct_ollama_allowed"],
    }


def render_runtime_diagnostics(key: str = "runtime_diagnostics") -> None:
    """Render a collapsed runtime diagnostics expander."""
    d = get_runtime_diagnostics()

    with st.expander("🔧 Runtime diagnostics", expanded=False):
        st.markdown(f"**Streamlit Cloud detected:** {'yes' if d['streamlit_cloud'] else 'no'}")
        st.markdown(f"**API_BASE_URL configured:** {'yes' if d['api_url_configured'] else 'no'}")
        st.markdown(f"**API_REQUIRED:** {'true' if d['api_required'] else 'false'}")

        if d["api_url_configured"]:
            if d["api_status"] == "connected":
                st.markdown("**API health:** connected ✅")
            elif d["api_status"] == "local_mode":
                st.markdown("**API health:** local mode")
            else:
                tone = "✅" if d["api_ok"] else "⚠️"
                st.markdown(f"**API health:** {d['api_status_label']} {tone}")
        else:
            st.markdown("**API health:** local mode")

        st.markdown(f"**Ollama route:** {d['ollama_route']}")

        if d["ollama_through_api"]:
            if d["ollama_available"]:
                st.markdown("**Ollama via API:** available ✅")
            elif d["ollama_available"] is False:
                st.markdown("**Ollama via API:** unavailable ⚠️")
            else:
                st.markdown("**Ollama via API:** unknown")
        else:
            st.markdown("**Ollama:** local mode / fallback")

        st.markdown(f"**Ollama model:** {d['ollama_model']}")
        st.markdown(f"**HF_TOKEN configured:** {'yes' if d['hf_token_configured'] else 'no'}")
        st.markdown(f"**Direct Ollama allowed:** {'yes' if d['direct_ollama_allowed'] else 'no'}")
