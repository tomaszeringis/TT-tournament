"""
Match result parser service.

Provides deterministic fallback parsing for common natural language match result
patterns, plus integration with the AI engine for more complex transcripts.
All parsing is read-only - no database writes occur here.
"""

import re
import logging
from typing import Optional, Dict, List, Tuple, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Number-word mapping (zero through seven, plus common variants)
# ---------------------------------------------------------------------------
_NUMBER_WORDS: Dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    # Common shorthand / alternate spellings
    "won": 1,
    "none": 0,
    "nought": 0,
    "love": 0,
    "thirty": 3,   # table-tennis scoring shorthand sometimes used
    "forty": 4,
}

# Reverse map for normalisation
_INT_TO_WORD: Dict[int, str] = {v: k for k, v in _NUMBER_WORDS.items() if isinstance(k, str) and k not in ("won", "none", "nought", "love", "thirty", "forty")}


def word_to_int(word: str) -> Optional[int]:
    """Convert a number word (or digit string) to an integer."""
    cleaned = word.strip().lower()
    if cleaned.isdigit():
        return int(cleaned)
    return _NUMBER_WORDS.get(cleaned)


def normalize_score(score_str: str) -> Optional[str]:
    """
    Normalise a score string into the canonical 'X-Y' form.

    Accepts:
      - Digit forms: "3-1", "3 to 1", "3:1"
      - Word forms:  "three-one", "three to one", "three one"
      - Mixed:      "3-one"

    Returns None if the score cannot be parsed.
    """
    # Strip surrounding whitespace and lowercase
    s = score_str.strip().lower()

    # Replace common separators with a single hyphen
    s = re.sub(r"\s+to\s+", "-", s)
    # Collapse any whitespace around hyphens to avoid double hyphens
    s = re.sub(r"\s*-\s*", "-", s)
    # Replace any remaining whitespace runs with hyphens
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r":", "-", s)

    parts = s.split("-")
    if len(parts) != 2:
        return None

    left = word_to_int(parts[0].strip())
    right = word_to_int(parts[1].strip())

    if left is None or right is None:
        return None

    return f"{left}-{right}"


# ---------------------------------------------------------------------------
# Deterministic fallback parser
# ---------------------------------------------------------------------------
# Patterns we handle without calling the LLM:
#   1. "<A> beat <B> <score>"
#   2. "<A> defeated <B> <score>"
#   3. "<A> wins over <B> <score>"
#   4. "<B> lost to <A> <score>"
#   5. "<A> beat <B> <word>-<word>"  (e.g. "three-one")

_WIN_PATTERNS = [
    # (regex, group_for_player_a, group_for_player_b, group_for_score)
    # player_a beat player_b score
    (re.compile(r"^(?P<a>.+?)\s+beat\s+(?P<b>.+?)\s+(?P<score>.+)$", re.IGNORECASE),
     "a", "b", "score"),
    # player_a defeated player_b score
    (re.compile(r"^(?P<a>.+?)\s+defeated\s+(?P<b>.+?)\s+(?P<score>.+)$", re.IGNORECASE),
     "a", "b", "score"),
    # player_a wins over player_b score
    (re.compile(r"^(?P<a>.+?)\s+wins\s+over\s+(?P<b>.+?)\s+(?P<score>.+)$", re.IGNORECASE),
     "a", "b", "score"),
    # player_b lost to player_a score  (note: a and b are swapped in the pattern)
    (re.compile(r"^(?P<b>.+?)\s+lost\s+to\s+(?P<a>.+?)\s+(?P<score>.+)$", re.IGNORECASE),
     "a", "b", "score"),
]


