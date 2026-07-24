#!/usr/bin/env python3
"""Migrate tournament data from local SQLite to external PostgreSQL database.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \\
        --sqlite-url "sqlite:///data/tournament.db" \\
        --postgres-url "postgresql+psycopg2://user:pass@host:5432/db?sslmode=require"

Environment variables:
    SQLITE_DATABASE_URL  - Source SQLite database URL
    DATABASE_URL         - Target PostgreSQL database URL
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {k: _serialize(v) for k, v in value.__dict__.items() if not k.startswith("_")}
    return value


def dump_all(session):
    data = {
        "tournaments": [_serialize(r) for r in session.query(Tournament).all()],
        "players": [_serialize(r) for r in session.query(Player).all()],
        "venue_tables": [_serialize(r) for r in session.query(VenueTable).all()],
        "stages": [_serialize(r) for r in session.query(Stage).all()],
        "groups": [_serialize(r) for r in session.query(Group).all()],
        "tournament_participants": [_serialize(r) for r in session.query(TournamentParticipant).all()],
        "matches": [_serialize(r) for r in session.query(Match).all()],
        "entries": [_serialize(r) for r in session.query(Entry).all()],
        "rating_history": [_serialize(r) for r in session.query(RatingHistory).all()],
        "announcements": [_serialize(r) for r in session.query(Announcement).all()],
        "audit_logs": [_serialize(r) for r in session.query(AuditLog).all()],
        "match_point_events": [_serialize(r) for r in session.query(MatchPointEvent).all()],
        "voice_events": [_serialize(r) for r in session.query(VoiceEvent).all()],
        "commentary_events": [_serialize(r) for r in session.query(CommentaryEvent).all()],
    }
    return data


def import_all(session, data):
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
    print(f"Migration complete. {total} total records imported.")


def main():
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL")
    parser.add_argument("--sqlite-url", help="Source SQLite database URL")
    parser.add_argument("--postgres-url", help="Target PostgreSQL database URL")
    parser.add_argument("--skip-create", action="store_true", help="Skip creating tables in target")
    args = parser.parse_args()
    
    sqlite_url = args.sqlite_url or os.getenv("SQLITE_DATABASE_URL")
    postgres_url = args.postgres_url or os.getenv("DATABASE_URL")
    
    if not sqlite_url:
        print("Error: --sqlite-url or SQLITE_DATABASE_URL is required")
        sys.exit(1)
    if not postgres_url:
        print("Error: --postgres-url or DATABASE_URL is required")
        sys.exit(1)
    
    print(f"Source: {sqlite_url}")
    print(f"Target: {postgres_url.replace('://', '://****:****@') if '://' in postgres_url else postgres_url}")
    
    # Read from SQLite
    sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    SqliteSession = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)
    sqlite_session = SqliteSession()
    
    try:
        data = dump_all(sqlite_session)
        total_records = sum(len(v) for v in data.values())
        print(f"Read {total_records} records from SQLite")
    finally:
        sqlite_session.close()
        sqlite_engine.dispose()
    
    # Write to PostgreSQL
    postgres_engine = create_engine(postgres_url, pool_pre_ping=True)
    PostgresSession = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)
    postgres_session = PostgresSession()
    
    try:
        if not args.skip_create:
            print("Creating tables in target database...")
            Base.metadata.create_all(bind=postgres_engine)
        
        import_all(postgres_session, data)
    finally:
        postgres_session.close()
        postgres_engine.dispose()


if __name__ == "__main__":
    main()
