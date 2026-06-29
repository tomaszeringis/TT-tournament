# Workflow Mapping

This document maps the old workflows to the new navigation structure.

## Navigation Structure

| Page | Icon | Purpose |
|------|------|---------|
| Dashboard | 📊 | Overview of all tournaments |
| Participants | 👥 | Player registration and management |
| Events & Draws | 🏆 | Tournament creation and bracket setup |
| Rankings | 🏆 | Player rankings and statistics |
| Public Board | 📺 | Read-only display for TV/projector |
| Operator Console | 🎛️ | Match flow control and table management |
| Tournament Setup (Legacy) | ⚙️ | Compatibility redirect to new pages |
| AI Assistant | 🤖 | Rules Q&A and tournament questions |
| Voice Scorekeeper | 🔊 | Voice-activated scorekeeping with game-by-game workflow |
| Admin | 👨‍💼 | Admin-only maintenance and diagnostics |

## Workflow Mappings

### Old Tournament Setup → New Pages
- **Player Management** → [`Participants`](tournament_platform/app/pages/participants.py)
- **Tournament Creation** → [`Events & Draws`](tournament_platform/app/pages/events_draws.py)
- **Match Scoring** → [`Voice Scorekeeper`](tournament_platform/app/pages/voice_scorekeeper.py)

The old `tournament_setup.py` now shows a compatibility message directing users to the new pages.

### Voice Scorekeeper (Primary Scoring Page)
- **Status**: Active and maintained - now the primary match scoring interface
- **Purpose**: Voice-activated scorekeeping with game-by-game workflow
- **Features**:
  - Audio input for voice commands
  - Player selection via dropdowns
  - Live score display with +/- buttons
  - **Game-by-game scoring**: Enter each game score as completed, system tracks games and determines match winner
  - Match result reporting via `/api/report` endpoint
- **Note**: Live Scoring page now redirects to Voice Scorekeeper

### Live Scoring (Compatibility Wrapper)
- **Status**: Deprecated - redirects to Voice Scorekeeper
- **Purpose**: Previously manual match score entry; now redirects to Voice Scorekeeper
- **Note**: The file is preserved but users are automatically redirected to Voice Scorekeeper for all scoring needs

### Voice Rules Chat
- **Status**: Not in navigation (deprecated)
- **Purpose**: Voice-activated rules Q&A
- **Note**: Functionality is now available in the AI Assistant's Rules Q&A tab. The file is preserved but not linked.

### Operator Console
- **Status**: Active and maintained
- **Purpose**: Tournament operator control panel
- **Features**:
  - Match call queue
  - Table status overview
  - Rescheduling interface
  - Voice shortcut for commands
  - Audit log viewer
- **Note**: Uses centralized `ApiClient` for API calls

### AI Assistant
- **Status**: Active and maintained
- **Purpose**: Rules Q&A and tournament questions
- **Features**:
  - Tournament Assistant tab (general questions)
  - Rules Q&A tab (uses `/api/rules/ask` endpoint)
  - AI status display
- **Note**: Read-only; does not mutate tournament data

### Public Board
- **Status**: Active and maintained
- **Purpose**: Read-only display for TV/projector viewing
- **Features**:
  - Now Playing (current/called matches)
  - Coming Up (next matches)
  - Delayed matches
  - Rankings/standings
  - Recent results
  - Player lookup
  - Announcements
- **Note**: No admin actions; read-only access

## API Endpoints Used

| Page | Endpoint | Method | Purpose |
|-------|----------|--------|---------|
| Live Scoring | `/api/report` | POST | Submit match results |
| Live Scoring | `/api/tournaments/{id}/matches/active` | GET | Fetch active matches |
| AI Assistant | `/api/rules/ask` | POST | Ask rules questions |
| Operator Console | `/api/operator/matches/{id}/call` | POST | Call match |
| Operator Console | `/api/operator/matches/{id}/start` | POST | Start match |
| Operator Console | `/api/operator/matches/{id}/complete` | POST | Complete match |
| Operator Console | `/api/operator/matches/{id}/delay` | POST | Delay match |
| Operator Console | `/api/operator/matches/{id}/reschedule` | PATCH | Reschedule match |
| Operator Console | `/api/operator/matches/{id}/reset-call` | POST | Reset call status |

## Testing

All pages have associated tests:
- [`tests/test_live_scoring.py`](tests/test_live_scoring.py) - Score validation and match label formatting
- [`tests/test_api_client.py`](tests/test_api_client.py) - API client methods
- [`tests/test_regression.py`](tests/test_regression.py) - API contract tests including `/api/report` and `/api/rules/ask`