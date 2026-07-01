#!/usr/bin/env python3
"""
Dataset download script for TT-tournament multimodal AI system.

This script provides download commands for all recommended datasets.
Note: Some datasets require registration or have specific license terms.

Usage:
    python scripts/download_datasets.py --preset voice_core
    python scripts/download_datasets.py --preset tt_perception_core
    python scripts/download_datasets.py --preset coaching_core
    python scripts/download_datasets.py --all
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Dataset download commands
DATASET_DOWNLOADS = {
    "common_voice": {
        "url": "https://commonvoice.mozilla.org/en/datasets",
        "note": "Requires account registration. Download manually from website.",
        "size": "~100GB+",
    },
    "gigaspeech": {
        "url": "https://openslr.org/106/",
        "note": "Available via OpenSLR. Use download script from website.",
        "size": "~200GB",
    },
    "ami": {
        "url": "https://groups.inf.ed.ac.uk/ami/AMIdata/download.shtml",
        "note": "Requires license agreement. Use download script from website.",
        "size": "~100GB",
    },
    "fluent_commands": {
        "url": "https://github.com/thomashk000/fluent_speech_commands_dataset",
        "note": "Available on GitHub. Clone the repository.",
        "size": "~100MB",
    },
    "asvspoof": {
        "url": "https://www.asvspoof.org/",
        "note": "Requires registration for ASVspoof 2021.",
        "size": "~10GB",
    },
    "t3set": {
        "url": "https://zenodo.org/record/XXXXXXX",
        "note": "RESEARCH-ONLY LICENSE. Contact authors for access.",
        "size": "~50GB",
    },
    "openttgames": {
        "url": "https://github.com/zhenghuipeng/OpenTTGames",
        "note": "Check license terms. May require registration.",
        "size": "~20GB",
    },
    "blurball": {
        "url": "https://github.com/zhenghuipeng/BlurBall",
        "note": "Check license terms. May require registration.",
        "size": "~10GB",
    },
    "ttswing": {
        "url": "https://github.com/zhenghuipeng/TTSwing",
        "note": "Check license terms. May require registration.",
        "size": "~5GB",
    },
    "tt3d": {
        "url": "https://github.com/zhenghuipeng/TT3D",
        "note": "Check license terms. May require registration.",
        "size": "~15GB",
    },
}

PRESETS = {
    "voice_core": ["common_voice", "gigaspeech", "ami", "fluent_commands"],
    "tt_perception_core": ["openttgames", "blurball", "ttswing"],
    "coaching_core": ["t3set", "openttgames"],
    "research_full": list(DATASET_DOWNLOADS.keys()),
    "commercial_safe_baseline": ["common_voice", "gigaspeech", "openttgames", "blurball", "ttswing"],
}


def print_download_info(dataset_id: str):
    """Print download information for a dataset."""
    info = DATASET_DOWNLOADS.get(dataset_id)
    if not info:
        print(f"Unknown dataset: {dataset_id}")
        return
    
    print(f"\n{'='*60}")
    print(f"Dataset: {dataset_id}")
    print(f"{'='*60}")
    print(f"URL: {info['url']}")
    print(f"Size: {info['size']}")
    print(f"Note: {info['note']}")
    print()


def download_preset(preset: str, data_root: Path):
    """Print download instructions for a preset."""
    datasets = PRESETS.get(preset)
    if not datasets:
        print(f"Unknown preset: {preset}")
        return
    
    print(f"\n{'#'*60}")
    print(f"Downloading preset: {preset}")
    print(f"{'#'*60}")
    
    for dataset_id in datasets:
        print_download_info(dataset_id)
        
        # Create directory structure
        raw_path = data_root / "raw" / "table_tennis" / dataset_id
        processed_path = data_root / "processed" / "table_tennis" / dataset_id
        
        raw_path.mkdir(parents=True, exist_ok=True)
        processed_path.mkdir(parents=True, exist_ok=True)
        
        print(f"Created directories:")
        print(f"  - {raw_path}")
        print(f"  - {processed_path}")


def main():
    parser = argparse.ArgumentParser(description="Download datasets for TT-tournament multimodal AI")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), help="Download a preset combination")
    parser.add_argument("--all", action="store_true", help="Show info for all datasets")
    parser.add_argument("--data-root", default="tt_ai_data", help="Root directory for datasets")
    
    args = parser.parse_args()
    
    data_root = Path(args.data_root)
    
    if args.all:
        for dataset_id in DATASET_DOWNLOADS:
            print_download_info(dataset_id)
    elif args.preset:
        download_preset(args.preset, data_root)
    else:
        parser.print_help()
        print("\nAvailable presets:")
        for preset, datasets in PRESETS.items():
            print(f"  - {preset}: {', '.join(datasets)}")


if __name__ == "__main__":
    main()