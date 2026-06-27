from tournament_platform.models import Player, Match, Tournament, MatchStatus, SessionLocal

print("Models imported successfully")

try:
    db = SessionLocal()
    player_count = db.query(Player).count()
    match_count = db.query(Match).count()
    tournament_count = db.query(Tournament).count()
    db.close()

    print("[OK] Database accessible")
    print(f"  Players: {player_count}")
    print(f"  Matches: {match_count}")
    print(f"  Tournaments: {tournament_count}")
except Exception as e:
    print("[ERR] Database error: {e}")
    import traceback
    traceback.print_exc()

