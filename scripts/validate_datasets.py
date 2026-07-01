#!/usr/bin/env python
"""
Dataset validation script for the Multimodal AI system.

This script validates dataset availability and license compliance without downloading anything.

Usage:
    python scripts/validate_datasets.py --preset voice_core
    python scripts/validate_datasets.py --preset tt_perception_core
    python scripts/validate_datasets.py --preset coaching_core
    python scripts/validate_datasets.py --all
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tournament_platform.config import settings


def load_manifest() -> Dict[str, Any]:
    """Load the dataset manifest."""
    manifest_path = Path(__file__).parent.parent / "tournament_platform" / "multimodal_ai" / "manifests" / "datasets.yaml"
    
    if not manifest_path.exists():
        # Try alternate location
        manifest_path = Path(__file__).parent.parent / "tournament_platform" / "data" / "datasets" / "manifest.yaml"
    
    if not manifest_path.exists():
        raise FileNotFoundError(f"Dataset manifest not found at {manifest_path}")
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(path_template: str) -> str:
    """Resolve environment variable placeholders in path templates."""
    result = path_template
    for key, value in {
        "TT_RAW_DATA_DIR": settings.TT_RAW_DATA_DIR,
        "TT_DATA_ROOT": settings.TT_DATA_ROOT,
    }.items():
        result = result.replace(f"${{{key}}}", value)
    return result


def validate_dataset(dataset_id: str, dataset_info: Dict[str, Any]) -> Dict[str, str]:
    """Validate a single dataset and return status."""
    local_path = dataset_info.get("recommended_local_path", "")
    resolved_path = resolve_path(local_path) if local_path else ""
    
    path_exists = Path(resolved_path).exists() if resolved_path else False
    license_type = dataset_info.get("license", "unknown")
    commercial_allowed = dataset_info.get("commercial_allowed", False)
    
    if not path_exists:
        return {"status": "MISSING", "path": resolved_path}
    
    if license_type in ["non_commercial", "research_only"]:
        return {"status": "LICENSE_RESTRICTED", "path": resolved_path}
    
    if license_type == "unknown":
        return {"status": "COMMERCIAL_UNKNOWN", "path": resolved_path}
    
    return {"status": "FOUND", "path": resolved_path}


def main():
    parser = argparse.ArgumentParser(description="Validate dataset availability")
    parser.add_argument("--preset", type=str, help="Preset to validate (e.g., voice_core)")
    parser.add_argument("--all", action="store_true", help="Validate all datasets")
    parser.add_argument("--list-presets", action="store_true", help="List available presets")
    
    args = parser.parse_args()
    
    manifest = load_manifest()
    
    if args.list_presets:
        print("Available presets:")
        for preset_name in manifest.get("presets", {}).keys():
            print(f"  - {preset_name}")
        return 0
    
    if not args.preset and not args.all:
        parser.print_help()
        return 1
    
    datasets = manifest.get("datasets", {})
    presets = manifest.get("presets", {})
    
    if args.preset:
        if args.preset not in presets:
            print(f"Error: Unknown preset '{args.preset}'")
            print("Available presets: " + ", ".join(presets.keys()))
            return 1
        
        dataset_ids = presets[args.preset]
        print(f"\nValidating preset: {args.preset}")
        print(f"Dataset IDs: {', '.join(dataset_ids)}\n")
    else:
        dataset_ids = list(datasets.keys())
        print(f"\nValidating all {len(dataset_ids)} datasets\n")
    
    # Validate each dataset
    results = []
    missing_required = False
    
    for dataset_id in dataset_ids:
        if dataset_id not in datasets:
            print(f"  WARNING: Dataset '{dataset_id}' not found in manifest")
            continue
        
        dataset_info = datasets[dataset_id]
        result = validate_dataset(dataset_id, dataset_info)
        results.append((dataset_id, result))
        
        status = result["status"]
        path = result["path"]
        
        if status == "MISSING":
            print(f"  [MISSING] {dataset_id} -> {path}")
            missing_required = True
        elif status == "LICENSE_RESTRICTED":
            print(f"  [LICENSE_RESTRICTED] {dataset_id} -> {path}")
        elif status == "COMMERCIAL_UNKNOWN":
            print(f"  [COMMERCIAL_UNKNOWN] {dataset_id} -> {path}")
        else:
            print(f"  [FOUND] {dataset_id} -> {path}")
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    
    found = sum(1 for _, r in results if r["status"] == "FOUND")
    missing = sum(1 for _, r in results if r["status"] == "MISSING")
    restricted = sum(1 for _, r in results if r["status"] == "LICENSE_RESTRICTED")
    unknown = sum(1 for _, r in results if r["status"] == "COMMERCIAL_UNKNOWN")
    
    print(f"  Found: {found}")
    print(f"  Missing: {missing}")
    print(f"  License Restricted: {restricted}")
    print(f"  Commercial Unknown: {unknown}")
    
    if missing_required:
        print("\nError: Required datasets are missing!")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())