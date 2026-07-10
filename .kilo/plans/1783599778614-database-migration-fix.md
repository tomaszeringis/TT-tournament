# Fix Alembic Migration Conflict

## Current State
- **Database:** `tournament_platform/data/tournament.db`
- **Alembic version:** `009_add_event_models`
- **Tables created outside Alembic:** `voice_events`, `voice_commands` (created by `init_db()` in `models.py:515` via tests/demo code)
- **Typical conflicting files:** tests under `tests/*.py` and `seed_quick_win_demo.py` call `init_db()`
- **models.py `init_db()`** runs `Base.metadata.create_all(bind=engine)` at import/use time
- **Error:** `sqlite3.OperationalError: table voice_events already exists` because migration `010` tries to create them

## Plan
1. **Backup the database** before any changes.
   - Copy `tournament_platform/data/tournament.db` to `tournament_platform/data/tournament.db.bak`

2. **Drop only the conflicting tables** to restore schema to migration `009` state without losing other data.
   - Execute `DROP TABLE IF EXISTS voice_commands;`
   - Execute `DROP TABLE IF EXISTS voice_events;`
   - These are the only tables created outside Alembic ahead of version `010`.

3. **Re-run Alembic** to apply migration `010` cleanly.
   - `python -m alembic -c tournament_platform/alembic.ini upgrade head`
   - Expected result: `010_add_voice_event_models` applied; tables recreated by migration; `alembic_version` updated to `010_add_voice_event_models`

4. **Fix root cause** to prevent future mismatches.
   - In `tournament_platform/models.py`, change `init_db()` so it no longer runs `Base.metadata.create_all(bind=engine)` unconditionally.
   - Recommended: make `init_db()` a no-op wrapper that only logs when used in runtime, or remove its body entirely.
   - Audit test files that import `init_db` and ensure they do not depend on auto-creation via `metadata.create_all` during pytest runs.

5. **Validation**
   - Confirm `alembic_version` = `010_add_voice_event_models`
   - Confirm `voice_events` and `voice_commands` exist with expected columns/indexes using SQLite pragmas or DB inspection
   - Spot-check at least one pre-existing table (e.g., `players`, `matches`, `tournaments`) row count unchanged from backup
   - Run existing tests to ensure no breakage from removing/create_all side effects

## Risks
- If tests rely on `init_db()` auto-creating schema in-memory/on-disk, they may start failing after step 4. Mitigation: fix tests to set up schema explicitly or use the app's migration path instead of `metadata.create_all`.
- If other devs have local DBs, they will need to apply steps 1-3 locally.
