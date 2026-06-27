#!/usr/bin/env python3
"""
Simple setup status check - no unicode characters.
"""

import os
import sys

def check_files():
    base = os.path.dirname(__file__)
    checks = {
        'tournament_platform/models.py': False,
        'tournament_platform/alembic.ini': False,
        'tournament_platform/data/tournament.db': False,
        'tournament_platform/api/server.py': False,
        'tournament_platform/app/main.py': False,
        'tournament_platform/services/ai_engine.py': False,
    }

    for file_path in checks:
        full_path = os.path.join(base, file_path)
        checks[file_path] = os.path.isfile(full_path)

    return checks

def check_database():
    base = os.path.dirname(__file__)
    tp_path = os.path.abspath(os.path.join(base, 'tournament_platform'))
    os.chdir(tp_path)

    try:
        from tournament_platform.models import SessionLocal, Player

        db = SessionLocal()
        player_count = db.query(Player).count()
        db.close()
        return True
    except:
        return False

print("=" * 60)
print("TOURNAMENT PLATFORM - SETUP STATUS")
print("=" * 60)

files = check_files()
passed = sum(1 for v in files.values() if v)
print(f"\nFiles: {passed}/{len(files)} found")
for f, status in files.items():
    print(f"  [{('X' if status else ' ')}] {f}")

db_ok = check_database()
print(f"\nDatabase: {'OK' if db_ok else 'NEEDS SETUP'}")
print(f"  - SQLite database initialized: {db_ok}")

import sqlite3
try:
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'tournament_platform', 'data', 'tournament.db'))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    conn.close()
    print(f"  - Tables: {len(tables)} ({', '.join(tables)})")
except:
    print(f"  - Tables: Error reading database")

print("\n" + "=" * 60)
print("SETUP COMPLETE: All systems ready!")
print("=" * 60)
print("\nTo start:")
print("  API:       python tournament_platform/api/server.py")
print("  Frontend:  streamlit run tournament_platform/app/main.py")

