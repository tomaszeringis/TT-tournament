#!/usr/bin/env python3
"""Import tournament platform data from JSON export."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tournament_platform.models import (
    Base,
    Tournament,
    Player,
    TournamentParticipant,
    Match,
    RatingHistory,
    VenueTable,
    Announcement,
    AuditLog,
    Stage,
    Group,
    Entry,
    MatchPointEvent,
    VoiceEvent,
    CommentaryEvent,
)
from tournament_platform.core.db_config import SessionLocal, engine


def _deserialize(value):
    """Convert JSON-safe values back to SQLAlchemy-compatible values."""
    if isinstance(value, dict):
        return value
    return value


def import_data(input_path: str, clear_existing: bool = False) -> None:
    """Import tournament data from a JSON file into the current database."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    session = SessionLocal()
    try:
        if clear_existing:
            print("Clearing existing data...")
            session.query(MatchPointEvent).delete()
            session.query(VoiceEvent).delete()
            session.query(CommentaryEvent).delete()
            session.query(Entry).delete()
            session.query(Group).delete()
            session.query(Stage).delete()
            session.query(Match).delete()
            session.query(TournamentParticipant).delete()
            session.query(Announcement).delete()
            session.query(AuditLog).delete()
            session.query(RatingHistory).delete()
            session.query(VenueTable).delete()
            session.query(Player).delete()
            session.query(Tournament).delete()
            session.commit()
        
        # Import in dependency order
        imports = [
            ("tournaments", Tournament),
            ("players", Player),
            ("venue_tables", VenueTable),
            ("stages", Stage),
            ("groups", Group),
            ("tournament_participants", TournamentParticipant),
            ("matches", Match),
            ("entries", Entry),
            ("rating_history", RatingHistory),
            ("announcements", Announcement),
            ("audit_logs", AuditLog),
            ("match_point_events", MatchPointEvent),
            ("voice_events", VoiceEvent),
            ("commentary_events", CommentaryEvent),
        ]
        
        total = 0
        for key, model in imports:
            rows = data.get(key, [])
            if not rows:
                continue
            
            # Map JSON keys back to model columns
            for row in rows:
                obj = model()
                for col in model.__table__.columns:
                    col_name = col.name
                    if col_name in row:
                        setattr(obj, col_name, row[col_name])
                session.add(obj)
                total += 1
            
            print(f"Imported {len(rows)} {key}")
        
        session.commit()
        print(f"Import complete. {total} total records imported.")
    except Exception as e:
        session.rollback()
        print(f"Import failed: {e}")
        sys.exit(1)
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Import tournament data from JSON")
    parser.add_argument("input", help="Input JSON file path")
    parser.add_argument("--clear", action="store_true", help="Clear existing data before import")
    args = parser.parse_args()
    import_data(args.input, clear_existing=args.clear)


if __name__ == "__main__":
    main()
