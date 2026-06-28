# Quick Wins - Tournament Platform

This document describes the quick-win features added to the Tournament Platform and how to verify them.

## Features Added

| # | Feature | Page / Endpoint | Description |
|---|---------|-----------------|-------------|
| 1 | **Public Schedule & Ranking Board** | Public Board page + `/api/public/*` | Read-only TV/projector display with current matches, standings, and recent results. |
| 2 | **Operator Match-Call Workflow** | Operator Console + `/api/operator/*` | Call, start, complete, delay, and reschedule matches with audit logging. |
| 3 | **Player Path View** | Public Board & Operator Console | View a player's match history and projected bracket path. |
| 4 | **Deterministic Text Shortcuts** | Operator Console Command Bar | Type commands like "call match 12 to table 3" for quick match management. |
| 5 | **Optional Vosk Voice Shortcuts** | Operator Console (if Vosk configured) | Offline speech-to-text for operator commands. |
| 6 | **Safe Match Result Parsing** | `POST /api/match/parse` | Parse natural language like "Alice beat Bob 3-1" into structured JSON. No database writes. |
| 7 | **Match Reporting UI** | Voice Scorekeeper → "Report Match Result" | 3-step flow: parse → review → confirm & submit. |
| 8 | **Ranking Intelligence** | Dashboard + `GET /api/ratings/leaderboard` | Live standings with wins/losses derived from completed matches. |
| 9 | **Rating Preview** | `POST /api/ratings/preview-match` | Preview rating impact and upset potential before a match. |
| 10 | **Tournament Rules Assistant** | AI Assistant → Rules Q&A tab + `POST /api/rules/ask` | Ask questions about tournament rules using RAG. |
| 11 | **Voice Privacy Safeguards** | Voice Scorekeeper + Tournament Setup | Local-first audio processing, temp file deletion by default, privacy notices. |
| 12 | **Active Match Selection** | Voice Scorekeeper → "Active Tournament Matches" | Select a match from an active tournament to prefill players and score the result. |
| 13 | **Announcements** | Operator Console + `/api/announcements/*` | Create and send announcements for match calls and stage starts. |

## How to Run the API

```powershell
# From the repository root
cd tournament_platform
python -m alembic upgrade head
python api/server.py
```

The API will be available at `http://localhost:8000` by default.

## How to Run Streamlit

```powershell
# From the repository root
streamlit run tournament_platform/app/main.py
```

Open `http://localhost:8501` in your browser.

## How to Open Public Board

1. Navigate to `http://localhost:8501`
2. Click on **"Public Board"** in the navigation sidebar
3. The board shows:
   - **Now Playing**: Active and called matches
   - **Coming Up**: Next 3 pending matches
   - **Delayed**: Matches that have been delayed
   - **Rankings**: Player standings with wins/losses
   - **Recent Results**: Last 5 completed matches
   - **Player Lookup**: Search for a player's path

## How to Open Operator Console

1. Navigate to `http://localhost:8501`
2. Click on **"Operator Console"** in the navigation sidebar
3. The console provides:
   - **Command Bar**: Text shortcuts for match management
   - **Table Status**: Overview of all tables and their current/next matches
   - **Match Queue**: List of all matches with call status and actions
   - **Player Path**: View a player's tournament journey
   - **Audit Log**: History of all operator state-changing actions

## How to Create Venue Tables

Tables can be created via the Tournament Setup page or directly in the database:

### Via UI (Tournament Setup)
1. Go to **Tournament Setup** page
2. Look for the "Venue Tables" section
3. Add tables with names like "Table 1", "Table 2", etc.

### Via Database (Alembic migration)
The `007_add_operator_workflow.py` migration creates the `venue_tables` table. After running migrations, you can add tables:

```python
# In a Python shell or script
from tournament_platform.models import SessionLocal, VenueTable, init_db
init_db()
db = SessionLocal()
for i in range(1, 5):
    table = VenueTable(name=f"Table {i}", is_active=1)
    db.add(table)
db.commit()
```

## How to Call/Delay/Reschedule a Match

### Via Operator Console UI

1. **Call a Match**:
   - Find the match in the queue with status "not_called"
   - Click **"📢 Call"** button
   - The match will move to "called" status

2. **Start a Match**:
   - Find a "called" match
   - Click **"▶️ Start"** button
   - The match will move to "active" status

3. **Complete a Match**:
   - Find an "active" match
   - Click **"✅ Complete"** button
   - The match will move to "completed" status

4. **Delay a Match**:
   - Find any match in the queue
   - Click **"⏸ Delay"** button
   - The match will be delayed for 15 minutes (configurable)

5. **Reschedule a Match**:
   - Find any match in the queue
   - Click **"📅 Reschedule"** button
   - Enter new time (ISO format) and optional table
   - The match will move to "queued" status

### Via Text Shortcuts (Command Bar)

Type these commands in the Operator Console Command Bar:

| Command | Action |
|---------|--------|
| `call match 12 to table 3` | Call match #12 to table #3 |
| `call match 12` | Call match #12 (no specific table) |
| `delay match 15 for 10 minutes` | Delay match #15 for 10 minutes |
| `show player path John Smith` | Show player path for John Smith |
| `next available table` | Find the next available table |

## How to Use Text Shortcuts

The Operator Console includes a **Command Bar** that accepts deterministic text commands:

1. Select a tournament from the dropdown
2. Type a command in the input field (e.g., "call match 12 to table 3")
3. The system will:
   - Parse the command and show the detected intent
   - Display a preview of the action
   - For state-changing commands, show a **Confirm Action** button
4. Click **Confirm Action** to execute the command

All state-changing commands create an audit log entry visible in the Audit Log section.

