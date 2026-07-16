"""API status helper.

Determines the external API backend status in a way that is safe for Streamlit
Cloud: when no external API is configured the status is ``local_mode`` (never a
scary "Unavailable"). A configured-but-unreachable API is only fatal when
``API_REQUIRED=true``.

Health states
-------------
* ``local_mode``             — no external API configured (app uses local services)
* ``connected``              — external API reachable
* ``optional_unavailable``   — API configured but unreachable and not required
* ``required_unavailable``   — API configured, unreachable, and required
"""

from __future__ import annotations

import time
from typing import Dict, Optional

import requests

from tournament_platform.config.runtime import get_api_token, get_runtime_config

# Brief in-process cache so the health check does not run on every rerun.
_CACHE_TTL_SECONDS = 10.0
_cache: Dict[str, tuple[float, dict]] = {}


def _cached_or_compute(key: str, compute) -> dict:
    now = time.monotonic()
    entry = _cache.get(key)
    if entry and (now - entry[0]) < _CACHE_TTL_SECONDS:
        return entry[1]
    result = compute()
    _cache[key] = (now, result)
    return result


def get_api_status(
    api_base_url: Optional[str] = None,
    api_required: Optional[bool] = None,
    api_token: Optional[str] = None,
) -> dict:
    """Return a structured API status.

    Resolution order for any unset argument is the runtime config (env/secrets).
    The health check hits ``${API_BASE_URL}/health`` with a 1.5s timeout and
    sends a bearer token when configured. It never raises.
    """
    if api_base_url is None or api_required is None:
        cfg = get_runtime_config()
        api_base_url = api_base_url if api_base_url is not None else cfg.api_base_url
        api_required = api_required if api_required is not None else cfg.api_required
        if api_token is None:
            api_token = cfg.api_token

    if not api_base_url:
        return {
            "state": "local_mode",
            "label": "Local Streamlit",
            "message": "External API is not configured. The Streamlit app is using local services.",
            "ok": True,
            "api_required": bool(api_required),
        }

    def _check() -> dict:
        headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
        try:
            response = requests.get(
                f"{api_base_url.rstrip('/')}/health", timeout=1.5, headers=headers
            )
            if response.ok:
                return {
                    "state": "connected",
                    "label": "Connected",
                    "message": "External API is reachable.",
                    "ok": True,
                    "api_required": bool(api_required),
                }
            return {
                "state": "required_unavailable" if api_required else "optional_unavailable",
                "label": "Required API unavailable" if api_required else "Optional API unavailable",
                "message": f"External API returned HTTP {response.status_code}.",
                "ok": not api_required,
                "api_required": bool(api_required),
            }
        except Exception as exc:
            return {
                "state": "required_unavailable" if api_required else "optional_unavailable",
                "label": "Required API unavailable" if api_required else "Optional API unavailable",
                "message": f"External API is not reachable: {exc}",
                "ok": not api_required,
                "api_required": bool(api_required),
            }

    return _cached_or_compute(f"{api_base_url}|{bool(api_required)}", _check)


def get_app_status() -> dict:
    """Return a presentation-friendly app status summary.

    Combines the runtime mode with the API status so the dashboard never shows a
    scary unavailable badge when the app can run without the API.
    """
    cfg = get_runtime_config()
    api = get_api_status(cfg.api_base_url, cfg.api_required, cfg.api_token)

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

    if api["state"] == "required_unavailable":
        return {
            "mode": cfg.mode,
            "is_streamlit_cloud": cfg.is_streamlit_cloud,
            "api_required": True,
            "api_configured": True,
            "state": "required_unavailable",
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
