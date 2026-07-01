#!/usr/bin/env python3
"""
Local coaching demo script for TT-tournament multimodal AI system.

This script demonstrates the coaching pipeline using tiny fixtures
when real datasets are not available.

Usage:
    python scripts/run_local_coaching_demo.py
"""

import json
import logging
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Tiny fixture data for testing
TINY_FIXTURES = {
    "transcripts": [
        "Player A scores a point with a forehand loop",
        "What's the current score?",
        "How can I improve my backhand?",
        "Player B wins the game 11-5",
        "Undo the last point"
    ],
    "coaching_knowledge": [
        {
            "technique": "forehand",
            "key_points": ["Racket angle", "Body position", "Follow through"],
            "common_mistakes": ["Too much wrist", "Late contact"]
        },
        {
            "technique": "backhand",
            "key_points": ["Elbow position", "Racket angle", "Weight transfer"],
            "common_mistakes": ["Collapsed wrist", "No follow through"]
        }
    ],
    "event_context": [
        {"event": "serve", "context": "Server throws ball and strikes it"},
        {"event": "point_end", "context": "Point is scored when opponent cannot return ball legally"}
    ]
}


def create_tiny_fixtures(data_root: Path) -> None:
    """
    Create tiny fixture files for testing.
    
    Args:
        data_root: Root directory for datasets
    """
    # Create directory structure
    fixtures_path = data_root / "fixtures" / "table_tennis"
    fixtures_path.mkdir(parents=True, exist_ok=True)
    
    # Save transcripts
    transcripts_path = fixtures_path / "transcripts.json"
    with open(transcripts_path, 'w', encoding='utf-8') as f:
        json.dump(TINY_FIXTURES["transcripts"], f, indent=2)
    
    # Save coaching knowledge
    coaching_path = fixtures_path / "coaching_knowledge.json"
    with open(coaching_path, 'w', encoding='utf-8') as f:
        json.dump(TINY_FIXTURES["coaching_knowledge"], f, indent=2)
    
    # Save event context
    events_path = fixtures_path / "event_context.json"
    with open(events_path, 'w', encoding='utf-8') as f:
        json.dump(TINY_FIXTURES["event_context"], f, indent=2)
    
    logger.info(f"Created tiny fixtures in {fixtures_path}")


def run_demo() -> None:
    """
    Run a demo of the coaching pipeline.
    """
    print("\n" + "="*60)
    print("TT-Tournament Multimodal AI Coaching Demo")
    print("="*60 + "\n")
    
    print("Available commands:")
    for i, transcript in enumerate(TINY_FIXTURES["transcripts"], 1):
        print(f"  {i}. {transcript}")
    
    print("\n" + "-"*60)
    print("Demo: Processing 'How can I improve my backhand?'")
    print("-"*60 + "\n")
    
    # Simulate intent classification
    transcript = "How can I improve my backhand?"
    intent = "COACHING_QUERY"
    stroke_type = "backhand"
    
    print(f"Transcript: {transcript}")
    print(f"Intent: {intent}")
    print(f"Stroke type: {stroke_type}")
    
    # Simulate RAG retrieval
    print("\nRetrieving coaching knowledge...")
    for knowledge in TINY_FIXTURES["coaching_knowledge"]:
        if knowledge["technique"] == stroke_type:
            print(f"\nCoaching for {stroke_type}:")
            print(f"  Key points: {', '.join(knowledge['key_points'])}")
            print(f"  Common mistakes: {', '.join(knowledge['common_mistakes'])}")
            break
    
    # Simulate LLM response
    print("\n" + "-"*60)
    print("Generated coaching feedback:")
    print("-"*60)
    print(f"Focus on your {stroke_type} technique. Keep your elbow high and maintain proper racket angle.")
    print("Common mistake to avoid: collapsed wrist. Practice with a compact swing for better control.")
    
    print("\n" + "="*60)
    print("Demo complete!")
    print("="*60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Run local coaching demo with tiny fixtures"
    )
    parser.add_argument(
        "--data-root", 
        default="tt_ai_data", 
        help="Root directory for datasets"
    )
    parser.add_argument(
        "--create-fixtures",
        action="store_true",
        help="Create tiny fixture files"
    )
    
    args = parser.parse_args()
    
    data_root = Path(args.data_root)
    
    if args.create_fixtures:
        create_tiny_fixtures(data_root)
    
    run_demo()


if __name__ == "__main__":
    main()