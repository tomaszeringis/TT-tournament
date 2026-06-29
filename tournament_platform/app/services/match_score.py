"""
Match Scoring Utilities

Pure functions for parsing, validating, and summarizing table tennis match scores.
Independent of Streamlit and database code.
"""

import re
from typing import Optional, Tuple, List, Dict


def parse_game_score(text: str) -> Optional[Tuple[int, int]]:
    """
    Parse a game score from text.
    
    Supports formats:
    - "11-3"
    - "11 - 3"
    - "12-3"
    - "11 to 3"
    - "11 dash 3"
    - "player one wins 11 3"
    - "player two wins 12 10"
    
    Returns:
        Tuple of (score1, score2) if valid, None if parsing fails.
    """
    if not text:
        return None
    
    text = text.strip().lower()
    
    # Remove common prefixes
    for prefix in ["player one wins", "player two wins", "player1 wins", "player2 wins"]:
        text = text.replace(prefix, "").strip()
    
    # Extract two integers from the text
    numbers = re.findall(r'\d+', text)
    if len(numbers) != 2:
        return None
    
    try:
        score1 = int(numbers[0])
        score2 = int(numbers[1])
        return (score1, score2)
    except ValueError:
        return None


def validate_game_score(score1: int, score2: int) -> bool:
    """
    Validate a game score.
    
    Rules:
    - No ties
    - No negative numbers
    - Winner must have >= 11 points
    - Winner must have at least 2 point lead
    
    Returns:
        True if valid, False otherwise.
    """
    # No ties
    if score1 == score2:
        return False
    
    # No negative numbers
    if score1 < 0 or score2 < 0:
        return False
    
    # Determine winner
    winner = score1 if score1 > score2 else score2
    loser = score2 if score1 > score2 else score1
    
    # Winner must have at least 11 points
    if winner < 11:
        return False
    
    # Winner must have at least 2 point lead
    if winner - loser < 2:
        return False
    
    return True


def get_game_winner(score1: int, score2: int) -> Optional[int]:
    """
    Get the winner of a game (1 or 2).
    
    Returns:
        1 if player1 wins, 2 if player2 wins, None if invalid/tie.
    """
    if score1 > score2:
        return 1
    elif score2 > score1:
        return 2
    return None


def summarize_match(game_scores: List[Tuple[int, int]]) -> Dict:
    """
    Summarize a match from a list of game scores.
    
    Args:
        game_scores: List of (score1, score2) tuples for each game.
        
    Returns:
        Dict with:
        - player1_games: int
        - player2_games: int
        - winner_side: 1|2|None
        - is_complete: bool
        - score_string: str (e.g., "11-3, 12-3, 11-8")
    """
    player1_games = 0
    player2_games = 0
    
    for score1, score2 in game_scores:
        if score1 > score2:
            player1_games += 1
        else:
            player2_games += 1
    
    # Determine winner
    winner_side = None
    if player1_games >= 3:
        winner_side = 1
    elif player2_games >= 3:
        winner_side = 2
    
    # Build score string
    score_string = ", ".join(f"{s1}-{s2}" for s1, s2 in game_scores)
    
    return {
        "player1_games": player1_games,
        "player2_games": player2_games,
        "winner_side": winner_side,
        "is_complete": winner_side is not None,
        "score_string": score_string,
    }