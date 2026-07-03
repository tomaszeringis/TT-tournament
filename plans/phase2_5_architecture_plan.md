# Phase 2-5 Architecture Plan: Tournament Platform Evolution

## 1. Current-State Findings

### What Already Exists
- **Models**: `Player`, `Tournament`, `Match`, `VenueTable`, `RatingHistory`, `Announcement`, `AuditLog`
- **Tournament Types**: `knockout` (single elimination) and `round_robin` via `TournamentStrategy` pattern
- **Match State**: `MatchStatus` enum (pending, active, completed) + `call_status` string field
- **Operator Workflow**: Call, start, complete, delay, reschedule, reset-call actions with audit logging
- **Public Board**: Read-only display with current/called/upcoming/delayed matches, standings, player lookup
- **Kiosk Mode**: Query parameter support (`?kiosk=1`) and sidebar toggle
- **Bracket Rendering**: Uses `bracketool` library for knockout, `round_robin_tournament` for round-robin
- **Player FKs**: `player1_id`, `player2_id`, `winner_id` on Match (nullable for backward compatibility)

### What Is Missing
- **Event Model**: No explicit event abstraction (Tournament is used directly)
- **Entry Model**: No separate entry/registration model (players are directly assigned)
- **Stage/Phase Model**: No multi-phase tournament support (groups → knockout)
- **Group Model**: No group abstraction for group-stage tournaments
- **Seed Model**: No explicit seeding; players are assigned by name order
- **Standing Model**: Standings computed on-the-fly, not stored
- **Advancement Rule**: No configurable advancement rules
- **Swiss System**: Not implemented
- **Doubles Support**: No team/pair model
- **Scorer Tokens**: No tokenized per-match or per-table access
- **Schedule Optimizer**: No automated scheduling
- **Live Updates**: No SSE/WebSocket support (only polling)

### What Is Risky
- **Stringly-Typed State**: `player1`, `player2`, `winner` stored as strings; FKs are nullable
- **No Migration Path**: Legacy string fields may cause data inconsistency
- **Single Tournament Focus**: Public Board and Operator Console work best with one active tournament
- **SQLite Concurrency**: Limited concurrent write support
- **No Real-time Updates**: UI refreshes on button click or every 15-30 seconds

## 2. Recommended Phase Order

The proposed order (Phase 2 → 3 → 4 → 5) is appropriate. However, I recommend adjusting:

1. **Phase 2**: Core tournament engine (models, groups → knockout)
2. **Phase 3**: Operations excellence (scorer tokens, public portal, live updates)
3. **Phase 4**: Tournament depth (Swiss, doubles)
4. **Phase 5**: Platform and intelligence (package boundaries, AI assistance)

**Rationale**: Model/service foundations must be in place before UI and scorer features.

## 3. File-by-File Change Map

### Models (`tournament_platform/models.py`)
| New Model | Purpose |
|-----------|---------|
| `Event` | Top-level tournament event (contains multiple stages) |
| `Entry` | Player registration for an event (supports doubles) |
| `Stage` | A phase within an event (group, knockout, swiss) |
| `Group` | Group within a stage |
| `Seed` | Explicit seeding position |
| `Standing` | Computed standings (optional, for performance) |
| `ScorerToken` | Token for scorer/referee access |

### Migrations (`tournament_platform/alembic/versions/`)
| Migration | Changes |
|-----------|---------|
| `009_add_event_models.py` | Add Event, Entry, Stage, Group, Seed, ScorerToken tables |
| `010_add_standings.py` | Add Standing table (optional) |

### Services
| File | New Functions |
|------|---------------|
| `tournament_engine.py` | `GroupsKnockoutStrategy`, `SwissStrategy` |
| `tournament_read_models.py` | `get_event_standings()`, `get_group_matches()` |
| `tie_breaker.py` (new) | `compute_tie_breakers()`, `explain_ranking()` |
| `advancement.py` (new) | `advance_qualifiers()`, `validate_phase_completion()` |
| `scheduler.py` (new) | `generate_schedule()`, `detect_conflicts()` |
| `scorer_token.py` (new) | `create_token()`, `validate_token()`, `revoke_token()` |

### API (`tournament_platform/api/server.py`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/events` | GET/POST | Event CRUD |
| `/api/events/{id}/entries` | GET/POST | Entry management |
| `/api/events/{id}/stages` | GET | Stage listing |
| `/api/stages/{id}/groups` | GET | Group listing |
| `/api/groups/{id}/standings` | GET | Group standings |
| `/api/scorer/{token}` | GET | Scorer view (token-scoped) |
| `/api/schedule/propose` | POST | Schedule proposal |

