"""
Intent Classification for voice commands.

Uses patterns from Fluent Speech Commands dataset to classify voice input
into actionable intents for the table tennis coaching system.
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Types of intents for voice commands."""
    SCORE_UPDATE = "score_update"
    SCORE_QUERY = "score_query"
    UNDO = "undo"
    RESET = "reset"
    MATCH_RESULT = "match_result"
    SERVER_CHANGE = "server_change"
    COACHING_QUERY = "coaching_query"
    SESSION_CONTROL = "session_control"
    PLAYER_INFO = "player_info"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent_type: IntentType
    confidence: float
    entities: Dict[str, Any] = None
    raw_text: str = ""

    def __post_init__(self):
        if self.entities is None:
            self.entities = {}


# Intent patterns based on Fluent Speech Commands and table tennis domain
INTENT_PATTERNS: Dict[IntentType, List[str]] = {
    IntentType.SCORE_UPDATE: [
        r"\b(score|point|game|set)\s+(is\s+)?(for\s+)?",
        r"\b(player\s+\w+)\s+(wins|won|scores)",
        r"\b(\d+)\s*[-–]\s*(\d+)",
        r"\b(update|set|change)\s+score",
        r"\b(match\s+ball|game\s+point)",
        r"\bpoint\s+to\s+\w+",
        r"\bpoint\s+for\s+\w+",
        r"\bscored?\s+by\s+\w+",
        r"\b\w+\s+scores?\s+(a\s+)?point\b",
        r"\b\w+\s+wins\s+(the\s+)?point\b",
    ],
    IntentType.SCORE_QUERY: [
        r"\bwhat's\s+the\s+score\b",
        r"\bwhats\s+the\s+score\b",
        r"\bwhat\s+is\s+the\s+score\b",
        r"\bscore\s+please\b",
        r"\bcurrent\s+score\b",
        r"\btell\s+me\s+the\s+score\b",
        r"\bshow\s+score\b",
    ],
    IntentType.UNDO: [
        r"\bundo\b",
        r"\btake\s+back\b",
        r"\bremove\s+point\b",
        r"\bremove\s+the\s+last\s+point\b",
        r"\bwrong\b",
        r"\bincorrect\b",
        r"\bthat\s+was\s+wrong\b",
        r"\btake\s+that\s+back\b",
    ],
    IntentType.RESET: [
        r"\breset\b",
        r"\bstart\s+over\b",
        r"\bnew\s+match\b",
        r"\bclear\s+score\b",
        r"\breset\s+the\s+match\b",
    ],
    IntentType.MATCH_RESULT: [
        r"\b\w+\s+beat\s+\w+\s+\d+\s*[-–]\s*\d+\b",
        r"\b\w+\s+defeated\s+\w+\s+\d+\s*[-–]\s*\d+\b",
        r"\b\w+\s+wins\s+over\s+\w+\s+\d+\s*[-–]\s*\d+\b",
        r"\b\w+\s+lost\s+to\s+\w+\s+\d+\s*[-–]\s*\d+\b",
        r"\b\w+\s+beat\s+\w+\s+\w+\s*[-–]\s*\w+\b",  # word scores like "three-one"
    ],
    IntentType.SERVER_CHANGE: [
        r"\bserver\s+change\b",
        r"\bchange\s+server\b",
        r"\b\w+\s+serves\b",
        r"\b\w+\s+to\s+serve\b",
        r"\bserve\s+change\b",
        r"\bswitch\s+serve\b",
    ],
    IntentType.COACHING_QUERY: [
        r"\b(analyze|analyse)\s+(my\s+)?",
        r"\b(coaching|coach|tip|advice|suggest)",
        r"\b(feedback|improve|improvement)",
        r"\b(backhand|forehand|serve|stroke|swing)",
        r"\b(technique|form|posture|stance)",
        r"\b(show|give)\s+(me\s+)?(coaching|tips)",
    ],
    IntentType.SESSION_CONTROL: [
        r"\b(record|start|stop|end)\s+(session|recording)?",
        r"\b(save|discard)\s+(session|recording)?",
        r"\b(begin|start)\s+(match|session)?",
        r"\b(finish|complete)\s+(match|session)?",
        r"\b(start|stop|end)\s+the\s+(session|recording|match)",
    ],
    IntentType.PLAYER_INFO: [
        r"\b(who|what).*player",
        r"\b(player\s+\w+)",
        r"\b(rating|rank|win\s+rate|stats|statistics)",
        r"\b(match\s+history|played)",
    ],
}


