"""
Optional Piper runtime detection helpers.

Exposes lightweight functions for checking Piper availability and finding
local voice models without importing heavy dependencies at module load time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PIPER_VOICES_DIR = Path("tournament_platform/assets/tts/piper/voices")
PIPER_CACHE_DIR = Path("tournament_platform/data/tts_cache/piper")


@dataclass(frozen=True)
class PiperVoice:
    id: str
    label: str
    model_path: Path
    config_path: Path
    language: str | None = None


def is_piper_available() -> bool:
    """Return True if Piper package is installed and importable."""
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def get_piper_binary() -> str | None:
    """Return command to invoke Piper.

    On Windows, prefer ``python -m piper`` because the packaged ``piper.exe``
    can fail with ``WinError 5`` (Access is denied) in some environments.
    """
    import platform
    import shutil

    if platform.system() == "Windows":
        try:
            import piper  # noqa: F401
            return f"{Path(__import__('sys').executable).name} -m piper"
        except ImportError:
            return None

    binary = shutil.which("piper")
    if binary:
        return binary
    try:
        import piper  # noqa: F401
        return f"{Path(__import__('sys').executable).name} -m piper"
    except ImportError:
        return None


def _infer_language(voice_id: str) -> str | None:
    parts = voice_id.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return None


def find_piper_voices(base_dir: Path | None = None) -> list[PiperVoice]:
    """Scan the local Piper voices directory for valid voice pairs.

    Supports nested layout:
        voices/<voice_id>/<voice_id>.onnx
        voices/<voice_id>/<voice_id>.onnx.json

    And flat layout:
        voices/<voice_id>.onnx
        voices/<voice_id>.onnx.json

    Returns a list of PiperVoice objects.
    Returns an empty list if Piper is not installed or no voices are found.
    """
    if not is_piper_available():
        return []

    voices_dir = base_dir or PIPER_VOICES_DIR
    if not voices_dir.is_absolute() and base_dir is None:
        voices_dir = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "tts" / "piper" / "voices"

    if not voices_dir.exists():
        return []

    results: list[PiperVoice] = []
    seen_ids: set[str] = set()

    # Nested layout: voices/<voice_id>/<voice_id>.onnx
    for voice_folder in voices_dir.iterdir():
        if not voice_folder.is_dir():
            continue
        onnx_path = voice_folder / f"{voice_folder.name}.onnx"
        json_path = voice_folder.with_suffix(".onnx.json")
        if not onnx_path.exists():
            onnx_path = voice_folder / f"{voice_folder.name}.onnx"
        if onnx_path.exists() and json_path.exists():
            voice_id = voice_folder.name
            if voice_id not in seen_ids:
                seen_ids.add(voice_id)
                results.append(
                    PiperVoice(
                        id=voice_id,
                        label=voice_id,
                        model_path=onnx_path,
                        config_path=json_path,
                        language=_infer_language(voice_id),
                    )
                )
            continue

        # Flat layout fallback inside folder
        for onnx_path in voice_folder.glob("*.onnx"):
            if onnx_path.name == ".gitkeep":
                continue
            json_path = onnx_path.with_suffix(".onnx.json")
            if not json_path.exists():
                continue
            voice_id = onnx_path.stem
            if voice_id not in seen_ids:
                seen_ids.add(voice_id)
                results.append(
                    PiperVoice(
                        id=voice_id,
                        label=voice_id,
                        model_path=onnx_path,
                        config_path=json_path,
                        language=_infer_language(voice_id),
                    )
                )

    # Flat layout fallback: voices/*.onnx
    for onnx_path in voices_dir.glob("*.onnx"):
        if onnx_path.name == ".gitkeep":
            continue
        if onnx_path.parent != voices_dir:
            continue
        json_path = onnx_path.with_suffix(".onnx.json")
        if not json_path.exists():
            continue
        voice_id = onnx_path.stem
        if voice_id not in seen_ids:
            seen_ids.add(voice_id)
            results.append(
                PiperVoice(
                    id=voice_id,
                    label=voice_id,
                    model_path=onnx_path,
                    config_path=json_path,
                    language=_infer_language(voice_id),
                )
            )

    return results
