"""
Voice ASR Module

Local automatic speech recognition wrapper using faster-whisper.
Provides lazy model loading, configurable settings, and graceful error handling.
"""

import os
import threading
import tempfile
import wave
import logging
from typing import Optional, Any

from tournament_platform.app.services.voice_vocab import VoiceVocabulary
from tournament_platform.app.services.voice.hf_token import apply_hf_token, get_hf_token
from tournament_platform.app.services.voice.asr_diagnostics import get_voice_setting
from tournament_platform.app.services.asr_backends.base import TranscriptionResult

logger = logging.getLogger(__name__)

# Ensure HF token is available in the environment before any HF library
# attempts to download models. This prevents unauthenticated-request warnings
# and rate-limit errors on Streamlit Cloud and local runs.
apply_hf_token()

# ---------------------------------------------------------------------------
# Module-level model cache
# ---------------------------------------------------------------------------
# Key: (model_size, device, compute_type) -> WhisperModel instance
# This ensures the model is loaded only once per unique configuration,
# even if multiple LocalASR instances are created (e.g., per WebRTC
# processor rerun).
_ASR_MODEL_CACHE: dict = {}
_ASR_CACHE_LOCK = threading.Lock()


class LocalASRError(Exception):
    """Raised when the local ASR cannot be initialized or used."""
    pass


