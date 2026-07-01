#!/usr/bin/env python3
"""
Intent classifier training script for TT-tournament voice scorekeeper.

This script extracts score-related patterns from Fluent Speech Commands dataset
and updates the IntentClassifier patterns for better score update recognition.

Usage:
    python scripts/train_intent_classifier.py --data-root ../tt_ai_data
"""

import argparse
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Table tennis specific score patterns
TABLE_TENNIS_SCORE_PATTERNS = [
    # Point scoring
    (r"\b(point|score)\s+(to|for)\s+(player\s+[ab]|p[12])\b", "SCORE_UPDATE"),
    (r"\b(player\s+[ab]|p[12])\s+(scores?|wins?)\s+(point|score)\b", "SCORE_UPDATE"),
    (r"\b(player\s+[ab]|p[12])\s+(scores?|wins?)\b", "SCORE_UPDATE"),
    
    # Game scoring
    (r"\b(game|match)\s+(point|score)\b", "SCORE_UPDATE"),
    (r"\b(score|result)\s+(is|was)\s+\d+-\d+\b", "SCORE_UPDATE"),
    (r"\b(\d+)-(\d+)\s+(game|match)\b", "SCORE_UPDATE"),
    
    # Undo/ correction
    (r"\b(undo|remove|take back|correction)\b", "SESSION_CONTROL"),
    (r"\b(last point|previous point)\b", "SESSION_CONTROL"),
    
    # Score query
    (r"\b(what's|what is|show)\s+(the\s+)?(score|result)\b", "PLAYER_INFO"),
    (r"\b(current|match)\s+(score|status)\b", "PLAYER_INFO"),
    
    # Player info
    (r"\b(who is|player info|player stats)\b", "PLAYER_INFO"),
    (r"\b(player\s+[ab]|p[12])\s+(name|rating)\b", "PLAYER_INFO"),
]


def extract_score_patterns(fluent_commands_path: Path) -> List[Dict[str, Any]]:
    """
    Extract score-related patterns from Fluent Speech Commands dataset.
    
    Args:
        fluent_commands_path: Path to the Fluent Speech Commands dataset
        
    Returns:
        List of extracted patterns with intent type
    """
    patterns = []
    
    # Check if dataset exists
    if not fluent_commands_path.exists():
        logger.warning(f"Fluent Speech Commands dataset not found at {fluent_commands_path}")
        logger.info("Using built-in table tennis patterns instead")
        return TABLE_TENNIS_SCORE_PATTERNS
    
    # Look for command data files
    data_files = list(fluent_commands_path.glob("**/*.json"))
    if not data_files:
        data_files = list(fluent_commands_path.glob("**/*.csv"))
    
    for data_file in data_files:
        try:
            if data_file.suffix == ".json":
                with open(data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            elif data_file.suffix == ".csv":
                import csv
                with open(data_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    data = list(reader)
            else:
                continue
            
            # Extract patterns that might be relevant to scorekeeping
            for item in data:
                text = item.get('text', item.get('transcript', '')).lower()
                
                # Look for score-related keywords
                if any(kw in text for kw in ['score', 'point', 'game', 'win', 'match']):
                    # Convert to regex pattern
                    pattern = re.escape(text)
                    patterns.append({
                        "pattern": pattern,
                        "intent": "SCORE_UPDATE",
                        "entities": {}
                    })
                    
        except Exception as e:
            logger.warning(f"Error processing {data_file}: {e}")
    
    return patterns


def update_intent_classifier(patterns: List[Dict[str, Any]], output_path: Path) -> None:
    """
    Update the IntentClassifier with extracted patterns.
    
    Args:
        patterns: List of patterns to add
        output_path: Path to save the updated patterns
    """
    # Load existing patterns or create new
    if output_path.exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            existing_patterns = json.load(f)
    else:
        existing_patterns = []
    
    # Merge patterns (avoid duplicates)
    existing_texts = {p.get('pattern', '') for p in existing_patterns}
    for pattern in patterns:
        if pattern.get('pattern', '') not in existing_texts:
            existing_patterns.append(pattern)
    
    # Save updated patterns
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing_patterns, f, indent=2)
    
    logger.info(f"Saved {len(existing_patterns)} patterns to {output_path}")


def create_training_manifest(data_root: Path) -> None:
    """
    Create a training manifest for the intent classifier.
    
    Args:
        data_root: Root directory for datasets
    """
    manifest = {
        "dataset": "intent_classifier_training",
        "version": "1.0",
        "patterns": TABLE_TENNIS_SCORE_PATTERNS,
        "table_tennis_terms": [
            "forehand", "backhand", "serve", "return", "loop", "drive",
            "chop", "block", "push", "smash", "point", "game", "match",
            "deuce", "advantage", "let", "fault", "table tennis", "ping pong"
        ]
    }
    
    manifest_path = data_root / "manifests" / "intent_training.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"Created training manifest at {manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Train intent classifier for voice scorekeeper"
    )
    parser.add_argument(
        "--data-root", 
        default="tt_ai_data", 
        help="Root directory for datasets"
    )
    parser.add_argument(
        "--fluent-commands-path",
        help="Path to Fluent Speech Commands dataset (optional)"
    )
    parser.add_argument(
        "--output",
        default="tournament_platform/multimodal_ai/intent_patterns.json",
        help="Output path for intent patterns"
    )
    
    args = parser.parse_args()
    
    data_root = Path(args.data_root)
    
    # Create training manifest
    create_training_manifest(data_root)
    
    # Extract patterns from Fluent Speech Commands if available
    if args.fluent_commands_path:
        fluent_path = Path(args.fluent_commands_path)
        patterns = extract_score_patterns(fluent_path)
        update_intent_classifier(patterns, Path(args.output))
    else:
        # Use built-in patterns
        update_intent_classifier(TABLE_TENNIS_SCORE_PATTERNS, Path(args.output))
    
    logger.info("Intent classifier training complete!")


if __name__ == "__main__":
    main()