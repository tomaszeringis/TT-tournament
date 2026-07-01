"""Tests for the Dataset Registry."""

import pytest
import tempfile
import os
from pathlib import Path

from tournament_platform.multimodal_ai.dataset_registry import (
    DatasetRegistry,
    DatasetInfo,
    LicenseType,
    Modality,
    Task,
    DATASET_COMBINATIONS,
    DEFAULT_MANIFEST,
)


class TestDatasetInfo:
    """Tests for DatasetInfo dataclass."""

    def test_dataset_info_creation(self):
        """Test creating a DatasetInfo instance."""
        info = DatasetInfo(
            dataset_id="test_dataset",
            name="Test Dataset",
            modality=Modality.AUDIO,
            task=Task.ASR,
            license=LicenseType.CC0,
            commercial_allowed=True,
            source_url="https://example.com",
        )
        
        assert info.dataset_id == "test_dataset"
        assert info.name == "Test Dataset"
        assert info.modality == Modality.AUDIO
        assert info.task == Task.ASR
        assert info.commercial_allowed is True

    def test_dataset_info_to_dict(self):
        """Test converting DatasetInfo to dictionary."""
        info = DatasetInfo(
            dataset_id="test_dataset",
            name="Test Dataset",
            modality=Modality.AUDIO,
            task=Task.ASR,
            license=LicenseType.CC0,
            commercial_allowed=True,
            source_url="https://example.com",
            notes="Test notes",
        )
        
        result = info.to_dict()
        
        assert result["dataset_id"] == "test_dataset"
        assert result["name"] == "Test Dataset"
        assert result["modality"] == "audio"
        assert result["task"] == "asr"
        assert result["license"] == "cc0"
        assert result["commercial_allowed"] is True
        assert result["notes"] == "Test notes"


class TestDatasetRegistry:
    """Tests for DatasetRegistry class."""

    def test_default_manifest_loading(self):
        """Test that default manifest loads correctly."""
        registry = DatasetRegistry()
        
        # Should have loaded all default datasets
        assert len(registry.list_datasets()) > 0
        
        # Check specific datasets exist
        assert registry.get_dataset("mozilla_common_voice") is not None
        assert registry.get_dataset("t3set") is not None
        assert registry.get_dataset("openttgames") is not None

    def test_get_dataset(self):
        """Test retrieving a dataset by ID."""
        registry = DatasetRegistry()
        
        dataset = registry.get_dataset("mozilla_common_voice")
        assert dataset is not None
        assert dataset.name == "Mozilla Common Voice"
        assert dataset.commercial_allowed is True

    def test_list_datasets_by_modality(self):
        """Test filtering datasets by modality."""
        registry = DatasetRegistry()
        
        audio_datasets = registry.list_datasets_by_modality(Modality.AUDIO)
        assert len(audio_datasets) > 0
        for ds in audio_datasets:
            assert ds.modality == Modality.AUDIO

    def test_list_datasets_by_task(self):
        """Test filtering datasets by task."""
        registry = DatasetRegistry()
        
        asr_datasets = registry.list_datasets_by_task(Task.ASR)
        assert len(asr_datasets) > 0
        for ds in asr_datasets:
            assert ds.task == Task.ASR

    def test_get_combination(self):
        """Test retrieving dataset combination."""
        registry = DatasetRegistry()
        
        voice_core = registry.get_combination("voice_core")
        assert len(voice_core) > 0
        
        # All should be audio modality
        for ds in voice_core:
            assert ds.modality == Modality.AUDIO

    def test_validate_license_commercial(self):
        """Test license validation for commercial datasets."""
        registry = DatasetRegistry()
        
        # CC0 dataset should pass
        assert registry.validate_license("mozilla_common_voice", allow_non_commercial=False) is True
        
        # Non-commercial dataset should fail
        assert registry.validate_license("t3set", allow_non_commercial=False) is False

    def test_validate_license_non_commercial(self):
        """Test license validation with non-commercial flag."""
        registry = DatasetRegistry()
        
        # Non-commercial dataset should pass with flag
        assert registry.validate_license("t3set", allow_non_commercial=True) is True

    def test_validate_combination(self):
        """Test validating a combination of datasets."""
        registry = DatasetRegistry()
        
        # Voice core combination should pass (all commercial allowed)
        result = registry.validate_combination("voice_core", allow_non_commercial=False)
        assert all(result.values()) is True
        
        # Research combination should have some failures
        result = registry.validate_combination("research_full", allow_non_commercial=False)
        # Check that not all pass (some are non-commercial)
        assert not all(result.values())

    def test_get_non_commercial_datasets(self):
        """Test getting non-commercial datasets."""
        registry = DatasetRegistry()
        
        non_commercial = registry.get_non_commercial_datasets()
        assert len(non_commercial) > 0
        
        for ds in non_commercial:
            assert ds.commercial_allowed is False

    def test_get_commercial_safe_datasets(self):
        """Test getting commercial-safe datasets."""
        registry = DatasetRegistry()
        
        commercial_safe = registry.get_commercial_safe_datasets()
        assert len(commercial_safe) > 0
        
        for ds in commercial_safe:
            assert ds.commercial_allowed is True

    def test_save_and_load_manifest(self):
        """Test saving and loading manifest from file."""
        registry = DatasetRegistry()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "test_manifest.yaml")
            registry.save_manifest(manifest_path)
            
            assert os.path.exists(manifest_path)
            
            # Load into new registry
            new_registry = DatasetRegistry(manifest_path)
            assert len(new_registry.list_datasets()) == len(registry.list_datasets())


class TestDatasetCombinations:
    """Tests for dataset combination presets."""

    def test_combination_exists(self):
        """Test that all expected combinations exist."""
        assert "voice_core" in DATASET_COMBINATIONS
        assert "tt_perception_core" in DATASET_COMBINATIONS
        assert "coaching_core" in DATASET_COMBINATIONS
        assert "research_full" in DATASET_COMBINATIONS
        assert "commercial_safe_baseline" in DATASET_COMBINATIONS

    def test_combination_contents(self):
        """Test that combinations have expected datasets."""
        voice_core = DATASET_COMBINATIONS["voice_core"]
        assert "mozilla_common_voice" in voice_core
        assert "gigaspeech" in voice_core
        
        # Research full should include all
        research_full = DATASET_COMBINATIONS["research_full"]
        assert len(research_full) == len(DEFAULT_MANIFEST["datasets"])