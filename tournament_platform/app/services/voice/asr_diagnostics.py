"""
Voice ASR Diagnostics & Settings Helpers

Provides:
- ``get_voice_setting``: read a voice/ASR setting from environment, falling
  back to Streamlit secrets, then a default. Streamlit Cloud secrets do NOT
  automatically become ``os.environ`` values, so this helper is the single
  correct way to read voice configuration in the app.
- ``diagnose_faster_whisper_environment``: probe the ASR dependency stack and
  report exactly which packages are present/importable so failures are
  diagnosable instead of surfacing as a vague "Status unavailable" message.

These helpers are import-safe (no Streamlit/page side effects) so they can be
unit tested directly.
"""

from __future__ import annotations

import os
import sys
import platform
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_voice_setting(name: str, default: str) -> str:
    """Read a voice/ASR setting from env, then Streamlit secrets, then default.

    Streamlit Cloud secrets are not injected into ``os.environ`` automatically,
    so this helper honors both sources. Returns ``str`` always.

    Args:
        name: Setting name, e.g. ``"VOICE_ASR_MODEL_SIZE"``.
        default: Value to return when neither env nor secrets provide it.
    """
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        if name in st.secrets:
            secret_val = st.secrets[name]
            if secret_val is not None:
                return str(secret_val)
    except Exception:
        # st may be unavailable (e.g. unit tests) or secrets not configured.
        pass

    return default


def _safe_import_version(module_name: str) -> str:
    """Return installed version of ``module_name`` or a missing/error marker."""
    try:
        module = __import__(module_name)
        return getattr(module, "__version__", "installed")
    except Exception as exc:  # ImportError, or any load failure
        kind = type(exc).__name__
        return f"missing_or_failed({kind}: {exc})"


def diagnose_faster_whisper_environment() -> Dict[str, Any]:
    """Probe the faster-whisper dependency stack and report readiness.

    Returns a dict with structured readiness info suitable for UI/logging:

        {
            "provider": "faster_whisper",
            "available": bool,
            "reason": str,
            "imports": {module_name: version_or_error, ...},
        }

    ``reason`` is one of the precise states used across the app:
    ``not_configured``, ``package_missing``, ``import_failed``,
    ``model_loading``, ``model_loaded``, ``model_download_failed``,
    ``model_init_failed``, ``ready``.
    """
    result: Dict[str, Any] = {
        "provider": "faster_whisper",
        "available": False,
        "reason": "not_configured",
        "imports": {},
    }

    for module_name in ("faster_whisper", "ctranslate2", "av", "onnxruntime"):
        result["imports"][module_name] = _safe_import_version(module_name)

    try:
        from faster_whisper import WhisperModel  # noqa: F401

        result["available"] = True
        result["reason"] = "imports_ok"
    except Exception as exc:
        result["available"] = False
        kind = type(exc).__name__
        result["reason"] = f"import_failed({kind}: {exc})"

    return result


def log_voice_asr_environment_once() -> None:
    """Log ASR configuration + dependency versions once per process.

    Safe to call on every page render; it only emits the diagnostic block the
    first time via a module-level flag. Never raises.
    """
    global _ENV_DIAGNOSTICS_LOGGED
    if _ENV_DIAGNOSTICS_LOGGED:
        return
    _ENV_DIAGNOSTICS_LOGGED = True
    try:
        model_size = get_voice_setting("VOICE_ASR_MODEL_SIZE", "tiny.en")
        device = get_voice_setting("VOICE_ASR_DEVICE", "cpu")
        compute_type = get_voice_setting("VOICE_ASR_COMPUTE_TYPE", "int8")
        diag = diagnose_faster_whisper_environment()
        imports = diag.get("imports", {})
        logger.info(
            "Voice ASR config: provider=faster_whisper model_size=%s device=%s "
            "compute_type=%s python_version=%s faster_whisper=%s ctranslate2=%s "
            "av=%s onnxruntime=%s",
            model_size,
            device,
            compute_type,
            sys.version.split()[0],
            imports.get("faster_whisper"),
            imports.get("ctranslate2"),
            imports.get("av"),
            imports.get("onnxruntime"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Voice ASR env diagnostics skipped: %s", exc)


_ENV_DIAGNOSTICS_LOGGED = False
