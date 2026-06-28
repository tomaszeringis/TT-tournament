"""
Vosk Voice Adapter for Operator Commands

Provides offline speech-to-text for operator commands.
Uses Vosk for local voice recognition without network dependencies.
"""

import os
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Vosk model path (downloaded separately)
VOSK_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "model")


def is_vosk_available() -> bool:
    """Check if Vosk is available and model is downloaded."""
    try:
        from vosk import Model, KaldiRecognizer
        if os.path.exists(VOSK_MODEL_PATH):
            return True
        logger.warning(f"Vosk model not found at {VOSK_MODEL_PATH}")
        return False
    except ImportError:
        logger.warning("Vosk not installed. Install with: pip install vosk")
        return False


def transcribe_audio(audio_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
    """
    Transcribe audio bytes to text using Vosk.
    
    Args:
        audio_bytes: Raw audio data (16-bit mono PCM)
        sample_rate: Audio sample rate (default 16000)
    
    Returns:
        Transcribed text or None if transcription fails.
    """
    if not is_vosk_available():
        return None
    
    try:
        from vosk import Model, KaldiRecognizer
        import json
        
        model = Model(VOSK_MODEL_PATH)
        recognizer = KaldiRecognizer(model, sample_rate)
        
        # Process audio in chunks
        recognizer.AcceptWaveform(audio_bytes)
        result = json.loads(recognizer.FinalResult())
        
        return result.get("text", "").strip() or None
    
    except Exception as e:
        logger.error(f"Vosk transcription error: {e}")
        return None


def get_voice_command_interface() -> Dict[str, Any]:
    """
    Get the voice command interface configuration.
    
    Returns:
        Dict with voice command settings and availability.
    """
    return {
        "available": is_vosk_available(),
        "model_path": VOSK_MODEL_PATH,
        "sample_rate": 16000,
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


# For testing without actual audio
def mock_transcribe(text: str) -> str:
    """Mock transcription for testing purposes."""
    return text