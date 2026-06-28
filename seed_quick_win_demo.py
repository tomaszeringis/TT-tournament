#!/usr/bin/env python
"""
Seed script for Quick Wins demo data.

Creates demo data for testing the quick-win features:
- 4-8 demo players (if they don't exist)
- One tournament (if it doesn't exist)
- Various match states: active, called, pending, delayed, completed
- Venue tables

Safe to run multiple times without duplicating data.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add the project root to the path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tournament_platform.models import (
    SessionLocal,
    Player,
    Tournament,
    Match,
    MatchStatus,
    VenueTable,
    init_db,
)


def seed_demo_data():
    """Seed demo data for quick wins testing."""
    # Ensure database tables exist
    init_db()
    
    db = SessionLocal()
    
    try:
        # Create demo players (if they don't exist)
        player_names = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Henry"]
        players = {}
        
        for name in player_names:
            existing = db.query(Player).filter(Player.name == name).first()
            if existing:
                players[name] = existing
                print(f"  [EXISTS] Player: {name}")
            else:
                # Use example.com email so generated players are identifiable
                player = Player(name=name, email=f"{name.lower()}@example.com", rating=1200)
                db.add(player)
                db.flush()  # Get the ID without committing
                players[name] = player
                print(f"  [CREATED] Player: {name}")
        
        # Create tournament (if it doesn't exist)
        tournament_name = "Quick Wins Demo Tournament"
        tournament = db.query(Tournament).filter(Tournament.name == tournament_name).first()

        if tournament:
            print(f"  [EXISTS] Tournament: {tournament_name}")
        else:
            tournament = Tournament(
                name=tournament_name,
                description="[generated-test-data] Demo tournament for quick wins testing",
                tournament_type="round-robin"
            )
            db.add(tournament)
            db.flush()
            print(f"  [CREATED] Tournament: {tournament_name}")
        
        # Create venue tables (if they don't exist)
        table_names = ["Table 1", "Table 2", "Table 3", "Table 4"]

        for table_name in table_names:
            existing = db.query(VenueTable).filter(VenueTable.name == table_name).first()
            if existing:
                print(f"  [EXISTS] Table: {table_name}")
            else:
                table = VenueTable(name=table_name, is_active=1, notes="[generated-test-data]")
                db.add(table)
                print(f"  [CREATED] Table: {table_name}")
        
        # Create matches with various states
        now = datetime.now(timezone.utc)
        
        # Check if we already have matches for this tournament
        existing_matches = db.query(Match).filter(Match.tournament_id == tournament.id).count()
        
        if existing_matches > 0:
            print(f"  [EXISTS] {existing_matches} matches already in tournament")
        else:
            # Active match on Table 1
            match1 = Match(
                player1=players["Alice"].name,
                player2=players["Bob"].name,
                player1_id=players["Alice"].id,
                player2_id=players["Bob"].id,
                status=MatchStatus.active,
                call_status="active",
                location="Table 1",
                scheduled_time=now - timedelta(minutes=5),
                started_at=now - timedelta(minutes=5),
                tournament_id=tournament.id,
                round_number=1,
            )
            db.add(match1)
            print("  [CREATED] Active match: Alice vs Bob on Table 1")
            
            # Called match on Table 2
            match2 = Match(
                player1=players["Charlie"].name,
                player2=players["Diana"].name,
                player1_id=players["Charlie"].id,
                player2_id=players["Diana"].id,
                status=MatchStatus.pending,
                call_status="called",
                location="Table 2",
                scheduled_time=now + timedelta(minutes=10),
                called_at=now,
                tournament_id=tournament.id,
                round_number=1,
            )
            db.add(match2)
            print("  [CREATED] Called match: Charlie vs Diana on Table 2")
            
            # Pending upcoming match
            match3 = Match(
                player1=players["Eve"].name,
                player2=players["Frank"].name,
                player1_id=players["Eve"].id,
                player2_id=players["Frank"].id,
                status=MatchStatus.pending,
                call_status="not_called",
                location="Table 3",
                scheduled_time=now + timedelta(hours=1),
                tournament_id=tournament.id,
                round_number=1,
            )
            db.add(match3)
            print("  [CREATED] Pending match: Eve vs Frank on Table 3")
            
            # Delayed match
            match4 = Match(
                player1=players["Grace"].name,
                player2=players["Henry"].name,
                player1_id=players["Grace"].id,
                player2_id=players["Henry"].id,
                status=MatchStatus.pending,
                call_status="delayed",
                location="Table 4",
                scheduled_time=now - timedelta(minutes=30),
                delayed_until=now + timedelta(minutes=30),
                operator_note="Waiting for player availability",
                tournament_id=tournament.id,
                round_number=1,
            )
            db.add(match4)
            print("  [CREATED] Delayed match: Grace vs Henry on Table 4")
            
            # Completed match with score
            match5 = Match(
                player1=players["Alice"].name,
                player2=players["Charlie"].name,
                player1_id=players["Alice"].id,
                player2_id=players["Charlie"].id,
                winner=players["Alice"].name,
                winner_id=players["Alice"].id,
                score="3-1",
                status=MatchStatus.completed,
                call_status="completed",
                location="Table 1",
                scheduled_time=now - timedelta(hours=2),
                completed_at=now - timedelta(hours=1, minutes=30),
                tournament_id=tournament.id,
                round_number=1,
            )
            db.add(match5)
            print("  [CREATED] Completed match: Alice beat Charlie 3-1 on Table 1")
            
            # Another completed match
            match6 = Match(
                player1=players["Bob"].name,
                player2=players["Diana"].name,
                player1_id=players["Bob"].id,
                player2_id=players["Diana"].id,
                winner=players["Diana"].name,
                winner_id=players["Diana"].id,
                score="2-3",
                status=MatchStatus.completed,
                call_status="completed",
                location="Table 2",
                scheduled_time=now - timedelta(hours=3),
                completed_at=now - timedelta(hours=2, minutes=30),
                tournament_id=tournament.id,
                round_number=1,
            )
            db.add(match6)
            print("  [CREATED] Completed match: Diana beat Bob 3-2 on Table 2")
        
        db.commit()
        print("\n[OK] Demo data seeded successfully!")
        
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Error seeding demo data: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Seeding Quick Wins Demo Data")
    print("=" * 50)
    seed_demo_data()