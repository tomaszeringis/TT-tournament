"""
Rating intelligence helpers for leaderboard, history, and match preview.

These functions are pure enough to be tested without FastAPI.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from tournament_platform.models import SessionLocal, Player, Match, MatchStatus, RatingHistory

logger = logging.getLogger(__name__)

# Threshold for considering a match an "upset" (rating difference in points)
UPSET_THRESHOLD = 100


def get_leaderboard_data(db_session=None) -> List[Dict[str, Any]]:
    """
    Build leaderboard data with wins/losses derived from matches.

    Returns a list of dicts with keys:
        player_id, name, rating, matches_played, wins, losses, last_rating_change
    """
    session = db_session or SessionLocal()
    close_session = db_session is None

    try:
        players = session.query(Player).order_by(Player.rating.desc()).all()
        result = []
        for p in players:
            # Count matches where this player was player1 or player2
            matches = session.query(Match).filter(
                ((Match.player1_id == p.id) | (Match.player2_id == p.id)),
                Match.status == MatchStatus.completed,
            ).all()

            matches_played = len(matches)
            wins = sum(1 for m in matches if m.winner_id == p.id)
            losses = matches_played - wins

            # Last rating change from history
            last_change = None
            if p.rating_history:
                sorted_history = sorted(p.rating_history, key=lambda h: h.timestamp)
                if len(sorted_history) >= 2:
                    last_change = sorted_history[-1].rating - sorted_history[-2].rating
                elif len(sorted_history) == 1:
                    # No previous entry to compare; treat as None
                    last_change = None

            result.append({
                "player_id": p.id,
                "name": p.name,
                "rating": p.rating,
                "matches_played": matches_played,
                "wins": wins,
                "losses": losses,
                "last_rating_change": last_change,
            })
        return result
    except Exception as e:
        logger.error(f"Error building leaderboard data: {e}")
        return []
    finally:
        if close_session:
            session.close()


def get_player_rating_history_data(player_id: int, db_session=None) -> List[Dict[str, Any]]:
    """
    Return rating history entries for a player as dicts.
    """
    session = db_session or SessionLocal()
    close_session = db_session is None

    try:
        history = (
            session.query(RatingHistory)
            .filter(RatingHistory.player_id == player_id)
            .order_by(RatingHistory.timestamp.asc())
            .all()
        )
        return [
            {
                "id": h.id,
                "rating": h.rating,
                "timestamp": h.timestamp.isoformat() if h.timestamp else None,
            }
            for h in history
        ]
    except Exception as e:
        logger.error(f"Error fetching rating history for player {player_id}: {e}")
        return []
    finally:
        if close_session:
            session.close()


def preview_match_rating(
    player1_id: int,
    player2_id: int,
    winner_id: Optional[int] = None,
    db_session=None,
) -> Dict[str, Any]:
    """
    Deterministic preview of rating changes and upset analysis for a match.

    Returns dict with:
        player1_id, player2_id, player1_rating, player2_rating,
        rating_difference, expected_favorite, upset_possible,
        explanation, predicted_rating_changes
    """
    session = db_session or SessionLocal()
    close_session = db_session is None

    try:
        p1 = session.query(Player).filter(Player.id == player1_id).first()
        p2 = session.query(Player).filter(Player.id == player2_id).first()

        if not p1 or not p2:
            return {
                "player1_id": player1_id,
                "player2_id": player2_id,
                "player1_rating": p1.rating if p1 else 0,
                "player2_rating": p2.rating if p2 else 0,
                "rating_difference": 0,
                "expected_favorite": 0,
                "upset_possible": False,
                "explanation": "One or both players not found.",
                "predicted_rating_changes": None,
            }

        r1 = p1.rating
        r2 = p2.rating
        diff = abs(r1 - r2)
        favorite = player1_id if r1 >= r2 else player2_id

        # Determine upset
        upset_possible = False
        if winner_id is not None and winner_id != favorite:
            upset_possible = True

        # Build explanation
        if winner_id is None:
            if diff == 0:
                explanation = (
                    f"{p1.name} and {p2.name} have identical ratings ({r1}). "
                    "No clear favorite."
                )
            else:
                fav_name = p1.name if favorite == player1_id else p2.name
                explanation = (
                    f"{fav_name} is the expected favorite with a {diff}-point rating advantage "
                    f"({r1} vs {r2})."
                )
        else:
            if upset_possible:
                winner_name = p1.name if winner_id == player1_id else p2.name
                fav_name = p1.name if favorite == player1_id else p2.name
                explanation = (
                    f"⚠️ Possible upset: {winner_name} (rating {r1 if winner_id == player1_id else r2}) "
                    f"is predicted to beat {fav_name} (rating {r2 if winner_id == player1_id else r1}). "
                    f"Rating gap is {diff} points."
                )
            else:
                winner_name = p1.name if winner_id == player1_id else p2.name
                explanation = (
                    f"{winner_name} is the expected winner with a {diff}-point rating advantage."
                )

        # Predict rating changes using the same logic as ranking-table-tennis
        try:
            from ranking_table_tennis.models.rankings import Rankings
            from ranking_table_tennis.configs import ConfigManager

            rm = ConfigManager()
            current_date = datetime.now().strftime("%y%m%d")
            rm.set_current_config(current_date)
            rankings = Rankings()

            points_to_winner, points_to_loser = rankings._points_to_assign(
                float(r1), float(r2)
            )
            factor = 2.0
            if rm.current_config and hasattr(rm.current_config.compute, "rating_factor"):
                factor = float(rm.current_config.compute.rating_factor)

            # Determine which player is winner/loser based on winner_id
            if winner_id == player1_id:
                w_change = int(float(points_to_winner) * factor)
                l_change = int(float(points_to_loser) * factor)
                predicted = {
                    p1.name: w_change,
                    p2.name: l_change,
                }
            elif winner_id == player2_id:
                w_change = int(float(points_to_winner) * factor)
                l_change = int(float(points_to_loser) * factor)
                predicted = {
                    p1.name: l_change,
                    p2.name: w_change,
                }
            else:
                # No winner specified; show both directions
                predicted = {
                    p1.name: int(float(points_to_winner) * factor),
                    p2.name: int(float(points_to_loser) * factor),
                }
        except Exception as e:
            logger.warning(f"Could not compute predicted rating changes: {e}")
            predicted = None

        return {
            "player1_id": player1_id,
            "player2_id": player2_id,
            "player1_rating": r1,
            "player2_rating": r2,
            "rating_difference": diff,
            "expected_favorite": favorite,
            "upset_possible": upset_possible,
            "explanation": explanation,
            "predicted_rating_changes": predicted,
        }
    except Exception as e:
        logger.error(f"Error previewing match rating: {e}")
        return {
            "player1_id": player1_id,
            "player2_id": player2_id,
            "player1_rating": 0,
            "player2_rating": 0,
            "rating_difference": 0,
            "expected_favorite": 0,
            "upset_possible": False,
            "explanation": f"Error computing preview: {e}",
            "predicted_rating_changes": None,
        }
    finally:
        if close_session:
            session.close()
