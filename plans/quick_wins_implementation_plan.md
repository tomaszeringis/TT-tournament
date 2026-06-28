# Quick Wins Implementation Plan

## Overview
This plan addresses the four quick wins for the tournament-management app:
1. Public schedule and ranking board
2. Operator match-call and rescheduling workflow
3. Player path view
4. Deterministic voice/text shortcuts for operator actions

---

## Step 1: Public Schedule and Ranking Board

### Files to Create/Modify
| File | Action |
|------|--------|
| `tournament_platform/services/tournament_read_models.py` | Create (7 read-model functions) |
| `tournament_platform/app/pages/public_board.py` | Create (Streamlit page) |
| `tournament_platform/api/server.py` | Add public endpoints |

### Database Changes Required
No new tables required. Uses existing `Match`, `Player`, `Tournament` models.

### API Endpoints to Add
| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/public/tournaments` | GET | List all tournaments |
| `GET /api/public/tournaments/{tournament_id}/schedule` | GET | Get public schedule for tournament |
| `GET /api/public/tournaments/{tournament_id}/rankings` | GET | Get public rankings for tournament |
| `GET /api/public/player/{player_name}/path` | GET | Get player path (shared with operator) |

### Read-Model Functions (tournament_read_models.py)
1. `list_tournaments(db)` - Return all tournaments with basic info
2. `get_public_schedule(db, tournament_id)` - Return matches sorted by status/time
3. `get_public_rankings(db, tournament_id)` - Return players sorted by rating with stats
4. `get_player_path(db, player_name, tournament_id)` - Return player's tournament path

### Streamlit Page (public_board.py)
- Tournament selector dropdown
- "Now Playing" section (active/called matches)
- "Coming Up" section (next 3 pending matches)
- "Delayed" section (delayed matches)
- "Rankings" table with wins/losses
- "Recent Results" section
- "Player Lookup" for path view
- Auto-refresh every 15 seconds

### Tests to Add
| File | Tests |
|------|-------|
| `tournament_platform/test_tournament_read_models.py` | 19 tests for read-model functions |

### Verification Commands
```bash
cd tournament_platform && python -m pytest test_tournament_read_models.py -v
```

---

## Step 2: Operator Match-Call and Rescheduling Workflow

### Files to Create/Modify
| File | Action |
|------|--------|
| `tournament_platform/models.py` | Add VenueTable, Announcement, AuditLog models + Match operator fields |
| `tournament_platform/alembic/versions/007_add_operator_workflow.py` | Create migration |
| `tournament_platform/services/audit_service.py` | Create audit logging service |
| `tournament_platform/api/server.py` | Add operator endpoints |
| `tournament_platform/app/pages/operator_console.py` | Create Streamlit page |

### Database Changes Required
**New Tables:**
- `venue_tables` - Physical tables at venue (id, name, is_active, notes, created_at, updated_at)
- `announcements` - Match/tournament announcements (id, match_id, tournament_id, message, channel, sent_status, error, created_at)
- `audit_log` - Operator action audit trail (id, actor, action, entity_type, entity_id, payload_json, created_at)

**Match Model Extensions:**
- `call_status` - String: "not_called", "queued", "called", "active", "delayed", "completed", "cancelled"
- `called_at` - DateTime (nullable)
- `started_at` - DateTime (nullable)
- `completed_at` - DateTime (nullable)
- `delayed_until` - DateTime (nullable)
- `operator_note` - String (nullable)
- `updated_at` - DateTime (nullable)

### API Endpoints to Add
| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/operator/tournaments/{tournament_id}/queue` | GET | Get operator queue with conflict flags |
| `GET /api/operator/tournaments/{tournament_id}/tables` | GET | Get table status |
| `GET /api/operator/tournaments/{tournament_id}/tables/available` | GET | Get next available table |
| `POST /api/operator/matches/{match_id}/call` | POST | Call a match to a table |
| `POST /api/operator/matches/{match_id}/start` | POST | Start a called match |
| `POST /api/operator/matches/{match_id}/complete` | POST | Complete an active match |
| `POST /api/operator/matches/{match_id}/delay` | POST | Delay a match |
| `POST /api/operator/matches/{match_id}/reschedule` | POST | Reschedule a match |
| `POST /api/operator/matches/{match_id}/reset-call` | POST | Reset call status to queued |
| `GET /api/operator/audit` | GET | Get audit log entries |

### Read-Model Functions (tournament_read_models.py)
5. `get_operator_queue(db, tournament_id)` - Return matches with conflict flags
6. `get_table_status(db, tournament_id)` - Return table availability
7. `get_next_available_table(db, tournament_id)` - Return next free/busy table

### Streamlit Page (operator_console.py)
- Tournament selector
- Table status overview (current/next match per table)
- Next available table indicator
- Match queue with conflict detection
- Action buttons: Call, Start, Complete, Delay, Reschedule, Reset
- Player path lookup
- Audit log viewer

