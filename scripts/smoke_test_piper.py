#!/usr/bin/env python3
"""
Smoke test for Piper local TTS.

This script is not imported during normal app startup.
Run it manually after installing Piper and adding voice models.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PIPER_VOICES_DIR = PROJECT_ROOT / "tournament_platform" / "assets" / "tts" / "piper" / "voices"
PIPER_CACHE_DIR = PROJECT_ROOT / "tournament_platform" / "data" / "tts_cache" / "piper"
SMOKE_TEST_OUTPUT = PIPER_CACHE_DIR / "piper_smoke_test.wav"
SMOKE_TEST_TEXT = "Point Tomas. Ten eight."


def find_piper_voices() -> list[tuple[Path, Path]]:
    """Return list of (onnx_path, json_path) pairs from nested or flat layout."""
    if not PIPER_VOICES_DIR.exists():
        return []
    pairs = []
    # Nested layout: voices/<voice_id>/<voice_id>.onnx
    for voice_folder in PIPER_VOICES_DIR.iterdir():
        if not voice_folder.is_dir():
            continue
        onnx_path = voice_folder / f"{voice_folder.name}.onnx"
        json_path = voice_folder.with_suffix(".onnx.json")
        if onnx_path.exists() and json_path.exists():
            pairs.append((onnx_path, json_path))
            continue
        # Flat layout inside folder
        for onnx_path in voice_folder.glob("*.onnx"):
            if onnx_path.name == ".gitkeep":
                continue
            json_path = onnx_path.with_suffix(".onnx.json")
            if json_path.exists():
                pairs.append((onnx_path, json_path))
    # Flat layout fallback: voices/*.onnx
    if not pairs:
        for onnx_path in PIPER_VOICES_DIR.glob("*.onnx"):
            if onnx_path.name == ".gitkeep":
                continue
            json_path = onnx_path.with_suffix(".onnx.json")
            if json_path.exists():
                pairs.append((onnx_path, json_path))
    return pairs


def synthesize_with_cli(onnx_path: Path, text: str, output_path: Path) -> bool:
    """Try synthesizing using `python -m piper` CLI."""
    cmd = [sys.executable, "-m", "piper", "-m", str(onnx_path), "-f", str(output_path)]
    try:
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0 and output_path.exists():
            return True
        logger.debug("Piper CLI stderr: %s", proc.stderr.decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.debug("Piper CLI failed: %s", exc)
    return False


def synthesize_with_python_api(onnx_path: Path, text: str, output_path: Path) -> bool:
    """Try synthesizing using the Piper Python API."""
    try:
        from piper import PiperVoice  # type: ignore
    except Exception as exc:
        logger.debug("Piper Python API import failed: %s", exc)
        return False
    try:
        voice = PiperVoice.load(str(onnx_path))
        voice.synthesize(text, str(output_path))
        return output_path.exists()
    except Exception as exc:
        logger.debug("Piper Python API synthesis failed: %s", exc)
        return False


def main() -> int:
    # Check if Piper package is installed
    try:
        import piper  # noqa: F401
    except ImportError:
        logger.info("Piper is not installed. Install with: python -m pip install 'piper-tts>=1.4,<2'")
        return 0

    # Find local voice models
    voices = find_piper_voices()
    if not voices:
        logger.info(
            "Piper is installed, but no local voice models were found.\n"
            "Add .onnx and .onnx.json files to %s.",
            PIPER_VOICES_DIR,
        )
        return 0

    # Ensure cache directory exists
    PIPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    onnx_path, _ = voices[0]
    logger.info("Found Piper voice: %s", onnx_path.name)

    # Try CLI first, then Python API
    success = synthesize_with_cli(onnx_path, SMOKE_TEST_TEXT, SMOKE_TEST_OUTPUT)
    if not success:
        success = synthesize_with_python_api(onnx_path, SMOKE_TEST_TEXT, SMOKE_TEST_OUTPUT)

    if success and SMOKE_TEST_OUTPUT.exists():
        logger.info("Piper smoke test succeeded: %s", SMOKE_TEST_OUTPUT)
        return 0

    logger.error("Piper smoke test failed. Check voice model and Piper installation.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