def _extract_players_and_score(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to extract player names and a normalised score from *text* using
    deterministic regex patterns.

    Returns a dict with keys: player_a, player_b, score, winner, confidence
    or None if no pattern matches.
    """
    for pattern, a_key, b_key, score_key in _WIN_PATTERNS:
        m = pattern.match(text.strip())
        if not m:
            continue

        player_a = m.group(a_key).strip()
        player_b = m.group(b_key).strip()
        raw_score = m.group(score_key).strip()

        # Normalise the score
        norm_score = normalize_score(raw_score)
        if norm_score is None:
            # Could not parse score – treat as ambiguous
            return {
                "player_a": player_a,
                "player_b": player_b,
                "score": None,
                "winner": player_a,  # assumed winner from the verb
                "confidence": 0.5,
                "warnings": [f"Could not normalise score '{raw_score}'"],
            }

        # Determine winner from the pattern
        if "lost to" in pattern.pattern:
            winner = player_a
        else:
            winner = player_a

        return {
            "player_a": player_a,
            "player_b": player_b,
            "score": norm_score,
            "winner": winner,
            "confidence": 0.9,
            "warnings": [],
        }

    return None


# ---------------------------------------------------------------------------
# High-level parse function
# ---------------------------------------------------------------------------

def parse_match_result_fallback(text: str) -> Dict[str, Any]:
    """
    Parse *text* using deterministic rules only.

    Returns a dict with keys matching the MatchResultParseResponse schema
    (status, transcript, player1, player2, winner, score, confidence, warnings, raw).
    """
    warnings: List[str] = []

    if not text or not text.strip():
        return {
            "status": "error",
            "transcript": text or "",
            "player1": None,
            "player2": None,
            "winner": None,
            "score": None,
            "confidence": 0.0,
            "warnings": ["Empty transcript provided"],
            "raw": None,
        }

    result = _extract_players_and_score(text)

    if result is None:
        return {
            "status": "needs_review",
            "transcript": text,
            "player1": None,
            "player2": None,
            "winner": None,
            "score": None,
            "confidence": 0.0,
            "warnings": ["Could not parse match result from transcript. Please enter manually."],
            "raw": None,
        }

    player_a = result["player_a"]
    player_b = result["player_b"]
    score = result["score"]
    winner = result["winner"]
    confidence = result["confidence"]
    parse_warnings = result.get("warnings", [])

    # Validate winner is one of the players
    if winner not in (player_a, player_b):
        warnings.append(f"Winner '{winner}' is not one of the players. Defaulting to {player_a}.")
        winner = player_a
        confidence *= 0.7

    # If score is missing, lower confidence
    if score is None:
        warnings.append("Score could not be determined.")
        confidence = min(confidence, 0.4)

    # Check for identical player names
    if player_a.lower() == player_b.lower():
        warnings.append("Both player names appear identical. Please verify.")
        confidence = min(confidence, 0.3)

    status = "success" if confidence >= 0.7 and not warnings else "needs_review"

    return {
        "status": status,
        "transcript": text,
        "player1": player_a,
        "player2": player_b,
        "winner": winner,
        "score": score,
        "confidence": round(confidence, 2),
        "warnings": warnings + parse_warnings,
        "raw": result,
    }


def parse_match_result(
    text: str,
    ai_engine: Optional[Any] = None,
    tournament_id: Optional[int] = None,
    match_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Parse a match result from *text*.

    Strategy:
      1. Try deterministic fallback parser first.
      2. If fallback returns 'needs_review' or 'error', optionally call the
         AI engine (if provided) as a second opinion.
      3. Never write to the database.

    Returns a dict matching MatchResultParseResponse.
    """
    # Step 1: deterministic fallback
    fallback = parse_match_result_fallback(text)

    # If fallback succeeded with high confidence, return it directly
    if fallback["status"] == "success" and fallback["confidence"] >= 0.8:
        return fallback

    # Step 2: try AI engine if available
    if ai_engine is not None:
        try:
            ai_result = ai_engine.parse_match_result(text, match_id=None)
            # ai_engine.parse_match_result returns a MatchResult or dict
            if hasattr(ai_result, "model_dump"):
                ai_dict = ai_result.model_dump()
            elif hasattr(ai_result, "dict"):
                ai_dict = ai_result.dict()
            else:
                ai_dict = dict(ai_result) if ai_result else {}

            # Normalise AI result into our response shape
            player_a = ai_dict.get("player_a") or ai_dict.get("player1")
            player_b = ai_dict.get("player_b") or ai_dict.get("player2")
            player_a_score = ai_dict.get("player_a_score") or ai_dict.get("score_a")
            player_b_score = ai_dict.get("player_b_score") or ai_dict.get("score_b")
            winner = ai_dict.get("winner")

            # Build score string if we have individual scores
            ai_score = None
            if player_a_score is not None and player_b_score is not None:
                ai_score = f"{player_a_score}-{player_b_score}"

            # Validate winner
            ai_warnings = []
            if winner and winner not in (player_a, player_b):
                ai_warnings.append(f"AI returned winner '{winner}' not in player list.")
                winner = player_a  # fallback

            ai_confidence = 0.7  # AI is less certain than deterministic parse

            # Merge with fallback: prefer AI values when available, keep fallback warnings
            merged = {
                "status": "needs_review" if ai_warnings else "success",
                "transcript": text,
                "player1": player_a or fallback["player1"],
                "player2": player_b or fallback["player2"],
                "winner": winner or fallback["winner"],
                "score": ai_score or fallback["score"],
                "confidence": ai_confidence,
                "warnings": ai_warnings + fallback["warnings"],
                "raw": ai_dict,
            }
            return merged

        except Exception as e:
            logger.warning(f"AI engine parsing failed, falling back to deterministic result: {e}")
            # Fall through to return the deterministic result

    # Return the deterministic result (may be needs_review or error)
    return fallback
