"""
Tests for dataset manifest and validation.
"""

import pytest
import tempfile
import os
from pathlib import Path

import yaml


def load_manifest():
    """Load the dataset manifest."""
    manifest_path = Path(__file__).parent.parent.parent / "tournament_platform" / "multimodal_ai" / "manifests" / "datasets.yaml"
    
    if not manifest_path.exists():
        # Try alternate location
        manifest_path = Path(__file__).parent.parent.parent / "tournament_platform" / "data" / "datasets" / "manifest.yaml"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestManifestLoading:
    """Tests for manifest loading."""
    
    def test_manifest_loads_successfully(self):
        """Test that the manifest can be loaded."""
        manifest = load_manifest()
        assert manifest is not None
        assert "datasets" in manifest
    
    def test_datasets_section_exists(self):
        """Test that datasets section exists."""
        manifest = load_manifest()
        assert "datasets" in manifest
        assert len(manifest["datasets"]) > 0
    
    def test_presets_section_exists(self):
        """Test that presets section exists."""
        manifest = load_manifest()
        assert "presets" in manifest
        assert len(manifest["presets"]) > 0


class TestRequiredDatasetIds:
    """Tests for required dataset IDs."""
    
    def test_voice_core_datasets_exist(self):
        """Test that voice core dataset IDs exist."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        required_voice = ["common_voice", "gigaspeech", "ami", "fluent_speech_commands", "asvspoof2021"]
        for dataset_id in required_voice:
            assert dataset_id in datasets, f"Missing dataset: {dataset_id}"
    
    def test_table_tennis_core_datasets_exist(self):
        """Test that table tennis core dataset IDs exist."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        required_tt = ["t3set", "openttgames", "extended_openttgames", "blurball", "ttswing", "tt3d"]
        for dataset_id in required_tt:
            assert dataset_id in datasets, f"Missing dataset: {dataset_id}"
    
    def test_optional_datasets_exist(self):
        """Test that optional dataset IDs exist."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        optional = ["p2anet", "racketvision", "ttst", "voxceleb2", "iemocap", "audioset", "soccernet_echoes"]
        for dataset_id in optional:
            assert dataset_id in datasets, f"Missing optional dataset: {dataset_id}"


class TestPresets:
    """Tests for dataset combination presets."""
    
    def test_voice_core_preset_valid(self):
        """Test that voice_core preset references valid datasets."""
        manifest = load_manifest()
        presets = manifest["presets"]
        datasets = manifest["datasets"]
        
        assert "voice_core" in presets
        for dataset_id in presets["voice_core"]:
            assert dataset_id in datasets, f"Invalid dataset in voice_core: {dataset_id}"
    
    def test_tt_perception_core_preset_valid(self):
        """Test that tt_perception_core preset references valid datasets."""
        manifest = load_manifest()
        presets = manifest["presets"]
        datasets = manifest["datasets"]
        
        assert "tt_perception_core" in presets
        for dataset_id in presets["tt_perception_core"]:
            assert dataset_id in datasets, f"Invalid dataset in tt_perception_core: {dataset_id}"
    
    def test_coaching_core_preset_valid(self):
        """Test that coaching_core preset references valid datasets."""
        manifest = load_manifest()
        presets = manifest["presets"]
        datasets = manifest["datasets"]
        
        assert "coaching_core" in presets
        for dataset_id in presets["coaching_core"]:
            assert dataset_id in datasets, f"Invalid dataset in coaching_core: {dataset_id}"
    
    def test_commercial_safe_baseline_preset_valid(self):
        """Test that commercial_safe_baseline preset references valid datasets."""
        manifest = load_manifest()
        presets = manifest["presets"]
        datasets = manifest["datasets"]
        
        assert "commercial_safe_baseline" in presets
        for dataset_id in presets["commercial_safe_baseline"]:
            assert dataset_id in datasets, f"Invalid dataset in commercial_safe_baseline: {dataset_id}"
    
    def test_research_full_preset_valid(self):
        """Test that research_full preset references valid datasets."""
        manifest = load_manifest()
        presets = manifest["presets"]
        datasets = manifest["datasets"]
        
        assert "research_full" in presets
        for dataset_id in presets["research_full"]:
            assert dataset_id in datasets, f"Invalid dataset in research_full: {dataset_id}"


class TestLicenseGates:
    """Tests for license gate behavior."""
    
    def test_non_commercial_datasets_flagged(self):
        """Test that non-commercial datasets are flagged correctly."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        non_commercial = ["t3set", "openttgames", "extended_openttgames"]
        for dataset_id in non_commercial:
            assert datasets[dataset_id]["license"] in ["non_commercial", "research_only"]
            assert datasets[dataset_id]["commercial_allowed"] is False
    
    def test_unknown_license_datasets_flagged(self):
        """Test that unknown license datasets are flagged correctly."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        unknown_license = ["p2anet", "racketvision", "ttst", "voxceleb2", "iemocap", "audioset", "soccernet_echoes"]
        for dataset_id in unknown_license:
            assert datasets[dataset_id]["license"] == "unknown"
            assert datasets[dataset_id]["commercial_allowed"] is False
    
    def test_commercial_safe_datasets_flagged(self):
        """Test that commercial-safe datasets are flagged correctly."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        commercial_safe = ["common_voice", "gigaspeech", "ami", "blurball", "ttswing", "tt3d"]
        for dataset_id in commercial_safe:
            assert datasets[dataset_id]["commercial_allowed"] is True


class TestEnvironmentPathResolution:
    """Tests for environment path resolution."""
    
    def test_path_template_resolution(self):
        """Test that path templates can be resolved."""
        manifest = load_manifest()
        
        for dataset_id, dataset_info in manifest["datasets"].items():
            path = dataset_info.get("recommended_local_path", "")
            if path:
                # Check that template contains expected variable
                assert "${TT_RAW_DATA_DIR}" in path or path.startswith("/") or path.startswith("D:/") or path.startswith("../")
    
    def test_dataset_has_required_fields(self):
        """Test that each dataset has required fields."""
        manifest = load_manifest()
        datasets = manifest["datasets"]
        
        required_fields = ["dataset_id", "name", "domain", "modality", "primary_task", "priority", "license", "commercial_allowed"]
        
        for dataset_id, dataset_info in datasets.items():
            for field in required_fields:
                assert field in dataset_info, f"Missing field '{field}' in dataset '{dataset_id}'"