### Streamlit Pages
| File | Changes |
|------|---------|
| `events_draws.py` | Multi-phase event setup, group configuration |
| `public_board.py` | Event selector, stage navigation |
| `operator_console.py` | Phase progression controls, scorer link generation |
| `scorer.py` (new) | Mobile scorer interface |

### Tests
| File | Tests |
|------|-------|
| `test_tournament_engine.py` | Groups knockout, Swiss, tie-breakers |
| `test_tie_breaker.py` | Tie-breaker logic |
| `test_advancement.py` | Qualifier advancement |
| `test_scheduler.py` | Schedule generation, conflict detection |
| `test_scorer_token.py` | Token validation, access control |

## 4. Data Model Proposal

### New Tables

```sql
-- Event: Top-level tournament event
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    name VARCHAR UNIQUE,
    description TEXT,
    format_type VARCHAR, -- 'groups_knockout', 'swiss', 'round_robin', 'knockout'
    num_groups INTEGER,
    qualifiers_per_group INTEGER,
    created_at TIMESTAMP
);

-- Entry: Player registration (supports doubles)
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    event_id INTEGER REFERENCES events(id),
    player1_id INTEGER REFERENCES players(id),
    player2_id INTEGER REFERENCES players(id), -- NULL for singles
    seed_position INTEGER,
    club VARCHAR,
    division VARCHAR
);

-- Stage: A phase within an event
CREATE TABLE stages (
    id INTEGER PRIMARY KEY,
    event_id INTEGER REFERENCES events(id),
    stage_type VARCHAR, -- 'group', 'knockout', 'swiss'
    name VARCHAR,
    order_index INTEGER
);

-- Group: Group within a stage
CREATE TABLE groups (
    id INTEGER PRIMARY KEY,
    stage_id INTEGER REFERENCES stages(id),
    name VARCHAR,
    order_index INTEGER
);

-- ScorerToken: Token for scorer/referee access
CREATE TABLE scorer_tokens (
    id INTEGER PRIMARY KEY,
    token VARCHAR UNIQUE,
    match_id INTEGER REFERENCES matches(id),
    table_id INTEGER REFERENCES venue_tables(id),
    expires_at TIMESTAMP,
    revoked BOOLEAN,
    created_at TIMESTAMP
);
```

### Backward Compatibility
- Keep existing `Tournament` and `Match` tables
- Add `event_id` FK to `Tournament` (nullable)
- Add `stage_id` FK to `Match` (nullable)
- Legacy tournaments render as single-stage events

### Legacy Cleanup Plan
- Phase 2: Add new models, keep legacy fields
- Phase 3: Add migration path for legacy data
- Phase 4: Deprecate legacy string fields
- Phase 5: Remove legacy fields (optional)

## 5. Service Design

### Tournament Engine
```
TournamentStrategy (ABC)
├── KnockoutStrategy (exists)
├── RoundRobinStrategy (exists)
├── GroupsKnockoutStrategy (new)
│   ├── generate_group_matches()
│   ├── compute_group_standings()
│   └── advance_qualifiers()
└── SwissStrategy (Phase 4)
    ├── generate_round_pairings()
    ├── avoid_repeat_pairings()
    └── handle_byes()
```

### Standings/Tie-Breaker Engine
```python
def compute_tie_breakers(players: List[PlayerStanding]) -> List[PlayerStanding]:
    """Apply tie-breakers in order: wins, h2h, point diff, rating, manual override."""

def explain_ranking(standing: PlayerStanding) -> str:
    """Return human-readable explanation of ranking position."""
```

### Advancement Engine
```python
def advance_qualifiers(event: Event, db: Session) -> List[Entry]:
    """Compute qualifiers from group stage and create knockout entries."""

def validate_phase_completion(stage: Stage, db: Session) -> ValidationResult:
    """Check if all required matches are complete before progression."""
```

### Scheduler
```python
def generate_schedule(matches: List[Match], tables: List[VenueTable], 
                      start_time: datetime, duration: int) -> ScheduleProposal:
    """Propose a schedule with table assignments and detect conflicts."""

def detect_conflicts(schedule: ScheduleProposal) -> List[Conflict]:
    """Find player double-booking, table conflicts, insufficient rest."""
```

### Scorer Token Service
```python
def create_token(match_id: int, expires_in: int) -> ScorerToken:
    """Create a time-limited token for scorer access."""

def validate_token(token: str) -> TokenValidation:
    """Validate token and return permitted actions."""
```

