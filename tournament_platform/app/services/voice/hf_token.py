"""
HF Token Helper

Reads an optional Hugging Face token from the environment or Streamlit secrets
so model downloads can authenticate without hard-coding credentials.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_hf_token() -> Optional[str]:
    """Return the HF token from env or Streamlit secrets, if configured.

    Priority:
    1. ``HF_TOKEN`` environment variable
    2. ``HUGGINGFACEHUB_API_TOKEN`` environment variable
    3. ``HUGGINGFACE_API_TOKEN`` environment variable
    4. ``st.secrets["HF_TOKEN"]`` (Streamlit Cloud / local secrets)
    5. ``st.secrets["HUGGINGFACEHUB_API_TOKEN"]`` (Streamlit Cloud / local secrets)

    The token is never logged or returned in error messages.
    """
    for env_name in ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "HUGGINGFACE_API_TOKEN"):
        token = os.environ.get(env_name)
        if token:
            return token.strip() or None

    try:
        import streamlit as st

        for secret_name in ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"):
            secret_token = st.secrets.get(secret_name)
            if secret_token:
                return str(secret_token).strip() or None
    except Exception:
        pass

    return None


def apply_hf_token() -> None:
    """Apply the HF token to the process environment if available.

    Sets ``HF_TOKEN`` so that ``huggingface_hub`` (used by faster-whisper
    and other HF libraries) can authenticate downloads automatically.
    """
    token = get_hf_token()
    if token and not os.environ.get("HF_TOKEN"):
        os.environ["HF_TOKEN"] = token
        logger.debug("HF_TOKEN applied from secrets/env")
