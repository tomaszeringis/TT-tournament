"""
Voice Command Dataset - Patterns and examples for intent classification.

Provides deterministic patterns for table-tennis voice commands that can be
used to improve intent classification without requiring training data.
"""

from typing import Dict, List

# Command patterns for each intent type
# These are used for deterministic classification and can be extended

SCORE_UPDATE_PATTERNS: List[str] = [
    r"\b(score|point|game|set)\s+(is\s+)?(for\s+)?",
    r"\b(player\s+\w+)\s+(wins|won|scores)",
    r"\b(\d+)\s*[-–]\s*(\d+)",
    r"\b(update|set|change)\s+score",
    r"\b(match\s+ball|game\s+point)",
    r"\bpoint\s+to\s+\w+",
    r"\bpoint\s+for\s+\w+",
    r"\bscored?\s+by\s+\w+",
]

SCORE_QUERY_PATTERNS: List[str] = [
    r"\bwhat's\s+the\s+score\b",
    r"\bwhats\s+the\s+score\b",
    r"\bwhat\s+is\s+the\s+score\b",
    r"\bscore\s+please\b",
    r"\bcurrent\s+score\b",
    r"\btell\s+me\s+the\s+score\b",
    r"\bshow\s+score\b",
]

UNDO_PATTERNS: List[str] = [
    r"\bundo\b",
    r"\btake\s+back\b",
    r"\bremove\s+point\b",
    r"\bwrong\b",
    r"\bincorrect\b",
    r"\bthat\s+was\s+wrong\b",
    r"\btake\s+that\s+back\b",
]

RESET_PATTERNS: List[str] = [
    r"\breset\b",
    r"\bstart\s+over\b",
    r"\bnew\s+match\b",
    r"\bclear\s+score\b",
]

MATCH_RESULT_PATTERNS: List[str] = [
    r"\b\w+\s+beat\s+\w+\s+\d+\s*[-–]\s*\d+\b",
    r"\b\w+\s+defeated\s+\w+\s+\d+\s*[-–]\s*\d+\b",
    r"\b\w+\s+wins\s+over\s+\w+\s+\d+\s*[-–]\s*\d+\b",
    r"\b\w+\s+lost\s+to\s+\w+\s+\d+\s*[-–]\s*\d+\b",
    r"\b\w+\s+beat\s+\w+\s+\w+\s*[-–]\s*\w+\b",  # word scores like "three-one"
]

SERVER_CHANGE_PATTERNS: List[str] = [
    r"\bserver\s+change\b",
    r"\bchange\s+server\b",
    r"\b\w+\s+serves\b",
    r"\b\w+\s+to\s+serve\b",
    r"\bserve\s+change\b",
    r"\bswitch\s+serve\b",
]

COACHING_QUERY_PATTERNS: List[str] = [
    r"\b(analyze|analyse)\s+(my\s+)?",
    r"\b(coaching|coach|tip|advice|suggest)\b",
    r"\b(feedback|improve|improvement)\b",
    r"\b(backhand|forehand|serve|stroke|swing)\b",
    r"\b(technique|form|posture|stance)\b",
    r"\b(show|give)\s+(me\s+)?(coaching|tips)\b",
]

SESSION_CONTROL_PATTERNS: List[str] = [
    r"\b(record|start|stop|end)\s+(session|recording)?\b",
    r"\b(save|discard)\s+(session|recording)?\b",
    r"\b(begin|start)\s+(match|session)?\b",
    r"\b(finish|complete)\s+(match|session)?\b",
]

PLAYER_INFO_PATTERNS: List[str] = [
    r"\b(who|what).*player\b",
    r"\bplayer\s+\w+\b",
    r"\b(rating|rank|win\s+rate|stats|statistics)\b",
    r"\b(match\s+history|played)\b",
]


# Example transcripts for each intent type
# These can be used for testing and documentation

SCORE_UPDATE_EXAMPLES: List[str] = [
    "Point to Alice",
    "Point to Bob",
    "Alice scores a point",
    "Bob wins the point",
    "Score is 10-5",
    "Game point for Alice",
    "Update score to 3-1",
]

SCORE_QUERY_EXAMPLES: List[str] = [
    "What's the score?",
    "What is the score?",
    "Show me the score",
    "Current score please",
]

UNDO_EXAMPLES: List[str] = [
    "Undo",
    "Undo last point",
    "Take that back",
    "That was wrong",
    "Remove the last point",
]

RESET_EXAMPLES: List[str] = [
    "Reset the match",
    "Start over",
    "New match",
    "Clear the score",
]

MATCH_RESULT_EXAMPLES: List[str] = [
    "Alice beat Bob 3-1",
    "Bob defeated Alice 11-5",
    "Alice wins over Bob 2-0",
    "Bob lost to Alice 3-2",
    "Alice beat Bob three-one",
]

SERVER_CHANGE_EXAMPLES: List[str] = [
    "Server change",
    "Alice serves",
    "Bob to serve",
    "Change server",
]

COACHING_QUERY_EXAMPLES: List[str] = [
    "How can I improve my backhand?",
    "What's the right forehand technique?",
    "Give me tips for my serve",
    "Coaching on footwork please",
]

SESSION_CONTROL_EXAMPLES: List[str] = [
    "Start recording session",
    "Stop the session",
    "Start a new game",
    "End match",
]

PLAYER_INFO_EXAMPLES: List[str] = [
    "Who is player Alice?",
    "What's the current score?",
    "Show player stats",
    "Alice rating?",
]


# Combined patterns dictionary for easy access
INTENT_PATTERNS: Dict[str, List[str]] = {
    "score_update": SCORE_UPDATE_PATTERNS,
    "score_query": SCORE_QUERY_PATTERNS,
    "undo": UNDO_PATTERNS,
    "reset": RESET_PATTERNS,
    "match_result": MATCH_RESULT_PATTERNS,
    "server_change": SERVER_CHANGE_PATTERNS,
    "coaching_query": COACHING_QUERY_PATTERNS,
    "session_control": SESSION_CONTROL_PATTERNS,
    "player_info": PLAYER_INFO_PATTERNS,
}


# Combined examples dictionary for testing
INTENT_EXAMPLES: Dict[str, List[str]] = {
    "score_update": SCORE_UPDATE_EXAMPLES,
    "score_query": SCORE_QUERY_EXAMPLES,
    "undo": UNDO_EXAMPLES,
    "reset": RESET_EXAMPLES,
    "match_result": MATCH_RESULT_EXAMPLES,
    "server_change": SERVER_CHANGE_EXAMPLES,
    "coaching_query": COACHING_QUERY_EXAMPLES,
    "session_control": SESSION_CONTROL_EXAMPLES,
    "player_info": PLAYER_INFO_EXAMPLES,
}


def get_patterns_for_intent(intent_name: str) -> List[str]:
    """Get patterns for a specific intent."""
    return INTENT_PATTERNS.get(intent_name, [])


def get_examples_for_intent(intent_name: str) -> List[str]:
    """Get example transcripts for a specific intent."""
    return INTENT_EXAMPLES.get(intent_name, [])


def get_all_intent_names() -> List[str]:
    """Get all intent names."""
    return list(INTENT_PATTERNS.keys())