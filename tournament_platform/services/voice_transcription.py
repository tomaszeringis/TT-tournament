"""
Voice Transcription Service for Operator Commands

Provides offline speech-to-text for operator commands using Vosk.
Vosk is optional - the app will work without it and show setup instructions.
"""

import os
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Vosk model path (downloaded separately)
VOSK_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "model")


def is_vosk_available() -> bool:
    """
    Check if Vosk is available and model is downloaded.
    
    Returns:
        True if Vosk can be used, False otherwise.
    """
    try:
        # Guarded import - only import when needed
        from vosk import Model, KaldiRecognizer  # noqa: F401
        if os.path.exists(VOSK_MODEL_PATH):
            return True
        logger.warning(f"Vosk model not found at {VOSK_MODEL_PATH}")
        return False
    except ImportError:
        logger.warning("Vosk not installed. Install with: pip install vosk")
        return False


def get_vosk_setup_instructions() -> str:
    """
    Get setup instructions for Vosk when it's not available.
    
    Returns:
        Human-readable setup instructions.
    """
    return """
    **Vosk Voice Recognition Setup Required**
    
    To enable offline voice commands:
    
    1. Install Vosk: `pip install vosk`
    2. Download a model from https://alphacephei.com/vosk/models
    3. Extract the model to a directory (e.g., `model/`)
    4. Set environment variable: `VOSK_MODEL_PATH=model`
    
    Or place the model in the default `model/` directory.
    
    Without Vosk, you can still use text commands in the Command Bar.
    """


def transcribe_wav_bytes(audio_bytes: bytes, sample_rate: int = 16000) -> Tuple[Optional[str], Optional[str]]:
    """
    Transcribe WAV audio bytes to text using Vosk.
    
    Args:
        audio_bytes: Raw WAV audio data (16-bit mono PCM)
        sample_rate: Audio sample rate (default 16000)
    
    Returns:
        Tuple of (transcribed_text, error_message).
        - If successful: (text, None)
        - If Vosk unavailable: (None, "Vosk not available...")
        - If transcription fails: (None, "Transcription error...")
    """
    if not is_vosk_available():
        return None, f"Vosk not available. {get_vosk_setup_instructions()}"
    
    try:
        from vosk import Model, KaldiRecognizer
        import json
        
        model = Model(VOSK_MODEL_PATH)
        recognizer = KaldiRecognizer(model, sample_rate)
        
        # Process audio
        if recognizer.AcceptWaveform(audio_bytes):
            result = json.loads(recognizer.FinalResult())
            text = result.get("text", "").strip()
            return text if text else None, None
        else:
            # Partial result - still processing
            partial = json.loads(recognizer.PartialResult())
            text = partial.get("partial", "").strip()
            return text if text else None, None
            
    except Exception as e:
        error_msg = f"Transcription error: {e}"
        logger.error(error_msg)
        return None, error_msg


def get_voice_command_interface() -> dict:
    """
    Get the voice command interface configuration.
    
    Returns:
        Dict with voice command settings and availability.
    """
    return {
        "available": is_vosk_available(),
        "model_path": VOSK_MODEL_PATH,
        "sample_rate": 16000,
        "setup_instructions": get_vosk_setup_instructions() if not is_vosk_available() else None,
        "commands": [
            "call <player1> vs <player2>",
            "call <player1> vs <player2> to table <n>",
            "start <player1> vs <player2>",
            "complete <player1> vs <player2>",
            "delay <player1> vs <player2> for <n> minutes",
            "reschedule <player1> vs <player2> to table <n> at <time>",
            "path <player_name>",
            "tables",
        ],
    }