### Tests to Add
| File | Tests |
|------|-------|
| `tournament_platform/test_operator_models.py` | 14 tests for models and audit service |
| `tournament_platform/test_api_endpoints.py` | 15 tests for API endpoints |

### Verification Commands
```bash
cd tournament_platform && python -m pytest test_operator_models.py test_api_endpoints.py -v
```

---

## Step 3: Player Path View

### Files to Create/Modify
| File | Action |
|------|--------|
| `tournament_platform/services/tournament_read_models.py` | Add `get_player_path()` function |
| `tournament_platform/app/pages/public_board.py` | Add player lookup section |
| `tournament_platform/app/pages/operator_console.py` | Add player path section |
| `tournament_platform/api/server.py` | Add endpoint (shared with public) |

### API Endpoint
| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/public/player/{player_name}/path` | GET | Get player's tournament path |

### Read-Model Function
`get_player_path(db, player_name, tournament_id)` - Returns:
- `completed_matches` - List of completed matches
- `next_pending_match` - Next match to play
- `projected_path` - Future matches based on bracket

### Tests
Already covered in `test_tournament_read_models.py` (TestGetPlayerPath class)

---

## Step 4: Text Command Router + Vosk Voice Adapter

### Files to Create/Modify
| File | Action |
|------|--------|
| `tournament_platform/services/command_router.py` | Create text command parser |
| `tournament_platform/services/vosk_adapter.py` | Create voice adapter |
| `tournament_platform/api/server.py` | Add command endpoint |
| `tournament_platform/api/schemas.py` | Add command schemas |

### Text Command Patterns
| Command | Pattern |
|---------|---------|
| Call match | `call <player1> vs <player2>` or `call match <id>` |
| Call to table | `call <player1> vs <player2> to table <n>` |
| Start match | `start <player1> vs <player2>` or `start match <id>` |
| Complete match | `complete <player1> vs <player2>` or `complete match <id>` |
| Delay match | `delay <player1> vs <player2> for <n> minutes` |
| Reschedule | `reschedule <player1> vs <player2> to table <n> at <time>` |
| Player path | `path <player_name>` |
| Table status | `tables` or `table status` |

### API Endpoint
| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/operator/command` | POST | Process text command |

### Tests
| File | Tests |
|------|-------|
| `tournament_platform/test_command_router.py` | 9 tests for command parsing |

### Verification Commands
```bash
cd tournament_platform && python -m pytest test_command_router.py -v
```

---

## Summary of All Changes

### New Files
| File | Purpose |
|------|---------|
| `tournament_platform/services/tournament_read_models.py` | Read-model helper functions |
| `tournament_platform/services/audit_service.py` | Audit logging service |
| `tournament_platform/services/command_router.py` | Text command parser |
| `tournament_platform/services/vosk_adapter.py` | Voice adapter (optional) |
| `tournament_platform/api/schemas.py` | Pydantic schemas |
| `tournament_platform/app/pages/public_board.py` | Public board page |
| `tournament_platform/app/pages/operator_console.py` | Operator console page |
| `tournament_platform/test_tournament_read_models.py` | Read-model tests |
| `tournament_platform/test_operator_models.py` | Model tests |
| `tournament_platform/test_command_router.py` | Command router tests |
| `tournament_platform/test_api_endpoints.py` | API endpoint tests |
| `tournament_platform/alembic/versions/007_add_operator_workflow.py` | Database migration |

### Modified Files
| File | Changes |
|------|---------|
| `tournament_platform/models.py` | Add VenueTable, Announcement, AuditLog models; extend Match |
| `tournament_platform/api/server.py` | Add all new endpoints |
| `tournament_platform/app/main.py` | Add navigation entries for new pages |

---

## Risks

### Migration Risks
- **Risk:** Existing endpoints are already in use; renaming will break backward compatibility
- **Mitigation:** Keep old endpoints as deprecated aliases for one release cycle (not implemented in this phase)

### SQLite Compatibility Issues
- **Risk:** SQLite has limited ALTER TABLE support
- **Mitigation:** Using `batch_alter_table` in Alembic migration for safe column additions

### Existing Code Formatting Problems
- **Risk:** `tournament_platform/api/server.py` line 393 has duplicate `MatchStatus.active` check
- **Mitigation:** Fix during endpoint updates (already fixed in implementation)

### Missing Dependencies
- **Risk:** `vosk` is optional; code must handle missing dependency gracefully
- **Mitigation:** `vosk_adapter.py` already handles missing import with `is_vosk_available()` check

### Endpoint Naming Conflicts
- **Risk:** No conflicts with existing endpoints; all new paths are unique
- **Status:** Verified - no conflicts

---

## Verification Commands

```bash
# Run all quick wins tests
cd tournament_platform && python -m pytest test_operator_models.py test_tournament_read_models.py test_command_router.py test_api_endpoints.py -v

# Run full test suite
cd tournament_platform && python -m pytest -v

# Run specific test file
cd tournament_platform && python -m pytest test_tournament_read_models.py -v
```

---

## Implementation Status
All components have been implemented and tested. See the todo list for completion status.