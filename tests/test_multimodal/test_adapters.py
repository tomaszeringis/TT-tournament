"""
Tests for dataset adapters.
"""

import pytest
import tempfile
from pathlib import Path

from tournament_platform.multimodal_ai.adapters import (
    CommonVoiceAdapter,
    GigaSpeechAdapter,
    AMIAdapter,
    FluentCommandsAdapter,
    ASVspoofAdapter,
    T3SetAdapter,
    OpenTTGamesAdapter,
    BlurBallAdapter,
    TTSwingAdapter,
    TT3DAdapter,
)


class TestCommonVoiceAdapter:
    """Tests for CommonVoiceAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = CommonVoiceAdapter("mozilla_common_voice", "/tmp/data")
        assert adapter.dataset_id == "mozilla_common_voice"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = CommonVoiceAdapter("mozilla_common_voice", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.dataset_id == "mozilla_common_voice"
        assert info.name == "Mozilla Common Voice"
        assert info.modality == "audio"
        assert info.task == "asr"
        assert info.license == "cc0"
        assert info.commercial_allowed is True
    
    def test_validate_local_path_no_path(self):
        """Test validation fails without path."""
        adapter = CommonVoiceAdapter("mozilla_common_voice")
        assert adapter.validate_local_path() is False
    
    def test_list_samples_empty(self):
        """Test list samples returns empty without path."""
        adapter = CommonVoiceAdapter("mozilla_common_voice")
        samples = adapter.list_samples()
        assert samples == []


class TestGigaSpeechAdapter:
    """Tests for GigaSpeechAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = GigaSpeechAdapter("gigaspeech", "/tmp/data")
        assert adapter.dataset_id == "gigaspeech"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = GigaSpeechAdapter("gigaspeech", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "GigaSpeech"
        assert info.modality == "audio"
        assert info.task == "asr"
        assert info.license == "apache"
        assert info.commercial_allowed is True


class TestAMIAdapter:
    """Tests for AMIAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = AMIAdapter("ami_meeting", "/tmp/data")
        assert adapter.dataset_id == "ami_meeting"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = AMIAdapter("ami_meeting", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "AMI Meeting Corpus"
        assert info.modality == "audio"
        assert info.task == "asr"
        assert info.license == "cc_by"


class TestFluentCommandsAdapter:
    """Tests for FluentCommandsAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = FluentCommandsAdapter("fluent_commands", "/tmp/data")
        assert adapter.dataset_id == "fluent_commands"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = FluentCommandsAdapter("fluent_commands", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "Fluent Speech Commands"
        assert info.modality == "audio"
        assert info.task == "intent"
        assert info.license == "mit"


class TestASVspoofAdapter:
    """Tests for ASVspoofAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = ASVspoofAdapter("asvspoof_2021", "/tmp/data")
        assert adapter.dataset_id == "asvspoof_2021"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = ASVspoofAdapter("asvspoof_2021", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "ASVspoof 2021"
        assert info.modality == "audio"
        assert info.task == "anti_spoof"


class TestT3SetAdapter:
    """Tests for T3SetAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = T3SetAdapter("t3set", "/tmp/data")
        assert adapter.dataset_id == "t3set"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = T3SetAdapter("t3set", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "T3Set"
        assert info.modality == "video"
        assert info.task == "stroke_classification"
        assert info.license == "non_commercial"
        assert info.commercial_allowed is False


class TestOpenTTGamesAdapter:
    """Tests for OpenTTGamesAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = OpenTTGamesAdapter("openttgames", "/tmp/data")
        assert adapter.dataset_id == "openttgames"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = OpenTTGamesAdapter("openttgames", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "OpenTTGames"
        assert info.modality == "video"
        assert info.task == "ball_detection"
        assert info.license == "non_commercial"


class TestBlurBallAdapter:
    """Tests for BlurBallAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = BlurBallAdapter("blurball", "/tmp/data")
        assert adapter.dataset_id == "blurball"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = BlurBallAdapter("blurball", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "BlurBall"
        assert info.modality == "video"
        assert info.task == "ball_detection"
        assert info.license == "mit"


class TestTTSwingAdapter:
    """Tests for TTSwingAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = TTSwingAdapter("ttswing", "/tmp/data")
        assert adapter.dataset_id == "ttswing"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = TTSwingAdapter("ttswing", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "TTSwing"
        assert info.modality == "sensor"
        assert info.task == "stroke_classification"


class TestTT3DAdapter:
    """Tests for TT3DAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        adapter = TT3DAdapter("tt3d", "/tmp/data")
        assert adapter.dataset_id == "tt3d"
    
    def test_get_dataset_info(self):
        """Test dataset info is correct."""
        adapter = TT3DAdapter("tt3d", "/tmp/data")
        info = adapter.get_dataset_info()
        
        assert info.name == "TT3D"
        assert info.modality == "trajectory"
        assert info.task == "trajectory_reconstruction"