"""
Tests for voice_transcription service.

These tests verify that:
1. Vosk availability is checked without breaking imports
2. Transcription returns helpful errors when Vosk is missing
3. The service works gracefully without actual Vosk model in CI
"""

import pytest
from unittest.mock import patch, MagicMock


class TestVoskAvailability:
    """Test Vosk availability detection."""

    def test_is_vosk_available_returns_false_when_model_missing(self):
        """Test that is_vosk_available returns False when model is missing."""
        # Import the module fresh
        from tournament_platform.services import voice_transcription as vt
        
        # Patch os.path.exists to return False (model not found)
        with patch('os.path.exists', return_value=False):
            result = vt.is_vosk_available()
            assert result is False

    def test_get_vosk_setup_instructions_returns_helpful_text(self):
        """Test that setup instructions are returned as helpful text."""
        from tournament_platform.services import voice_transcription as vt
        
        instructions = vt.get_vosk_setup_instructions()
        
        assert "Vosk" in instructions
        assert "pip install vosk" in instructions
        assert "VOSK_MODEL_PATH" in instructions


class TestTranscribeWavBytes:
    """Test WAV transcription functionality."""

    def test_transcribe_wav_bytes_returns_error_when_vosk_unavailable(self):
        """Test that transcription returns error tuple when Vosk is unavailable."""
        from tournament_platform.services import voice_transcription as vt
        
        # Mock is_vosk_available to return False
        with patch.object(vt, 'is_vosk_available', return_value=False):
            text, error = vt.transcribe_wav_bytes(b"fake audio data")
            
            assert text is None
            assert error is not None
            assert "Vosk not available" in error

    def test_transcribe_wav_bytes_handles_empty_text(self):
        """Test that transcription handles empty text gracefully."""
        from tournament_platform.services import voice_transcription as vt
        
        with patch.object(vt, 'is_vosk_available', return_value=True):
            with patch('tournament_platform.services.voice_transcription.VOSK_MODEL_PATH', 'model'):
                with patch('os.path.exists', return_value=True):
                    # Mock the vosk module
                    mock_model = MagicMock()
                    mock_recognizer = MagicMock()
                    mock_recognizer.FinalResult.return_value = '{"text": ""}'
                    mock_recognizer.AcceptWaveform.return_value = True
                    
                    with patch.dict('sys.modules', {'vosk': MagicMock(Model=mock_model, KaldiRecognizer=lambda m, sr: mock_recognizer)}):
                        text, error = vt.transcribe_wav_bytes(b"")
                        
                        # Empty text should return None
                        assert text is None
                        assert error is None

    def test_transcribe_wav_bytes_returns_text_on_success(self):
        """Test that transcription returns text on successful recognition."""
        from tournament_platform.services import voice_transcription as vt
        
        with patch.object(vt, 'is_vosk_available', return_value=True):
            with patch('tournament_platform.services.voice_transcription.VOSK_MODEL_PATH', 'model'):
                with patch('os.path.exists', return_value=True):
                    # Mock the vosk module
                    mock_model = MagicMock()
                    mock_recognizer = MagicMock()
                    mock_recognizer.FinalResult.return_value = '{"text": "call match 1 to table 2"}'
                    mock_recognizer.AcceptWaveform.return_value = True
                    
                    with patch.dict('sys.modules', {'vosk': MagicMock(Model=mock_model, KaldiRecognizer=lambda m, sr: mock_recognizer)}):
                        text, error = vt.transcribe_wav_bytes(b"fake audio")
                        
                        assert text == "call match 1 to table 2"
                        assert error is None


class TestVoiceCommandInterface:
    """Test voice command interface configuration."""

    def test_get_voice_command_interface_returns_config(self):
        """Test that interface config is returned correctly."""
        from tournament_platform.services import voice_transcription as vt
        
        config = vt.get_voice_command_interface()
        
        assert "available" in config
        assert "model_path" in config
        assert "sample_rate" in config
        assert "commands" in config
        assert isinstance(config["commands"], list)
        assert len(config["commands"]) > 0

    def test_get_voice_command_interface_includes_setup_instructions_when_unavailable(self):
        """Test that setup instructions are included when Vosk is unavailable."""
        from tournament_platform.services import voice_transcription as vt
        
        with patch.object(vt, 'is_vosk_available', return_value=False):
            config = vt.get_voice_command_interface()
            
            assert config["available"] is False
            assert config["setup_instructions"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])