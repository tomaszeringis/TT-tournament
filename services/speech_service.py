import asyncio
import os
import tempfile
import audioop
import speech_recognition as sr
from faster_whisper import WhisperModel

class SpeechReporter:
    def __init__(self, model_size="base"):
        # Run on CPU by default for broader compatibility, can be changed to "cuda" if GPU is available
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe_audio(self, audio_file_path: str) -> str:
        """Transcribe audio file using faster-whisper."""
        if not os.path.exists(audio_file_path):
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")
        
        segments, info = self.model.transcribe(audio_file_path, beam_size=5)
        
        transcribed_text = ""
        for segment in segments:
            transcribed_text += segment.text + " "
            
        return transcribed_text.strip()

async def record_audio() -> str:
    """Capture audio from microphone for 5 seconds and save to a temporary file."""
    recognizer = sr.Recognizer()
    
    with sr.Microphone() as source:
        # Adjust for ambient noise
        recognizer.adjust_for_ambient_noise(source, duration=1)
        try:
            # record for 5 seconds
            audio_data = recognizer.record(source, duration=5)
        except Exception as e:
            raise RuntimeError(f"Failed to record audio: {e}")

    # Check if any audio was detected (non-silent)
    if not audio_data:
        raise ValueError("No audio data captured.")
        
    # Check energy level to detect silence
    rms = audioop.rms(audio_data.get_raw_data(), audio_data.sample_width)
    if rms < 100:  # Threshold for silence, might need adjustment
        raise ValueError("No audio detected (it was silent).")

    # Save to a temporary WAV file
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(audio_data.get_wav_data())
    except Exception as e:
        os.remove(path)
        raise RuntimeError(f"Failed to save temporary audio file: {e}")

    return path
