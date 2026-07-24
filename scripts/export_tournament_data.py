#!/usr/bin/env python3
"""Export tournament platform data to JSON for backup or migration."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

# Ensure project root is importable
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
from tournament_platform.core.db_config import SessionLocal, DATABASE_URL


def _serialize(value):
    """Convert SQLAlchemy model instances and dates to JSON-safe values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {k: _serialize(v) for k, v in value.__dict__.items() if not k.startswith("_")}
    return value


def dump_table(session: Session, model, filters=None):
    """Dump all rows from a table as a list of dicts."""
    query = session.query(model)
    if filters:
        query = query.filter_by(**filters)
    rows = query.all()
    return [_serialize(row) for row in rows]


def export_data(output_path: str) -> None:
    """Export all tournament data to a JSON file."""
    session = SessionLocal()
    try:
        data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "database_url": DATABASE_URL,
            "tournaments": dump_table(session, Tournament),
            "players": dump_table(session, Player),
            "tournament_participants": dump_table(session, TournamentParticipant),
            "matches": dump_table(session, Match),
            "rating_history": dump_table(session, RatingHistory),
            "venue_tables": dump_table(session, VenueTable),
            "announcements": dump_table(session, Announcement),
            "audit_logs": dump_table(session, AuditLog),
            "stages": dump_table(session, Stage),
            "groups": dump_table(session, Group),
            "entries": dump_table(session, Entry),
            "match_point_events": dump_table(session, MatchPointEvent),
            "voice_events": dump_table(session, VoiceEvent),
            "commentary_events": dump_table(session, CommentaryEvent),
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"Exported {sum(len(v) for k, v in data.items() if isinstance(v, list))} records to {output_path}")
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Export tournament data to JSON")
    parser.add_argument("output", help="Output JSON file path")
    args = parser.parse_args()
    export_data(args.output)


if __name__ == "__main__":
    main()
