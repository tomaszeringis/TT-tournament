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
from typing import Optional

from tournament_platform.app.services.voice_vocab import VoiceVocabulary
from tournament_platform.app.services.voice.hf_token import apply_hf_token, get_hf_token
from tournament_platform.app.services.voice.asr_diagnostics import get_voice_setting

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
    ):
        """
        Initialize the LocalASR wrapper.
        
        Args:
            model_size: Whisper model size (e.g., "base.en", "small.en")
            device: Device to run on ("cpu", "cuda", "auto")
            compute_type: Compute type ("int8", "float16", "float32")
            vocabulary: Optional VoiceVocabulary for biasing/post-processing.
        """
        # Read from env/secrets with optional constructor overrides.
        # get_voice_setting honors Streamlit Cloud secrets (which are NOT
        # injected into os.environ), so ASR config works on Streamlit Cloud.
        self.model_size = model_size or get_voice_setting("VOICE_ASR_MODEL_SIZE", "tiny.en")
        self.device = device or get_voice_setting("VOICE_ASR_DEVICE", "cpu")
        self.compute_type = compute_type or get_voice_setting("VOICE_ASR_COMPUTE_TYPE", "int8")
        self.vocabulary = vocabulary or VoiceVocabulary.load()
        
        # Lazy-loaded model (shared via module-level cache)
        self._model = None
        self._load_lock = threading.Lock()
        self._load_attempted = False
        self._load_failed = False
        self._load_error: Optional[str] = None
    
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
            # Write audio to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                with wave.open(f, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(16000)
                    wf.writeframes(audio_bytes)
                temp_path = f.name
            
            try:
                # Build transcription kwargs
                transcribe_kwargs: dict[str, Any] = {
                    "beam_size": 5,
                    "language": "en",
                    "condition_on_previous_text": False,
                }
                
                # Apply vocabulary biasing via initial_prompt if available
                initial_prompt = self.vocabulary.get_initial_prompt()
                if initial_prompt:
                    transcribe_kwargs["initial_prompt"] = initial_prompt
                
                # Transcribe with faster-whisper
                segments, info = self._model.transcribe(temp_path, **transcribe_kwargs)
                
                # Combine all segments
                text = " ".join(seg.text for seg in segments).strip()
                
                logger.debug(
                    "Transcribed %d samples in %.2fs: %s",
                    len(audio_bytes) // 2,  # 16-bit samples
                    info.duration,
                    text,
                )
                
                return text
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                    
        except Exception as e:
            logger.error("Transcription error: %s", e)
            return ""
    
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