class LocalASR:
    """
    Local ASR wrapper around faster-whisper.
    
    Features:
    - Lazy model loading (doesn't block import/startup)
    - Configurable model size, device, and compute type
    - Environment variable overrides
    - Graceful error handling with clear messages
    - Shared model cache across instances
    """
    
    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        vocabulary: Optional[VoiceVocabulary] = None,
        hotwords: Optional[str] = None,
    ):
        """
        Initialize the LocalASR wrapper.
        
        Args:
            model_size: Whisper model size (e.g., "base.en", "small.en")
            device: Device to run on ("cpu", "cuda", "auto")
            compute_type: Compute type ("int8", "float16", "float32")
            vocabulary: Optional VoiceVocabulary for biasing/post-processing.
            hotwords: Optional comma-separated hotwords hint for the ASR backend.
                      Falls back to vocabulary biasing words when not provided.
        """
        self.model_size = model_size or get_voice_setting("VOICE_ASR_MODEL_SIZE", "tiny.en")
        self.device = device or get_voice_setting("VOICE_ASR_DEVICE", "cpu")
        self.compute_type = compute_type or get_voice_setting("VOICE_ASR_COMPUTE_TYPE", "int8")
        self.vocabulary = vocabulary or VoiceVocabulary.load()
        self._hotwords = hotwords
        
        # Lazy-loaded model (shared via module-level cache)
        self._model = None
        self._load_lock = threading.Lock()
        self._load_attempted = False
        self._load_failed = False
        self._load_error: Optional[str] = None
        self._inference_lock = threading.Lock()
    
    def _load_model(self) -> None:
        """
        Lazily load the WhisperModel.
        
        Thread-safe: only one thread will actually load the model.
        Uses a module-level cache so the model is shared across all
        LocalASR instances with the same configuration.
        """
        if self._model is not None:
            return
        
        if self._load_attempted:
            if self._load_failed:
                raise LocalASRError(
                    f"Model loading previously failed: {self._load_error}"
                )
            return
        
        cache_key = (self.model_size, self.device, self.compute_type)
        
        # Check module-level cache first
        with _ASR_CACHE_LOCK:
            cached = _ASR_MODEL_CACHE.get(cache_key)
            if cached is not None:
                self._model = cached
                self._load_attempted = True
                logger.debug(
                    "Reusing cached faster-whisper model: %s (%s, %s)",
                    self.model_size, self.device, self.compute_type,
                )
                return
        
        with self._load_lock:
            if self._model is not None:
                return
            
            # Double-check cache after acquiring lock
            with _ASR_CACHE_LOCK:
                cached = _ASR_MODEL_CACHE.get(cache_key)
                if cached is not None:
                    self._model = cached
                    self._load_attempted = True
                    return
            
            self._load_attempted = True
            
            try:
                from faster_whisper import WhisperModel
                
                logger.info(
                    "Loading faster-whisper model: %s on %s (%s)",
                    self.model_size,
                    self.device,
                    self.compute_type,
                )
                
                hf_token = get_hf_token()
                kwargs = {
                    "device": self.device,
                    "compute_type": self.compute_type,
                }
                if hf_token:
                    kwargs["token"] = hf_token
                
                model = WhisperModel(
                    self.model_size,
                    **kwargs,
                )
                
                # Store in module-level cache
                with _ASR_CACHE_LOCK:
                    _ASR_MODEL_CACHE[cache_key] = model
                
                self._model = model
                
                logger.info("faster-whisper model loaded successfully")
                
            except ImportError as e:
                self._load_failed = True
                self._load_error = (
                    "faster-whisper is not installed. "
                    "Install it with: pip install faster-whisper"
                )
                logger.error(self._load_error)
                raise LocalASRError(self._load_error) from e
                
            except Exception as e:
                self._load_failed = True
                self._load_error = str(e)
                logger.error("Failed to load faster-whisper model: %s", e)
                raise LocalASRError(
                    f"Failed to load faster-whisper model '{self.model_size}': {e}"
                ) from e
    
    def _get_default_hotwords(self) -> str:
        """Return a comma-separated hotwords hint for table-tennis score commands.

        Uses the parser grammar and vocabulary when available; falls back to a
        conservative built-in list so short commands like 'point red' are
        strongly preferred over unrelated phrases.
        """
        words: List[str] = []
        vocab = self.vocabulary
        if vocab is not None:
            words.extend(vocab.get_biasing_words())
        if not words:
            words = [
                "point", "points", "red", "blue", "undo", "score",
                "player one", "player two", "deuce", "reset",
            ]
        # Deduplicate while preserving order
        seen: set = set()
        deduped = []
        for w in words:
            low = w.lower()
            if low not in seen:
                seen.add(low)
                deduped.append(w)
        return ", ".join(deduped)

    def _get_default_initial_prompt(self) -> str:
        """Return a concise initial prompt that biases toward score commands."""
        return (
            "Table tennis score command. "
            "Point red, point blue, red point, blue point, "
            "points red, points blue, undo, take back."
        )

    def _transcribe_with_kwargs(
        self,
        audio_bytes: bytes,
        transcribe_kwargs: dict[str, Any],
    ) -> str:
        """Write PCM to a temp WAV, run faster-whisper, and return text."""
        if not audio_bytes:
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            with wave.open(f, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_bytes)
            temp_path = f.name

        try:
            with self._inference_lock:
                segments, info = self._model.transcribe(temp_path, **transcribe_kwargs)
                text = " ".join(seg.text for seg in segments).strip()
            logger.debug(
                "Transcribed %d samples in %.2fs: %s",
                len(audio_bytes) // 2,
                info.duration,
                text,
            )
            return text
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def transcribe_chunk(self, audio_bytes: bytes) -> str:
        """
        Transcribe a chunk of audio and return normalized text.
        
        Args:
            audio_bytes: PCM audio bytes (mono, 16kHz, int16)
             
        Returns:
            Transcribed text string, or empty string if transcription fails.
        """
        if not audio_bytes:
            return ""
        
        try:
            self._load_model()
        except LocalASRError as e:
            logger.warning("ASR not available: %s", e)
            return ""
        
        try:
            transcribe_kwargs: dict[str, Any] = {
                "beam_size": 5,
                "language": "en",
                "condition_on_previous_text": False,
            }
            initial_prompt = self.vocabulary.get_initial_prompt() if self.vocabulary else ""
            if not initial_prompt:
                initial_prompt = self._get_default_initial_prompt()
            transcribe_kwargs["initial_prompt"] = initial_prompt
            
            hotwords = self._hotwords
            if hotwords is None and self.vocabulary:
                biasing = self.vocabulary.get_biasing_words()
                if biasing:
                    hotwords = self._get_default_hotwords()
            if hotwords:
                transcribe_kwargs["hotwords"] = hotwords
            
            return self._transcribe_with_kwargs(audio_bytes, transcribe_kwargs)
                
        except Exception as e:
            logger.error("Transcription error: %s", e)
            return ""

    def transcribe_experiment(
        self,
        *,
        audio: bytes,
        config: Any,
    ) -> TranscriptionResult:
        """
        Transcribe audio using an explicit experiment configuration.

        Reuses the loaded model and passes only supported parameters.
        Never mutates production defaults or reloads the model.
        """
        if not audio:
            return TranscriptionResult(text="")

        try:
            self._load_model()
        except LocalASRError as e:
            logger.warning("ASR experiment unavailable: %s", e)
            return TranscriptionResult(text="")

        transcribe_kwargs: dict[str, Any] = {}
        if config.language:
            transcribe_kwargs["language"] = config.language
        if config.initial_prompt:
            transcribe_kwargs["initial_prompt"] = config.initial_prompt
        if config.hotwords:
            transcribe_kwargs["hotwords"] = config.hotwords
        if config.condition_on_previous_text is not None:
            transcribe_kwargs["condition_on_previous_text"] = config.condition_on_previous_text
        if config.beam_size is not None:
            transcribe_kwargs["beam_size"] = config.beam_size

        import time as _time
        start = _time.perf_counter()
        try:
            text = self._transcribe_with_kwargs(audio, transcribe_kwargs)
            latency_ms = (_time.perf_counter() - start) * 1000.0
            return TranscriptionResult(
                text=text,
                language=config.language,
                latency_ms=latency_ms,
                metadata={
                    "config_id": config.config_id,
                    "beam_size": config.beam_size,
                    "condition_on_previous_text": config.condition_on_previous_text,
                },
            )
        except Exception as e:
            logger.error("Experiment transcription error: %s", e)
            return TranscriptionResult(text="")
    
    def is_available(self) -> bool:
        """
        Check if the ASR is available (model can be loaded).
        
        Returns:
            True if ASR is available, False otherwise.
        """
        try:
            self._load_model()
            return True
        except LocalASRError:
            return False
    
    def get_status(self) -> dict:
        """
        Get current ASR status.
        
        Returns:
            Dict with availability, model info, and any errors.
        """
        # Derive a precise, UI-safe readiness state instead of a vague reason.
        if self._model is not None:
            state = "model_loaded"
        elif self._load_failed:
            if self._load_error and "not installed" in self._load_error:
                state = "package_missing"
            elif self._load_error and "download" in self._load_error.lower():
                state = "model_download_failed"
            elif self._load_error:
                state = "model_init_failed"
            else:
                state = "import_failed"
        elif self._load_attempted:
            state = "model_loading"
        else:
            state = "not_configured"

        return {
            "available": self.is_available(),
            "state": state,
            "reason": self._load_error or state,
            "model_size": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type,
            "load_attempted": self._load_attempted,
            "load_failed": self._load_failed,
            "load_error": self._load_error,
        }
    
    def get_setup_instructions(self) -> str:
        """
        Get human-readable setup instructions if ASR is not available.
        
        Returns:
            Setup instructions string.
        """
        if self._model is not None:
            return ""
        
        if self._load_failed and self._load_error:
            if "not installed" in self._load_error:
                return (
                    "**faster-whisper not installed**\n\n"
                    "Install with:\n"
                    "```\n"
                    "pip install faster-whisper\n"
                    "```\n\n"
                    "On first use, the model will be downloaded automatically (~140MB for base.en)."
                )
            else:
                return f"**ASR Error:** {self._load_error}"
        
        return (
            "**Voice ASR Setup**\n\n"
            "1. Install faster-whisper: `pip install faster-whisper`\n"
            "2. The model will download automatically on first use\n"
            "3. For CPU: use `base.en` or `small.en`\n"
            "4. For GPU: use `medium.en` or `large-v3` with CUDA\n\n"
            "Environment variables:\n"
            "- `VOICE_ASR_MODEL_SIZE` (default: base.en)\n"
            "- `VOICE_ASR_DEVICE` (default: cpu)\n"
            "- `VOICE_ASR_COMPUTE_TYPE` (default: int8)"
        )