class IntentClassifier:
    """
    Classifies voice transcripts into actionable intents.
    
    Uses pattern matching based on Fluent Speech Commands dataset
    and table tennis domain knowledge.
    """

    def __init__(self, threshold: float = 0.3):
        """
        Initialize the intent classifier.
        
        Args:
            threshold: Confidence threshold for intent classification
        """
        self.threshold = threshold
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficiency."""
        self._compiled_patterns: Dict[IntentType, List[re.Pattern]] = {}
        for intent_type, patterns in INTENT_PATTERNS.items():
            self._compiled_patterns[intent_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def classify(self, transcript: str) -> IntentResult:
        """
        Classify a transcript into an intent.
        
        Args:
            transcript: The voice transcript to classify
            
        Returns:
            IntentResult with intent type, confidence, and extracted entities
        """
        if not transcript or not transcript.strip():
            return IntentResult(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                raw_text=transcript
            )

        scores: Dict[IntentType, float] = {}
        
        for intent_type, patterns in self._compiled_patterns.items():
            score = 0.0
            for pattern in patterns:
                if pattern.search(transcript):
                    score += 1.0
            scores[intent_type] = score

        # Normalize scores
        max_score = max(scores.values()) if scores else 0.0
        if max_score > 0:
            scores = {k: v / max_score for k, v in scores.items()}

        # Find best intent
        best_intent = max(scores, key=scores.get)
        confidence = scores[best_intent]

        # Extract entities based on intent
        entities = self._extract_entities(transcript, best_intent)

        return IntentResult(
            intent_type=best_intent if confidence >= self.threshold else IntentType.UNKNOWN,
            confidence=confidence,
            entities=entities,
            raw_text=transcript
        )

    def _extract_entities(self, transcript: str, intent_type: IntentType) -> Dict[str, Any]:
        """Extract entities from transcript based on intent type."""
        entities = {}

        if intent_type == IntentType.SCORE_UPDATE:
            # Extract score patterns
            score_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", transcript)
            if score_match:
                entities["score"] = f"{score_match.group(1)}-{score_match.group(2)}"

            # Extract player names
            player_match = re.search(r"player\s+(\w+)", transcript, re.IGNORECASE)
            if player_match:
                entities["player"] = player_match.group(1)

        elif intent_type == IntentType.SCORE_QUERY:
            # No specific entities needed for score query
            pass

        elif intent_type == IntentType.UNDO:
            entities["action"] = "undo"

        elif intent_type == IntentType.RESET:
            entities["action"] = "reset"

        elif intent_type == IntentType.MATCH_RESULT:
            # Extract player names and score from "X beat Y 3-1" patterns
            beat_match = re.search(
                r"(?P<a>\w+)\s+(?:beat|defeated|wins\s+over)\s+(?P<b>\w+)\s+(?P<score>\d+\s*[-–]\s*\d+)",
                transcript,
                re.IGNORECASE
            )
            if beat_match:
                entities["player_a"] = beat_match.group("a")
                entities["player_b"] = beat_match.group("b")
                entities["score"] = beat_match.group("score").replace(" ", "")
                entities["winner"] = beat_match.group("a")

            # Also handle "X lost to Y" pattern
            lost_match = re.search(
                r"(?P<b>\w+)\s+lost\s+to\s+(?P<a>\w+)\s+(?P<score>\d+\s*[-–]\s*\d+)",
                transcript,
                re.IGNORECASE
            )
            if lost_match:
                entities["player_a"] = lost_match.group("a")
                entities["player_b"] = lost_match.group("b")
                entities["score"] = lost_match.group("score").replace(" ", "")
                entities["winner"] = lost_match.group("a")

        elif intent_type == IntentType.SERVER_CHANGE:
            # Extract server name
            server_match = re.search(r"(\w+)\s+(?:serves|to\s+serve)", transcript, re.IGNORECASE)
            if server_match:
                entities["server"] = server_match.group(1)

        elif intent_type == IntentType.COACHING_QUERY:
            # Extract stroke type
            stroke_match = re.search(
                r"(backhand|forehand|serve|stroke|swing|loop|smash|block|push|chop|footwork)",
                transcript,
                re.IGNORECASE
            )
            if stroke_match:
                entities["stroke_type"] = stroke_match.group(1).lower()

        elif intent_type == IntentType.SESSION_CONTROL:
            # Extract action
            if re.search(r"\b(start|begin|record)\b", transcript, re.IGNORECASE):
                entities["action"] = "start"
            elif re.search(r"\b(stop|end|finish|discard)\b", transcript, re.IGNORECASE):
                entities["action"] = "stop"

        elif intent_type == IntentType.PLAYER_INFO:
            # Extract player name
            player_match = re.search(r"player\s+(\w+)", transcript, re.IGNORECASE)
            if player_match:
                entities["player"] = player_match.group(1)

        return entities

    def get_supported_intents(self) -> List[IntentType]:
        """Get list of supported intent types."""
        return list(IntentType)

    def get_patterns(self) -> Dict[IntentType, List[str]]:
        """Get the patterns used for classification."""
        return INTENT_PATTERNS