"""API status helper.

Determines the external API backend status in a way that is safe for Streamlit
Cloud: when no external API is configured the status is ``local_mode`` (never a
scary "Unavailable"). A configured-but-unreachable API is only fatal when
``API_REQUIRED=true``.
"""

from __future__ import annotations

from typing import Optional

import requests

from tournament_platform.config.runtime import get_runtime_config


def get_api_status(
    api_base_url: Optional[str] = None,
    api_required: bool = False,
) -> dict:
    """Return a structured API status.

    Returns one of:

    * ``local_mode``      — no external API configured (app uses local services)
    * ``connected``       — external API reachable
    * ``unavailable``     — external API configured but not reachable
    """
    # When api_base_url is not provided, resolve from runtime config.
    if api_base_url is None:
        cfg = get_runtime_config()
        api_base_url = cfg.api_base_url
        api_required = api_required or cfg.api_required

    if not api_base_url:
        return {
            "state": "local_mode",
            "label": "Local Streamlit",
            "message": "External API is not configured. The Streamlit app is using local services.",
            "ok": True,
            "api_required": api_required,
        }

    try:
        response = requests.get(f"{api_base_url.rstrip('/')}/health", timeout=1.5)
        if response.ok:
            return {
                "state": "connected",
                "label": "Connected",
                "message": "External API is reachable.",
                "ok": True,
                "api_required": api_required,
            }

        return {
            "state": "unavailable",
            "label": "Required API unavailable" if api_required else "Optional API unavailable",
            "message": f"External API returned HTTP {response.status_code}.",
            "ok": not api_required,
            "api_required": api_required,
        }

    except Exception as exc:
        return {
            "state": "unavailable",
            "label": "Required API unavailable" if api_required else "Optional API unavailable",
            "message": f"External API is not reachable: {exc}",
            "ok": not api_required,
            "api_required": api_required,
        }


def get_app_status() -> dict:
    """Return a presentation-friendly app status summary.

    Combines the runtime mode with the API status so the dashboard never shows a
    scary unavailable badge when the app can run without the API.
    """
    cfg = get_runtime_config()
    api = get_api_status(cfg.api_base_url, cfg.api_required)

    if api["state"] == "local_mode":
        return {
            "mode": cfg.mode,
            "is_streamlit_cloud": cfg.is_streamlit_cloud,
            "api_required": cfg.api_required,
            "api_configured": bool(cfg.api_base_url),
            "state": "local_mode",
            "label": "Local Streamlit",
            "message": "App is ready. External API is not configured / not required.",
            "ok": True,
        }

    if api["state"] == "connected":
        return {
            "mode": cfg.mode,
            "is_streamlit_cloud": cfg.is_streamlit_cloud,
            "api_required": cfg.api_required,
            "api_configured": True,
            "state": "connected",
            "label": "API Connected",
            "message": "External API is reachable.",
            "ok": True,
        }

    # unavailable
    if cfg.api_required:
        return {
            "mode": cfg.mode,
            "is_streamlit_cloud": cfg.is_streamlit_cloud,
            "api_required": True,
            "api_configured": True,
            "state": "unavailable",
            "label": "Required API unavailable",
            "message": "The required external API is not reachable. Some features may be limited.",
            "ok": False,
        }

    return {
        "mode": cfg.mode,
        "is_streamlit_cloud": cfg.is_streamlit_cloud,
        "api_required": False,
        "api_configured": True,
        "state": "optional_unavailable",
        "label": "Optional API unavailable",
        "message": "External API is not reachable. The app is using local fallback mode.",
        "ok": True,
    }
