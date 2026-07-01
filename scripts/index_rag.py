#!/usr/bin/env python3
"""
RAG indexing script for TT-tournament multimodal AI system.

This script indexes coaching knowledge from T3Set and event context from OpenTTGames
into ChromaDB for retrieval-augmented generation.

Usage:
    python scripts/index_rag.py --data-root ../tt_ai_data
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import chromadb, provide helpful error if not available
try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    chromadb = None
    logger.warning("chromadb not installed. Install with: pip install chromadb")


# Built-in table tennis technique knowledge (used when datasets not available)
BUILTIN_TECHNIQUE_KNOWLEDGE = [
    {
        "technique": "forehand",
        "key_points": [
            "Hold racket with thumb and index finger forming a fork grip",
            "Position racket angle slightly closed (about 45 degrees)",
            "Step forward with opposite foot for balance",
            "Contact ball at waist height for consistency",
            "Follow through toward target"
        ],
        "common_mistakes": [
            "Holding racket too tight causing tension",
            "Not stepping forward for power",
            "Late contact causing pop-ups",
            "No follow through reducing accuracy"
        ],
        "drills": [
            "Forehand to forehand rally",
            "Multi-ball forehand practice",
            "Target hitting with forehand"
        ]
    },
    {
        "technique": "backhand",
        "key_points": [
            "Use wrist and forearm for power",
            "Keep elbow relatively high and stable",
            "Racket angle slightly open for backspin",
            "Contact ball in front of body",
            "Compact swing for control"
        ],
        "common_mistakes": [
            "Collapsed wrist reducing control",
            "No follow through",
            "Too much arm swing",
            "Poor timing"
        ],
        "drills": [
            "Backhand to backhand rally",
            "Backhand block practice",
            "Backhand against topspin"
        ]
    },
    {
        "technique": "serve",
        "key_points": [
            "Ball toss should be visible above table",
            "Racket motion should be smooth and continuous",
            "Contact ball for desired spin",
            "Serve from behind end line",
            "Clear toss for legal serve"
        ],
        "common_mistques": [
            "High toss making timing difficult",
            "No spin on serve",
            "Hiding ball during toss",
            "Foot fault on serve"
        ],
        "drills": [
            "Practice different serve placements",
            "Serve and attack pattern",
            "Serve return practice"
        ]
    },
    {
        "technique": "footwork",
        "key_points": [
            "Stay on balls of feet for quick movement",
            "Use small steps for fine positioning",
            "Keep weight forward for quick transitions",
            "Move before opponent hits ball",
            "Recover to center position after shot"
        ],
        "common_mistakes": [
            "Flat-footed movement",
            "Large steps causing imbalance",
            "Waiting too long to move",
            "Poor recovery position"
        ],
        "drills": [
            "Shadow footwork practice",
            "Multiball footwork training",
            "Random ball placement drills"
        ]
    }
]


def get_chroma_client(data_root: Path) -> Optional[Any]:
    """
    Get or create ChromaDB client.
    
    Args:
        data_root: Root directory for datasets
        
    Returns:
        ChromaDB client or None if not available
    """
    if chromadb is None:
        return None
    
    chroma_path = data_root / "indexes" / "chroma_multimodal"
    chroma_path.mkdir(parents=True, exist_ok=True)
    
    return chromadb.PersistentClient(
        path=str(chroma_path),
        settings=Settings(allow_reset=True)
    )


def index_technique_knowledge(client: Any, data_root: Path) -> int:
    """
    Index table tennis technique knowledge into ChromaDB.
    
    Args:
        client: ChromaDB client
        data_root: Root directory for datasets
        
    Returns:
        Number of documents indexed
    """
    # Get or create collection
    try:
        collection = client.get_collection("technique_knowledge")
    except Exception:
        collection = client.create_collection(
            name="technique_knowledge",
            metadata={"description": "Table tennis technique knowledge for coaching"}
        )
    
    # Check for T3Set data
    t3set_path = data_root / "raw" / "table_tennis" / "t3set"
    if t3set_path.exists():
        # Load T3Set coaching text
        knowledge_items = load_t3set_knowledge(t3set_path)
    else:
        # Use built-in knowledge
        logger.info("T3Set not found, using built-in technique knowledge")
        knowledge_items = BUILTIN_TECHNIQUE_KNOWLEDGE
    
    # Prepare documents for indexing
    documents = []
    metadatas = []
    ids = []
    
    for i, item in enumerate(knowledge_items):
        # Create document text
        doc_text = f"Technique: {item.get('technique', 'unknown')}\n"
        doc_text += f"Key points: {', '.join(item.get('key_points', []))}\n"
        doc_text += f"Common mistakes: {', '.join(item.get('common_mistakes', []))}\n"
        if item.get('drills'):
            doc_text += f"Drills: {', '.join(item.get('drills', []))}\n"
        
        documents.append(doc_text)
        metadatas.append({
            "dataset": "t3set" if t3set_path.exists() else "builtin",
            "type": "technique",
            "technique": item.get('technique', 'unknown')
        })
        ids.append(f"technique_{i}")
    
    # Add to collection
    if documents:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        logger.info(f"Indexed {len(documents)} technique knowledge documents")
    
    return len(documents)


def load_t3set_knowledge(t3set_path: Path) -> List[Dict[str, Any]]:
    """
    Load coaching knowledge from T3Set dataset.
    
    Args:
        t3set_path: Path to T3Set data
        
    Returns:
        List of knowledge items
    """
    knowledge_items = []
    
    # Look for JSON files with coaching data
    json_files = list(t3set_path.glob("**/*.json"))
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract coaching text
            if isinstance(data, list):
                for item in data:
                    if 'coaching' in item or 'feedback' in item:
                        knowledge_items.append(item)
            elif isinstance(data, dict):
                if 'coaching' in data or 'feedback' in data:
                    knowledge_items.append(data)
                    
        except Exception as e:
            logger.warning(f"Error loading {json_file}: {e}")
    
    return knowledge_items if knowledge_items else BUILTIN_TECHNIQUE_KNOWLEDGE


def index_event_context(client: Any, data_root: Path) -> int:
    """
    Index event context from OpenTTGames into ChromaDB.
    
    Args:
        client: ChromaDB client
        data_root: Root directory for datasets
        
    Returns:
        Number of documents indexed
    """
    # Get or create collection
    try:
        collection = client.get_collection("event_context")
    except Exception:
        collection = client.create_collection(
            name="event_context",
            metadata={"description": "Table tennis event context for score interpretation"}
        )
    
    # Check for OpenTTGames data
    opentt_path = data_root / "raw" / "table_tennis" / "openttgames"
    if opentt_path.exists():
        # Load event context
        event_items = load_opentt_context(opentt_path)
    else:
        # Use built-in event context
        logger.info("OpenTTGames not found, using built-in event context")
        event_items = get_builtin_event_context()
    
    # Prepare documents for indexing
    documents = []
    metadatas = []
    ids = []
    
    for i, item in enumerate(event_items):
        doc_text = f"Event: {item.get('event', 'unknown')}\n"
        doc_text += f"Context: {item.get('context', '')}\n"
        
        documents.append(doc_text)
        metadatas.append({
            "dataset": "openttgames" if opentt_path.exists() else "builtin",
            "type": "event",
            "event": item.get('event', 'unknown')
        })
        ids.append(f"event_{i}")
    
    # Add to collection
    if documents:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        logger.info(f"Indexed {len(documents)} event context documents")
    
    return len(documents)


def load_opentt_context(opentt_path: Path) -> List[Dict[str, Any]]:
    """
    Load event context from OpenTTGames dataset.
    
    Args:
        opentt_path: Path to OpenTTGames data
        
    Returns:
        List of event context items
    """
    event_items = []
    
    # Look for annotation files
    json_files = list(opentt_path.glob("**/*annotation*.json"))
    json_files.extend(opentt_path.glob("**/*event*.json"))
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                event_items.extend(data)
            elif isinstance(data, dict):
                event_items.append(data)
                
        except Exception as e:
            logger.warning(f"Error loading {json_file}: {e}")
    
    return event_items if event_items else get_builtin_event_context()


def get_builtin_event_context() -> List[Dict[str, Any]]:
    """Get built-in event context for table tennis."""
    return [
        {
            "event": "serve",
            "context": "Server throws ball and strikes it. Receiver must let ball bounce before returning."
        },
        {
            "event": "point_scored",
            "context": "Point is scored when opponent cannot return ball legally. Update score immediately."
        },
        {
            "event": "fault",
            "context": "Fault occurs on illegal serve or hit. Opponent gets point."
        },
        {
            "event": "let",
            "context": "Let is called for interference. Point is replayed with no score change."
        },
        {
            "event": "game_point",
            "context": "When player reaches 10+ points with 2-point lead, they win the game."
        },
        {
            "event": "match_point",
            "context": "When player can win match with next point, it's match point."
        }
    ]


def create_index_manifest(data_root: Path, technique_count: int, event_count: int) -> None:
    """
    Create a manifest for the RAG index.
    
    Args:
        data_root: Root directory for datasets
        technique_count: Number of technique documents indexed
        event_count: Number of event documents indexed
    """
    manifest = {
        "index_name": "multimodal_ai_rag",
        "version": "1.0",
        "collections": {
            "technique_knowledge": {
                "document_count": technique_count,
                "description": "Table tennis technique knowledge for coaching"
            },
            "event_context": {
                "document_count": event_count,
                "description": "Table tennis event context for score interpretation"
            }
        },
        "created_at": str(Path.cwd())
    }
    
    manifest_path = data_root / "manifests" / "rag_index.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"Created RAG index manifest at {manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Index datasets into RAG for multimodal AI"
    )
    parser.add_argument(
        "--data-root", 
        default="tt_ai_data", 
        help="Root directory for datasets"
    )
    
    args = parser.parse_args()
    
    data_root = Path(args.data_root)
    
    # Get ChromaDB client
    client = get_chroma_client(data_root)
    
    if client is None:
        logger.error("ChromaDB not available. Install with: pip install chromadb")
        return
    
    # Index technique knowledge
    technique_count = index_technique_knowledge(client, data_root)
    
    # Index event context
    event_count = index_event_context(client, data_root)
    
    # Create manifest
    create_index_manifest(data_root, technique_count, event_count)
    
    logger.info("RAG indexing complete!")
    logger.info(f"  - Technique knowledge: {technique_count} documents")
    logger.info(f"  - Event context: {event_count} documents")


if __name__ == "__main__":
    main()