## 6. UI Flow Proposal

### Organizer Setup
1. Create Event (name, format, group config)
2. Register Entries (players, optional seeding)
3. Configure Stages (auto-generated for groups → knockout)
4. Review and Generate

### Groups → Knockout Setup
1. Select number of groups (2, 4, 6, 8)
2. Set qualifiers per group (1, 2, 3)
3. Auto-assign players to groups (or manual)
4. Generate group matches
5. After group completion, review qualifiers
6. Generate knockout bracket

### Phase Progression
1. Check group stage completion
2. Show qualifier preview
3. Organizer confirms or overrides
4. Generate knockout phase
5. Log progression in audit trail

### Public Board
1. Event selector dropdown
2. Stage navigation tabs
3. Group standings view
4. Knockout bracket view
5. Kiosk mode toggle

### Mobile Scorer
1. Token entry (or deep link)
2. View assigned match
3. Submit score
4. Update match status
5. Confirmation and audit log

## 7. Test Plan

### Unit Tests (Pure Services)
- `test_groups_knockout.py`: Group creation, match generation, standings, advancement
- `test_tie_breaker.py`: Two-way ties, three-way ties, incomplete data, manual override
- `test_scheduler.py`: Conflict detection, schedule generation
- `test_swiss.py`: Pairings, repeat avoidance, byes (Phase 4)

### Integration Tests (API)
- Event CRUD endpoints
- Scorer token validation
- Schedule proposal endpoint

### Streamlit Helper Tests
- Extract pure functions for testing
- Test bracket rendering with various sizes
- Test kiosk mode detection

### Migration Tests
- Verify legacy data still renders
- Test forward migration path

### Regression Tests
- Single elimination still works
- Round robin still works
- Public board still works

## 8. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Migration risk | Keep legacy fields, add compatibility layer, test thoroughly |
| Streamlit public/no-login | Use query parameters, no write endpoints, token-scoped access |
| String player fields | Add FKs, migrate data, keep string fields for compatibility |
| Backward compatibility | Dual-write during transition, deprecation warnings |
| Scheduling complexity | Start with deterministic greedy algorithm, document limitations |
| Swiss pairing complexity | Use existing library, add tests for edge cases |
| Auth/token safety | Cryptographically secure tokens, expiration, revocation |

## 9. Implementation Slices

### Phase 2 Slice 1: Event/Stage Models
- Add `Event`, `Stage`, `Group` models
- Add Alembic migration
- Update `Tournament` to link to `Event`
- Add backward compatibility layer

### Phase 2 Slice 2: Groups → Knockout Strategy
- Implement `GroupsKnockoutStrategy`
- Add group match generation
- Add group standings computation
- Add advancement logic

### Phase 2 Slice 3: Tie-Breaker Engine
- Implement tie-breaker service
- Add head-to-head, point differential, rating fallback
- Add manual override support
- Add explanation UI

### Phase 2 Slice 4: UI Integration
- Update Events & Draws for multi-phase
- Add group configuration UI
- Add phase progression controls
- Update public board for stages

### Phase 3 Slice 1: Scorer Tokens
- Add `ScorerToken` model
- Implement token service
- Add scorer page
- Add API endpoints

### Phase 3 Slice 2: Public Portal
- Add read-only public routes
- Add shareable URLs
- Add QR support
- Keep admin pages protected

### Phase 3 Slice 3: Live Updates
- Add SSE endpoint for match updates
- Add polling fallback for Streamlit
- Update public board and operator console

### Phase 3 Slice 4: Schedule Optimizer
- Implement scheduler service
- Add conflict detection
- Add UI for schedule proposal
- Add tests

### Phase 4 Slice 1: Swiss System
- Implement `SwissStrategy`
- Add pairing logic
- Add repeat avoidance
- Add tests

### Phase 4 Slice 2: Doubles Support
- Add `Entry` model with pair support
- Update match generation
- Add UI for pair registration
- Add tests

### Phase 5 Slice 1: Package Boundaries
- Separate `tournament_core` package
- Move AI to `tournament_ai` package
- Add compatibility shims

### Phase 5 Slice 2: AI Assistance
- Add seeding suggestions
- Add schedule suggestions
- Add anomaly detection
- Add tests

## 10. Stop Point

This architecture plan is ready for review. **Do not implement until approved.**

Key questions for approval:
1. Should we add `Standing` as a persisted table or keep computed?
2. Should `Event` replace `Tournament` or coexist?
3. Any concerns about the scorer token security model?
4. Should we prioritize Swiss or Doubles for Phase 4?