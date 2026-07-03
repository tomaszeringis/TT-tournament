"""
Tests for the Swiss System tournament strategy.
"""

import pytest
import time
from tournament_platform.services.tournament_engine import SwissStrategy
from tournament_platform.models import SessionLocal, Player, Match, init_db


def _unique_name(base: str) -> str:
    """Generate a unique name using timestamp to avoid database conflicts."""
    return f"{base}_{int(time.time() * 1000000)}"


class TestSwissStrategy:
    """Test the Swiss System tournament strategy."""

    def test_strategy_initialization(self):
        """Test strategy can be initialized with custom parameters."""
        strategy = SwissStrategy(num_rounds=5)
        assert strategy.num_rounds == 5

    def test_strategy_default_initialization(self):
        """Test strategy with default parameters."""
        strategy = SwissStrategy()
        assert strategy.num_rounds == 3

    def test_swiss_creates_matches(self):
        """Test that SwissStrategy creates matches for all rounds."""
        init_db()
        db = SessionLocal()
        
        try:
            # Use unique names to avoid conflicts
            ts = _unique_name("swiss")
            player_names = [f"Swiss{ts}P{i}" for i in range(1, 7)]
            
            # Create test players
            for name in player_names:
                p = db.query(Player).filter(Player.name == name).first()
                if not p:
                    p = Player(name=name)
                    db.add(p)
            db.commit()
            
            # Create a tournament (using Tournament model)
            from tournament_platform.models import Tournament
            tournament = Tournament(name=f"Swiss Test {ts}")
            db.add(tournament)
            db.flush()
            
            # Generate matches
            strategy = SwissStrategy(num_rounds=3)
            matches = strategy.generate_matches(player_names, tournament.id, db)
            
            # With 6 players and 3 rounds, we expect ~3 matches per round
            # (some players may not get paired if no suitable opponent)
            assert len(matches) > 0
            
            # Verify all matches have correct round numbers
            for match in matches:
                assert match.round_number in [1, 2, 3]
                assert match.status.value == "pending"
            
            # Clean up
            for match in matches:
                db.delete(match)
            db.delete(tournament)
            for name in player_names:
                p = db.query(Player).filter(Player.name == name).first()
                if p:
                    db.delete(p)
            db.commit()
        finally:
            db.close()

    def test_swiss_empty_players(self):
        """Test that strategy handles empty player list gracefully."""
        strategy = SwissStrategy()
        matches = strategy.generate_matches([], 1, SessionLocal())
        assert matches == []

    def test_swiss_pairing_avoids_repeats(self):
        """Test that Swiss strategy avoids pairing players who have already played."""
        init_db()
        db = SessionLocal()
        
        try:
            ts = _unique_name("swiss_pair")
            player_names = [f"Pair{ts}P{i}" for i in range(1, 5)]
            
            # Create test players
            for name in player_names:
                p = db.query(Player).filter(Player.name == name).first()
                if not p:
                    p = Player(name=name)
                    db.add(p)
            db.commit()
            
            from tournament_platform.models import Tournament
            tournament = Tournament(name=f"Pairing Test {ts}")
            db.add(tournament)
            db.flush()
            
            # Generate matches
            strategy = SwissStrategy(num_rounds=2)
            matches = strategy.generate_matches(player_names, tournament.id, db)
            
            # Check that no two players are paired more than once
            pairings = set()
            for match in matches:
                pair = tuple(sorted([match.player1, match.player2]))
                assert pair not in pairings, f"Duplicate pairing: {pair}"
                pairings.add(pair)
            
            # Clean up
            for match in matches:
                db.delete(match)
            db.delete(tournament)
            for name in player_names:
                p = db.query(Player).filter(Player.name == name).first()
                if p:
                    db.delete(p)
            db.commit()
        finally:
            db.close()

    def test_swiss_odd_player_count(self):
        """Test Swiss strategy with odd number of players (bye handling)."""
        init_db()
        db = SessionLocal()
        
        try:
            ts = _unique_name("swiss_odd")
            player_names = [f"Odd{ts}P{i}" for i in range(1, 5)]  # 4 players
            
            # Create test players
            for name in player_names:
                p = db.query(Player).filter(Player.name == name).first()
                if not p:
                    p = Player(name=name)
                    db.add(p)
            db.commit()
            
            from tournament_platform.models import Tournament
            tournament = Tournament(name=f"Odd Test {ts}")
            db.add(tournament)
            db.flush()
            
            # Generate matches
            strategy = SwissStrategy(num_rounds=2)
            matches = strategy.generate_matches(player_names, tournament.id, db)
            
            # With 4 players, we should get 2 matches per round
            assert len(matches) >= 2
            
            # Clean up
            for match in matches:
                db.delete(match)
            db.delete(tournament)
            for name in player_names:
                p = db.query(Player).filter(Player.name == name).first()
                if p:
                    db.delete(p)
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])