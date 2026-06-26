import sys
import os
import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import joinedload

# Import the library
from ranking_table_tennis.models.rankings import Rankings
from ranking_table_tennis.configs import ConfigManager

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from models import Player, SessionLocal, RatingHistory
except ImportError:
    Player = None
    SessionLocal = None
    RatingHistory = None

logger = logging.getLogger(__name__)

class RatingManager:
    """
    Manages player ratings using the ranking-table-tennis library.
    """
    def __init__(self):
        self.cm = ConfigManager()
        # Initialize with current date in YYMMDD format
        current_date = datetime.now().strftime("%y%m%d")
        try:
            self.cm.set_current_config(current_date)
        except Exception as e:
            logger.error(f"Failed to set current config for ranking-table-tennis: {e}")
        
        # Rankings object without initial data
        self.rankings = Rankings()

    def update_ratings(self, winner_id: int, loser_id: int, db_session=None):
        """
        Fetches current ratings, calculates new ones, and saves them back to the database.
        """
        if not Player:
            logger.error("Player model not loaded.")
            return

        session = db_session or (SessionLocal() if SessionLocal else None)
        if not session:
            logger.error("Database session not available.")
            return

        try:
            winner = session.query(Player).filter(Player.id == winner_id).first()
            loser = session.query(Player).filter(Player.id == loser_id).first()

            if not winner or not loser:
                logger.error(f"Player(s) not found: winner_id={winner_id}, loser_id={loser_id}")
                return

            # Calculate points to assign using the library's logic
            # _points_to_assign(winner_rating, loser_rating) -> (to_winner, to_loser)
            points_to_winner, points_to_loser = self.rankings._points_to_assign(
                float(winner.rating), float(loser.rating)
            )
            
            # Use the default rating factor from config
            factor = 2.0  # Default fallback
            if self.cm.current_config and hasattr(self.cm.current_config.compute, 'rating_factor'):
                factor = float(self.cm.current_config.compute.rating_factor)
            
            winner_change = float(points_to_winner) * factor
            loser_change = float(points_to_loser) * factor
            
            # Apply changes
            winner.rating += int(winner_change)
            loser.rating -= int(loser_change)
            
            # Ensure ratings don't go below a reasonable floor (e.g., 0)
            if loser.rating < 0:
                loser.rating = 0

            # Add to history if model is available
            if RatingHistory:
                history_winner = RatingHistory(player_id=winner.id, rating=winner.rating)
                history_loser = RatingHistory(player_id=loser.id, rating=loser.rating)
                session.add(history_winner)
                session.add(history_loser)

            session.commit()
            logger.info(f"Ratings updated: {winner.name} ({winner.rating}), {loser.name} ({loser.rating})")
            
        except Exception as e:
            logger.error(f"Error updating ratings: {e}")
            session.rollback()
        finally:
            if not db_session:
                session.close()

    def get_leaderboard(self, db_session=None) -> List:
        """
        Returns a list of players sorted by their current rating.
        """
        if not Player:
            return []

        session = db_session or (SessionLocal() if SessionLocal else None)
        if not session:
            return []

        try:
            players = session.query(Player).options(joinedload(Player.rating_history)).order_by(Player.rating.desc()).all()
            return players
        finally:
            if not db_session:
                session.close()

    def get_rating_history(self, player_id: int, db_session=None) -> List:
        """
        Returns the rating history for a specific player.
        """
        if not RatingHistory:
            return []

        session = db_session or (SessionLocal() if SessionLocal else None)
        if not session:
            return []

        try:
            history = session.query(RatingHistory).filter(RatingHistory.player_id == player_id).order_by(RatingHistory.timestamp.asc()).all()
            return history
        except Exception as e:
            logger.error(f"Error fetching rating history: {e}")
            return []
        finally:
            if not db_session:
                session.close()
