# Fix Alembic Migration: table voice_events already exists

## Problem
Running `python -m alembic -c tournament_platform/alembic.ini upgrade head` fails with:
```
sqlite3.OperationalError: table voice_events already exists
```

## Root Cause
- `models.py` defines `VoiceEvent` and `VoiceCommand` ORM models (`models.py:465`, `models.py:493`).
- `init_db()` calls `Base.metadata.create_all(bind=engine)` (`models.py:516`), which creates **all** model tables outside of Alembic.
- The database (`tournament_platform/data/tournament.db`) already contains `voice_events` and `voice_commands` tables.
- `alembic_version` records `009_add_event_models` as the last applied migration.
- Migration `010_add_voice_event_models.py` tries to `CREATE TABLE voice_events` and `voice_commands`, causing the duplicate-table error.

## Fix Plan

### Step 1: Make migration 010 idempotent
Edit `tournament_platform/alembic/versions/010_add_voice_event_models.py`:
- Replace `op.create_table('voice_events', ...)` with a raw-SQL `CREATE TABLE IF NOT EXISTS voice_events ...` via `op.execute()`, wrapped in a `has_table()` check from the connection.
- Replace `op.create_table('voice_commands', ...)` similarly.
- Keep the index creations idempotent: wrap each `op.create_index` in `op.execute("CREATE INDEX IF NOT EXISTS ...")` (or use `op.get_bind().dialect.has_table()` to skip if table already exists).

### Step 2: Verify no other migrations have the same pattern
Scan earlier migrations (`001_initial.py` through `009_add_event_models.py`) to ensure they don't also create tables that might already exist due to `create_all`. If found, apply the same idempotent pattern.

### Step 3: Validate
Run:
```bash
python -m alembic -c tournament_platform/alembic.ini upgrade head
```
Expected result: migration applies cleanly; `alembic_version` advances to `010_add_voice_event_models`.

## Risk / Rollback
- If the existing `voice_events`/`voice_commands` tables have a schema mismatch with the migration, the idempotent migration will skip creation but the app may still fail at runtime. In that case, compare columns via `PRAGMA table_info(voice_events)` and reconcile the model vs. migration definitions.
- No data loss expected; this only changes DDL execution behavior.
