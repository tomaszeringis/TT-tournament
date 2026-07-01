#!/usr/bin/env python3
"""
Feature extraction script for TT-tournament multimodal AI system.

This script extracts features from datasets for use in the coaching pipeline.

Usage:
    python scripts/extract_dataset_features.py --dataset t3set --data-root ../tt_ai_data
"""

import argparse
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_t3set_features(t3set_path: Path, output_path: Path) -> int:
    """
    Extract coaching features from T3Set dataset.
    
    Args:
        t3set_path: Path to T3Set data
        output_path: Path to save extracted features
        
    Returns:
        Number of features extracted
    """
    features = []
    
    if not t3set_path.exists():
        logger.warning(f"T3Set not found at {t3set_path}, creating sample features")
        features = get_sample_t3set_features()
    else:
        # Load actual T3Set data
        json_files = list(t3set_path.glob("**/*.json"))
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    for item in data:
                        if 'coaching' in item or 'feedback' in item:
                            features.append({
                                "type": "coaching_text",
                                "content": item.get('coaching', item.get('feedback', '')),
                                "stroke_type": item.get('stroke', 'general'),
                                "source": str(json_file)
                            })
            except Exception as e:
                logger.warning(f"Error processing {json_file}: {e}")
    
    # Save features
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(features, f, indent=2)
    
    logger.info(f"Extracted {len(features)} T3Set features to {output_path}")
    return len(features)


def get_sample_t3set_features() -> List[Dict[str, Any]]:
    """Get sample T3Set features for testing."""
    return [
        {
            "type": "coaching_text",
            "content": "Focus on your forehand technique. Keep your elbow up and follow through.",
            "stroke_type": "forehand",
            "source": "sample"
        },
        {
            "type": "coaching_text",
            "content": "Your backhand needs more wrist snap for better spin.",
            "stroke_type": "backhand",
            "source": "sample"
        },
        {
            "type": "coaching_text",
            "content": "Serve placement is good, but work on your toss consistency.",
            "stroke_type": "serve",
            "source": "sample"
        }
    ]


def extract_opentt_features(opentt_path: Path, output_path: Path) -> int:
    """
    Extract event features from OpenTTGames dataset.
    
    Args:
        opentt_path: Path to OpenTTGames data
        output_path: Path to save extracted features
        
    Returns:
        Number of features extracted
    """
    features = []
    
    if not opentt_path.exists():
        logger.warning(f"OpenTTGames not found at {opentt_path}, creating sample features")
        features = get_sample_opentt_features()
    else:
        # Load actual OpenTTGames data
        json_files = list(opentt_path.glob("**/*annotation*.json"))
        json_files.extend(opentt_path.glob("**/*event*.json"))
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    for item in data:
                        features.append({
                            "type": "event",
                            "event_type": item.get('event', 'unknown'),
                            "timestamp": item.get('timestamp', 0),
                            "source": str(json_file)
                        })
            except Exception as e:
                logger.warning(f"Error processing {json_file}: {e}")
    
    # Save features
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(features, f, indent=2)
    
    logger.info(f"Extracted {len(features)} OpenTTGames features to {output_path}")
    return len(features)


def get_sample_opentt_features() -> List[Dict[str, Any]]:
    """Get sample OpenTTGames features for testing."""
    return [
        {
            "type": "event",
            "event_type": "serve",
            "timestamp": 0.0,
            "source": "sample"
        },
        {
            "type": "event",
            "event_type": "point_end",
            "timestamp": 3.5,
            "source": "sample"
        },
        {
            "type": "event",
            "event_type": "score_update",
            "timestamp": 3.6,
            "source": "sample"
        }
    ]


def extract_blurball_features(blurball_path: Path, output_path: Path) -> int:
    """
    Extract ball tracking features from BlurBall dataset.
    
    Args:
        blurball_path: Path to BlurBall data
        output_path: Path to save extracted features
        
    Returns:
        Number of features extracted
    """
    features = []
    
    if not blurball_path.exists():
        logger.warning(f"BlurBall not found at {blurball_path}, creating sample features")
        features = get_sample_blurball_features()
    else:
        # Load actual BlurBall data
        json_files = list(blurball_path.glob("**/*.json"))
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    for item in data:
                        features.append({
                            "type": "ball_position",
                            "x": item.get('x', 0),
                            "y": item.get('y', 0),
                            "timestamp": item.get('timestamp', 0),
                            "source": str(json_file)
                        })
            except Exception as e:
                logger.warning(f"Error processing {json_file}: {e}")
    
    # Save features
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(features, f, indent=2)
    
    logger.info(f"Extracted {len(features)} BlurBall features to {output_path}")
    return len(features)


def get_sample_blurball_features() -> List[Dict[str, Any]]:
    """Get sample BlurBall features for testing."""
    return [
        {
            "type": "ball_position",
            "x": 0.5,
            "y": 0.3,
            "timestamp": 0.0,
            "source": "sample"
        },
        {
            "type": "ball_position",
            "x": 0.7,
            "y": 0.5,
            "timestamp": 0.1,
            "source": "sample"
        }
    ]


def create_feature_manifest(data_root: Path, counts: Dict[str, int]) -> None:
    """
    Create a manifest for extracted features.
    
    Args:
        data_root: Root directory for datasets
        counts: Dictionary of feature counts by dataset
    """
    manifest = {
        "feature_extraction": {
            "version": "1.0",
            "datasets": counts,
            "created_at": str(Path.cwd())
        }
    }
    
    manifest_path = data_root / "manifests" / "features.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"Created feature manifest at {manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract features from datasets for multimodal AI"
    )
    parser.add_argument(
        "--data-root", 
        default="tt_ai_data", 
        help="Root directory for datasets"
    )
    parser.add_argument(
        "--dataset",
        choices=["t3set", "openttgames", "blurball", "all"],
        default="all",
        help="Dataset to extract features from"
    )
    
    args = parser.parse_args()
    
    data_root = Path(args.data_root)
    features_path = data_root / "features" / "table_tennis"
    
    counts = {}
    
    if args.dataset in ["t3set", "all"]:
        t3set_path = data_root / "raw" / "table_tennis" / "t3set"
        output_path = features_path / "t3set_features.json"
        counts["t3set"] = extract_t3set_features(t3set_path, output_path)
    
    if args.dataset in ["openttgames", "all"]:
        opentt_path = data_root / "raw" / "table_tennis" / "openttgames"
        output_path = features_path / "openttgames_features.json"
        counts["openttgames"] = extract_opentt_features(opentt_path, output_path)
    
    if args.dataset in ["blurball", "all"]:
        blurball_path = data_root / "raw" / "table_tennis" / "blurball"
        output_path = features_path / "blurball_features.json"
        counts["blurball"] = extract_blurball_features(blurball_path, output_path)
    
    # Create manifest
    create_feature_manifest(data_root, counts)
    
    logger.info("Feature extraction complete!")


if __name__ == "__main__":
    main()