## How to Enable Optional Vosk Voice Shortcuts

Vosk provides offline speech-to-text for operator commands. To enable:

1. **Install Vosk**:
   ```powershell
   pip install vosk
   ```

2. **Download a Vosk model** (small model recommended for testing):
   ```powershell
   # Download small English model
   curl -L https://alphacephea.com/vosk/models/vosk-model-small-en-us-0.15.zip -o vosk-model.zip
   # Or on Windows, download manually from: https://alphacephea.com/vosk/models/
   ```

3. **Set environment variable**:
   ```powershell
   # In .env file or environment
   VOSK_MODEL_PATH=path/to/vosk-model-small-en-us-0.15
   ```

4. **Use in Operator Console**:
   - The voice interface will appear if Vosk is available
   - Speak commands like "call match 12 to table 3" or "next available table"

**Note**: Vosk is optional. The system works with text input only if Vosk is not available.

## Smoke-Check Instructions

Follow these steps to verify the quick wins:

```powershell
# 1. Apply database migrations
python -m alembic -c tournament_platform/alembic.ini upgrade head

# 2. Seed demo data
python seed_quick_win_demo.py

# 3. Start the API server (Terminal 1)
python tournament_platform/api/server.py

# 4. Start Streamlit (Terminal 2)
streamlit run tournament_platform/app/main.py

# 5. Visit in browser:
#    - http://localhost:8501 (Streamlit app)
#    - http://localhost:8000/docs (API docs)
#    - http://localhost:8000/health (Health check)
```

## Running Tests

```powershell
# Run all quick-win related tests
pytest tournament_platform/test_match_parser.py tournament_platform/test_rating_intelligence.py tournament_platform/test_operator_commands.py tournament_platform/test_tournament_read_models.py tournament_platform/test_voice_transcription.py tournament_platform/test_announcement_service.py -v

# Run compile check on all Python files
python -m compileall .

# Check database schema
python tournament_platform/check_schema.py

# Check database tables
python tournament_platform/check_tables.py
```

## API Endpoints Reference

### Public Board Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/public/tournaments` | List all tournaments |
| `GET` | `/api/public/tournaments/{id}/schedule` | Get schedule for a tournament |
| `GET` | `/api/public/tournaments/{id}/rankings` | Get rankings for a tournament |
| `GET` | `/api/public/player/{name}/path` | Get player path for a tournament |

### Operator Console Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/operator/tournaments/{id}/queue` | Get match queue for a tournament |
| `GET` | `/api/operator/tournaments/{id}/tables` | Get table status for a tournament |
| `GET` | `/api/operator/tournaments/{id}/tables/available` | Get next available table |
| `POST` | `/api/operator/matches/{id}/call` | Call a match |
| `POST` | `/api/operator/matches/{id}/start` | Start a match |
| `POST` | `/api/operator/matches/{id}/complete` | Complete a match |
| `POST` | `/api/operator/matches/{id}/delay` | Delay a match |
| `POST` | `/api/operator/matches/{id}/reschedule` | Reschedule a match |
| `POST` | `/api/operator/matches/{id}/reset-call` | Reset match call status |
| `GET` | `/api/operator/audit` | Get audit log entries |
| `POST` | `/api/operator/commands/parse` | Parse operator command text |
| `POST` | `/api/operator/commands/apply` | Apply operator command |

### Match & Rating Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/match/parse` | Parse match result from text (read-only) |
| `POST` | `/api/report` | Submit a confirmed match result |
| `GET` | `/api/ratings/leaderboard` | Get current ratings leaderboard |
| `GET` | `/api/ratings/player/{id}/history` | Get rating history for a player |
| `POST` | `/api/ratings/preview-match` | Preview rating impact for a match |
| `POST` | `/api/rules/ask` | Ask a question about tournament rules |

### Announcement Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/announcements` | Create a new announcement |
| `POST` | `/api/announcements/{id}/send` | Send an announcement via webhook |
| `GET` | `/api/announcements` | Get recent announcements (optional filters: limit, channel, sent_status) |

## Known Limitations

1. **SQLite Concurrency**: SQLite has limited concurrent write support. For production, consider PostgreSQL.

2. **Vosk Model Size**: The Vosk model must be downloaded separately. Small models are less accurate than larger ones.

3. **Match State Transitions**: The system enforces a basic state machine:
   - `not_called` → `called` → `active` → `completed`
   - Any state → `delayed`
   - Any state → `queued` (via reschedule)

4. **No Automatic Scheduling**: Matches must be created manually or via tournament setup. The system doesn't auto-generate schedules.

5. **Single Tournament Focus**: The Public Board and Operator Console work best with one active tournament at a time.

6. **Voice Commands Limited**: Voice shortcuts are only available in the Operator Console, not throughout the app.

7. **No Real-time Updates**: The UI refreshes on button click or every 15-30 seconds. No WebSocket support yet.

8. **Rating Updates**: Ratings are updated when match results are submitted via the API. Manual match updates may not trigger rating changes.

## Feature Flags

Feature flags are defined in [`tournament_platform/services/settings.py`](tournament_platform/services/settings.py) and can be overridden via environment variables or a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_VOICE_ENTRY` | `True` | Enable voice-based match entry |
| `ENABLE_RULES_ASSISTANT` | `True` | Enable the AI rules assistant (RAG) |
| `ENABLE_RANKING_INTELLIGENCE` | `True` | Enable ranking intelligence features |
| `ENABLE_SPOKEN_CONFIRMATION` | `False` | Enable spoken confirmation prompts |
| `KEEP_AUDIO_FILES` | `False` | Keep temporary audio files after transcription |
| `SPEECH_MODEL_SIZE` | `base` | Whisper model size for speech-to-text |
