#!/usr/bin/env python3
"""
SQLite database backup utility.

Creates a timestamped backup of the tournament database.
Safe to run multiple times - will not modify the original database.
"""

import shutil
from pathlib import Path
from datetime import datetime


def get_database_path() -> Path:
    """
    Detect the database path from models.DATABASE_PATH if possible,
    otherwise fall back to the default location.
    """
    try:
        # Try to import from models to get the actual DATABASE_PATH
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "tournament_platform"))
        from models import DATABASE_PATH
        return Path(DATABASE_PATH)
    except Exception:
        # Fall back to default location
        return Path(__file__).parent.parent / "tournament_platform" / "data" / "tournament.db"


def backup_database() -> None:
    """Create a timestamped backup of the SQLite database."""
    db_path = get_database_path()
    backup_dir = Path(__file__).parent.parent / "backups"
    
    # Check if database exists
    if not db_path.exists():
        print(f"Database not found at {db_path}. Nothing to backup.")
        return
    
    # Create backups directory if it doesn't exist
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate timestamped backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"tournament_{timestamp}.db"
    
    # Copy the database
    shutil.copy2(db_path, backup_path)
    
    print(f"Backup created: {backup_path}")


if __name__ == "__main__":
    backup_database()