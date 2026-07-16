"""
Compatibility shim for rendering inline HTML via Streamlit components.

Streamlit warns that ``st.components.v1.html`` may be removed after 2026-06-01
for the external-URL embedding case. This module centralizes the inline-HTML
rendering path (used for browser speech synthesis, audio cues, and animations)
so the call site is a single, supported location.

NOTE: This is intentionally NOT replaced with ``st.iframe``. ``st.iframe`` is
for embedding external URLs; the commentary/audio features inject inline
HTML/JS into the page and must keep using the HTML component.
"""

from __future__ import annotations

import streamlit as st
from streamlit.components.v1 import declare_component  # noqa: F401  (kept for forward-compat)


def render_html(
    html: str,
    *,
    height: int = 0,
    width: int = 0,
    scrolling: bool = False,
) -> None:
    """Render inline HTML/JS in the page.

    Thin wrapper around the Streamlit HTML component. All callers that inject
    inline scripts (speech synthesis, audio cues, loading animations, bracket
    rendering) should use this helper instead of calling ``components.html``
    directly.
    """
    import streamlit.components.v1 as components

    components.html(html, height=height, width=width, scrolling=scrolling)
