#!/usr/bin/env python3
"""Repair database schema for existing Neon/PostgreSQL databases.

Adds missing additive columns (e.g. public_registration_token) to existing
tables without dropping or modifying any existing data.

Usage:
    python scripts/repair_database_schema.py

Environment:
    DATABASE_URL  - PostgreSQL or SQLite connection URL
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tournament_platform.core.db_config import (
    DATABASE_URL,
    engine,
    ensure_tournament_registration_columns,
    get_database_type,
    get_database_url_masked,
)


def main() -> None:
    db_type = get_database_type()
    print(f"Database backend: {db_type}")
    print(f"Connection: {get_database_url_masked()}")
    print()

    print("Checking and repairing schema...")
    result = ensure_tournament_registration_columns(engine)

    if result["added"]:
        print(f"Added columns: {', '.join(result['added'])}")
    if result["already_present"]:
        print(f"Already present: {', '.join(result['already_present'])}")
    if not result["added"] and not result["already_present"]:
        print("No tournament table found or no columns to repair.")

    print()
    print("Schema repair complete.")
    print("Note: If columns were added, restart the app for changes to take effect.")


if __name__ == "__main__":
    main()
