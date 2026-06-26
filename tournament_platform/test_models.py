import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from models import Player, Match, Tournament, MatchStatus, SessionLocal

print("Models imported successfully")

try:
    db = SessionLocal()
    player_count = db.query(Player).count()
    match_count = db.query(Match).count()
    tournament_count = db.query(Tournament).count()
    db.close()

    print(f"✓ Database accessible")
    print(f"  Players: {player_count}")
    print(f"  Matches: {match_count}")
    print(f"  Tournaments: {tournament_count}")
except Exception as e:
    print(f"✗ Database error: {e}")
    import traceback
    traceback.print_exc()

