#!/usr/bin/env python3
"""
Example script to initialize the RAG system with tournament rules.
Run this once to populate the ChromaDB knowledge base.

Usage:
    python initialize_rag.py
"""

from tournament_platform.services.ai_engine import AIEngine

# Sample tournament rules for table tennis
TOURNAMENT_RULES = [
    "Players must arrive 5 minutes before their scheduled match time.",
    "Best of 5 games format: first to win 3 games wins the match.",
    "Each player is allowed one 60-second timeout per game.",
    "Players alternate serves every 2 points. After 10 points, if tied, players alternate every point.",
    "The ball must bounce once on the table during serves.",
    "If a player touches the net during play, they lose the point.",
    "Matches must be completed within 60 minutes.",
    "The umpire's decision is final and cannot be appealed.",
    "Players must maintain professional conduct at all times.",
    "No coaching is allowed during matches.",
    "Winners must report results within 24 hours.",
    "Rating points are determined by match outcome and opponent rating.",
    "Players ranked in top 10 earn double rating points for tournament matches.",
    "Provisional players must participate in at least 5 matches to be rated.",
    "Tournament format: Round-robin preliminaries followed by knockout stage.",
]

def initialize_rag():
    """Initialize the RAG system with tournament rules."""
    print("🧠 Initializing RAG System with Tournament Rules...")

    ai = AIEngine()

    print(f"📚 Loading {len(TOURNAMENT_RULES)} tournament rules into ChromaDB...")
    ai.batch_initialize_rules(TOURNAMENT_RULES)

    print("✅ RAG system initialized successfully!")
    print("\n📖 Loaded Rules:")
    for i, rule in enumerate(TOURNAMENT_RULES, 1):
        print(f"  {i}. {rule}")

    # Test retrieval
    print("\n🔍 Testing RAG retrieval...")
    test_queries = [
        "What are the rules for timing out?",
        "What is the match format?",
        "What are the conduct rules?",
    ]

    for query in test_queries:
        context = ai.retrieve_rules_context(query, top_k=2)
        print(f"\n  Query: '{query}'")
        print(f"  Retrieved Context:\n{context}\n")

if __name__ == "__main__":
    try:
        initialize_rag()
        print("\n🎉 RAG initialization complete!")
    except Exception as e:
        print(f"❌ Error during initialization: {e}")
        sys.exit(1)


