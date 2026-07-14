"""
Local Piper TTS engine (optional, Phase 3).

Requires:
- ``piper-tts`` Python package (optional)
- ``piper`` binary on PATH or ``python -m piper`` (optional, for CLI fallback)
- Voice models in ``assets/tts/piper/voices/`` as ``.onnx`` + ``.onnx.json`` pairs

If Piper is unavailable, ``available`` is False and the engine is skipped.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from tournament_platform.app.services.commentary_voice.piper_runtime import PiperVoice, get_piper_binary, is_piper_available, find_piper_voices

PIPER_VOICES_DIR = Path("tournament_platform/assets/tts/piper/voices")
PIPER_CACHE_DIR = Path("tournament_platform/data/tts_cache/piper")


class PiperTTSError(Exception):
    """Raised when Piper synthesis fails."""


@dataclass(frozen=True)
class AudioResult:
    audio_path: Path
    mime_type: str = "audio/wav"
    cache_hit: bool = False
    engine: str = "piper"
    voice_id: str | None = None


class PiperTTSEngine:
    """Optional Piper local TTS engine."""

    def __init__(
        self,
        voices_dir: Path = PIPER_VOICES_DIR,
        cache_dir: Path = PIPER_CACHE_DIR,
    ) -> None:
        self.voices_dir = Path(voices_dir)
        self.cache_dir = Path(cache_dir)
        self._piper_available: Optional[bool] = None
        self._piper_binary: Optional[str] = None
        self._engine_version: str = "unknown"

    @property
    def available(self) -> bool:
        if self._piper_available is not None:
            return self._piper_available
        self._piper_available = self._check_available()
        return self._piper_available

    def _check_available(self) -> bool:
        if not is_piper_available():
            return False
        self._piper_binary = get_piper_binary()
        if not self._piper_binary:
            return False
        try:
            import piper

            self._engine_version = getattr(piper, "__version__", "unknown")
        except Exception:
            pass
        return True

    def list_voices(self) -> list[PiperVoice]:
        if not self.available:
            return []
        return find_piper_voices(self.voices_dir)

    def _build_cache_key(
        self,
        text: str,
        voice: PiperVoice,
        rate: float,
        volume: float,
    ) -> str:
        model_mtime = 0.0
        try:
            model_mtime = voice.model_path.stat().st_mtime
        except OSError:
            pass
        payload = (
            text,
            voice.id,
            str(voice.model_path),
            model_mtime,
            rate,
            volume,
            "piper",
            self._engine_version,
        )
        return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()

    def _cache_path(self, cache_key: str, voice: PiperVoice) -> Path:
        safe_voice_id = voice.id.replace("/", "_").replace("\\", "_")
        version_dir = self._engine_version.replace("/", "_").replace("\\", "_")
        path = self.cache_dir / version_dir / safe_voice_id / f"{cache_key}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def synthesize(
        self,
        text: str,
        voice: PiperVoice,
        rate: float = 1.0,
        volume: float = 1.0,
    ) -> AudioResult:
        if not self.available:
            raise PiperTTSError("Piper is not available")
        text = text.strip()
        if not text:
            raise PiperTTSError("Empty text")
        if len(text) > 300:
            text = text[:300]

        cache_key = self._build_cache_key(text, voice, rate, volume)
        cached = self._cache_path(cache_key, voice)
        if cached.exists():
            return AudioResult(audio_path=cached, cache_hit=True, voice_id=voice.id)

        try:
            wav_path = self._synthesize(text, voice, rate, volume)
            return AudioResult(audio_path=wav_path, cache_hit=False, voice_id=voice.id)
        except PiperTTSError:
            raise
        except Exception as exc:
            raise PiperTTSError(str(exc)) from exc

    def _synthesize(self, text: str, voice: PiperVoice, rate: float, volume: float) -> Path:
        binary = self._piper_binary or ""
        temp_output = Path(tempfile.mktemp(suffix=".wav", dir=str(self.cache_dir)))
        try:
            if binary.startswith("python") or binary.endswith("-m"):
                cmd = ["python", "-m", "piper", "-m", str(voice.model_path), "-f", str(temp_output)]
            else:
                cmd = [binary, "-m", str(voice.model_path), "-f", str(temp_output)]
            subprocess.run(
                cmd,
                input=text,
                text=True,
                capture_output=True,
                timeout=10,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            raise PiperTTSError(f"Piper CLI failed: {stderr}") from exc
        except FileNotFoundError as exc:
            raise PiperTTSError("Piper binary not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise PiperTTSError("Piper synthesis timed out") from exc
        except Exception as exc:
            raise PiperTTSError(str(exc)) from exc

        if not temp_output.exists():
            raise PiperTTSError("Piper did not produce output")

        cache_key = self._build_cache_key(text, voice, rate, volume)
        final_path = self._cache_path(cache_key, voice)
        try:
            temp_output.replace(final_path)
        except OSError:
            final_path = temp_output
        return final_path


def get_piper_engine() -> PiperTTSEngine:
    return PiperTTSEngine()
