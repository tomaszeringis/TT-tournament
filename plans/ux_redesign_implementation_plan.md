# Table Tennis Tournament Platform — UX Redesign & Modernization Implementation Plan

**Repository:** https://github.com/tomaszeringis/TT-tournament/tree/ux-redesign-safe-pages
**Branch:** `ux-redesign-safe-pages`
**Date:** 2026-07-07
**Author:** Senior Software Architect / UX Designer

---

## Executive Summary

This document provides a comprehensive analysis of the current Tournament Platform and a prioritized implementation plan to align it with modern table tennis tournament management best practices. The platform already has a solid foundation with tournament creation, bracket generation, operator workflows, and AI-powered features. However, there are significant gaps in doubles/mixed doubles support, seeding workflows, player registration UX, mobile usability, and overall information architecture.

The plan is organized into six phases, prioritizing quick wins and incremental improvements over major rewrites. Each phase includes clear objectives, user value, affected modules, dependencies, and estimated effort.

---

## Current State Assessment

### Architecture Overview

| Layer | Technology | Status |
|-------|-----------|--------|
| Frontend | Streamlit 1.35+ with `st.navigation` | Functional but monolithic |
| Backend | FastAPI + Uvicorn | Well-structured, async |
| Database | SQLAlchemy ORM + Alembic + SQLite | Mature, 9 migrations |
| AI | Ollama + ChromaDB (RAG) | Experimental but functional |
| Auth | Streamlit Authenticator | Basic role-based |

### Data Model (Verified from `models.py`)

**Core Entities:**
- `Player` — name, email, rating (default 1200)
- `Tournament` — name, description, type (knockout/round-robin), created_at
- `Match` — player1, player2, winner, score, status, tournament_id, round_number, bracket_index, next_match_id, stage_id, call_status, scheduled_time, location, operator fields
- `Event` — name, description, event_type, num_groups, qualifiers_per_group
- `Stage` — event_id, stage_type (group/knockout/swiss), name, order_index
- `Group` — stage_id, name, order_index
- `Entry` — event_id, group_id, player1_id, player2_id (nullable for doubles), seed_position, club, division
- `VenueTable` — name, is_active, notes
- `Announcement` — match_id, tournament_id, message, channel, sent_status
- `AuditLog` — actor, action, entity_type, entity_id, payload_json

**Multimodal AI Models:**
- `Dataset`, `DatasetArtifact`, `DataSample`, `Annotation`
- `MultimodalSession`, `SensorStream`, `VideoSegment`, `AudioSegment`
- `BallTrajectory`, `StrokeEvent`, `CoachingFeedback`
- `ModelExperiment`, `EvaluationRun`

### Current Pages (Verified from `main.py` and `app/pages/`)

| Page | Path | Status |
|------|------|--------|
| Home | `pages/home.py` | ✅ Exists — getting started, setup checklist, recent tournaments |
| Events & Draws | `pages/events_draws.py` | ✅ Exists — tournament creation wizard, bracket, standings |
| Participants | `pages/participants.py` | ⚠️ Redirect wrapper only |
| Dashboard | `pages/dashboard.py` | ✅ Exists — metrics, rankings, recent matches |
| Rankings | `pages/rankings.py` | ⚠️ Redirect wrapper to Dashboard |
| Public Board | `pages/public_board.py` | ✅ Exists — TV/projector display |
| Operator Console | `pages/operator_console.py` | ✅ Exists — match center, table status, audit log |
| Player Profile | `pages/player_profile.py` | ✅ Exists — rating trend, match history |
| Schedule Board | `pages/schedule_board.py` | ✅ Exists — calendar view |
| AI Assistant | `pages/ai_assistant.py` | ✅ Exists — experimental |
| Voice Scorekeeper | `pages/voice_scorekeeper.py` | ✅ Exists — experimental |
| Video Scorekeeper | `pages/video_scorekeeper.py` | ⚠️ Experimental, `.new` file exists |
| Admin | `pages/admin.py` | ✅ Exists — admin-only |
| Coaching Lab | `pages/coaching_lab.py` | ⚠️ Experimental |
| Dataset Catalog | `pages/dataset_catalog.py` | ⚠️ Experimental |
| Experiment Dashboard | `pages/experiment_dashboard.py` | ⚠️ Experimental |

### Current Navigation Structure

```
Home (🏠)
Tournament (🏆) — Events & Draws (consolidated)
Insights (📊) — Dashboard + AI Assistant
Admin (👨‍💼) — admin-only
Experimental (🧪) — behind DEBUG_UI_ENABLED
```

### Existing Features (Verified)

**Tournament Management:**
- ✅ Tournament creation wizard (4 steps: basics, format, participants, review)
- ✅ Format selection: Single Elimination, Round Robin, Groups → Knockout, Swiss
- ✅ Seeding options: random, rating-based, manual (UI only, not fully implemented)
- ✅ Bracket generation using `bracketool` and `round_robin_tournament` libraries
- ✅ Interactive bracket visualization
- ✅ Round-robin standings calculation
- ✅ Group standings for Groups → Knockout
- ✅ Swiss system pairing (basic implementation)

**Match Management:**
- ✅ Match call queue with conflict detection
- ✅ Table status overview
- ✅ Match states: not_called → called → active → completed
- ✅ Delay, reschedule, reset functionality
- ✅ Score entry with validation
- ✅ Match result reporting via API
- ✅ Rating updates after matches

**Operator Workflow:**
- ✅ Operator console with quick actions
- ✅ Text command bar ("call match 12 to table 3")
- ✅ Voice shortcuts (optional Vosk integration)
- ✅ Audit logging
- ✅ Announcements (Teams webhook)
- ✅ Duplicate player detection and merge
- ✅ Player path visualization
- ✅ Health dashboard (active matches, table utilization, issues)

**Public Display:**
- ✅ Public board (TV/projector mode)
- ✅ Kiosk mode with auto-refresh
- ✅ Current/next/coming up/delayed/recent matches
- ✅ Rankings display
- ✅ Player lookup

**AI Features:**
- ✅ Match result parsing (natural language → structured JSON)
- ✅ Rules Q&A (RAG-based)
- ✅ AI tournament suggestions
- ✅ Rating preview (upset potential)
- ✅ Voice scorekeeper (experimental)
- ✅ Video scorekeeper (experimental)

### Technical Constraints

1. **Streamlit Limitations**: Single-page app model, limited custom UI, rerun-based reactivity
2. **SQLite**: Default database, not ideal for concurrent write operations
3. **No Real-time**: WebSocket/push notifications not implemented
4. **Experimental Features**: AI/ML features mixed with core tournament logic
5. **Code Organization**: Some pages are very large (events_draws.py: 31K, operator_console.py: 32K, voice_scorekeeper.py: 55K)

---

## Research Findings

### Modern Table Tennis Tournament Management Best Practices

Based on research of Tournify, Tournament Software, Omnipong, TT Manager, USATT, and ITTF systems:

#### 1. Tournament Creation Workflow
- **Best Practice**: Multi-step wizard with clear progress indication
- **Current State**: ✅ Implemented (4-step wizard)
- **Gap**: Missing event-level metadata (date, venue, description not persisted to Event model), no draft/ published states

#### 2. Player Registration
- **Best Practice**: Bulk import (CSV/Excel), check-in system, club/division assignment, duplicate detection at entry point
- **Current State**: ⚠️ Basic multiselect from existing players, duplicate detection exists but is manual
- **Gap**: No bulk import, no check-in workflow, no club/division filtering

#### 3. Event Management
- **Best Practice**: Multiple events per tournament (singles, doubles, mixed doubles, team), event-level configuration
- **Current State**: ⚠️ Event model exists but UI doesn't leverage it fully
- **Gap**: No doubles/mixed doubles support in UI, no team events

#### 4. Seeding
- **Best Practice**: Rating-based seeding with manual override, seed visualization in bracket
- **Current State**: ⚠️ UI has seeding options but not implemented in bracket generation
- **Gap**: Seeding not applied to bracket, no seed numbers displayed

#### 5. Draws/Brackets
- **Best Practice**: Interactive brackets with click-to-update, automatic advancement, consolation brackets
- **Current State**: ✅ Interactive bracket exists, automatic advancement for knockout
- **Gap**: No consolation/plate brackets, no double elimination

#### 6. Round Robin Groups
- **Best Practice**: Automatic group standings with tie-breakers (head-to-head, point differential)
- **Current State**: ⚠️ Basic standings (wins, points for/against)
- **Gap**: No head-to-head tie-breaker, no point differential tie-breaker

#### 7. Knockout Brackets
- **Best Practice**: Seed placement, bye handling, third-place match, final placement matches
- **Current State**: ✅ Basic knockout with bye handling
- **Gap**: No third-place match, no placement matches, no seed visualization

#### 8. Match Scheduling
- **Best Practice**: Auto-scheduling with table constraints, time slots, rest periods
- **Current State**: ⚠️ Basic scheduling (scheduled_time field), no auto-scheduler
- **Gap**: No intelligent scheduling, no rest period enforcement

#### 9. Table Assignment
- **Best Practice**: Automatic table assignment, table rotation, conflict detection
- **Current State**: ✅ Basic table status, conflict detection
- **Gap**: No automatic assignment, no table rotation

#### 10. Score Entry
- **Best Practice**: Touch-friendly interface, game-by-game entry (table tennis: best of 5 or 7), validation
- **Current State**: ⚠️ Simple score input (e.g., "11-9")
- **Gap**: No game-by-game entry, no touch-optimized UI, no validation for table tennis scoring rules

#### 11. Live Tournament Management
- **Best Practice**: Real-time updates, live bracket, instant notifications
- **Current State**: ⚠️ Polling-based (cache TTL), no WebSocket
- **Gap**: No real-time push, no live bracket updates

#### 12. Tournament Dashboard
- **Best Practice**: At-a-glance status, quick actions, drill-down capability
- **Current State**: ✅ Basic dashboard with metrics
- **Gap**: No tournament-specific dashboard, no quick actions from dashboard

#### 13. Administrator Workflow
- **Best Practice**: Role-based access, bulk operations, data export, system health
- **Current State**: ✅ Basic admin page, audit logging
- **Gap**: No bulk operations, no data export, limited role management

#### 14. Usability & UX Patterns
- **Best Practice**: Progressive disclosure, contextual help, keyboard shortcuts, mobile-responsive
- **Current State**: ⚠️ Basic Streamlit UI, no mobile optimization
- **Gap**: No mobile-responsive design, no keyboard shortcuts, limited contextual help

---

## Best Practices Summary

| Area | Best Practice | Current State | Priority |
|------|--------------|---------------|----------|
| Tournament Creation | Multi-step wizard with validation | ✅ Implemented | — |
| Player Registration | Bulk import, check-in, club/division | ⚠️ Basic | High |
| Event Management | Multiple events (singles, doubles, mixed) | ⚠️ Partial | High |
| Seeding | Rating-based with manual override | ⚠️ UI only | Medium |
| Bracket Display | Interactive with seed numbers | ⚠️ Partial | Medium |
| Round Robin | Tie-breakers (H2H, point diff) | ⚠️ Basic | Medium |
| Score Entry | Game-by-game, touch-optimized | ❌ Missing | High |
| Match Scheduling | Auto-schedule with constraints | ❌ Missing | Medium |
| Table Assignment | Auto-assign, rotation | ⚠️ Basic | Low |
| Live Updates | Real-time push, WebSocket | ❌ Missing | Medium |
| Dashboard | Tournament-specific, quick actions | ⚠️ Basic | Medium |
| Mobile UX | Responsive, touch-friendly | ❌ Missing | High |
| Accessibility | ARIA, keyboard nav, contrast | ❌ Missing | Medium |

---

## Gap Analysis

### Critical Gaps

| # | Gap | Why It Matters | Impact | Complexity | Affected Modules |
|---|-----|---------------|--------|------------|------------------|
| 1 | **No Doubles/Mixed Doubles Support** | Most tournaments include doubles events | Users cannot run complete tournaments | High | `models.py` (Entry), `tournament_engine.py`, `events_draws.py`, UI |
| 2 | **No Game-by-Game Score Entry** | Table tennis matches are best of 5/7 games | Operators must manually track games | Medium | `models.py` (Match), `operator_console.py`, API |
| 3 | **No Mobile-Responsive Design** | Operators use tablets/phones at venues | Poor UX on mobile devices | High | All pages, `design_system.py` |
| 4 | **Seeding Not Implemented** | Seeding is critical for fair brackets | Brackets are random only | Medium | `tournament_engine.py`, `events_draws.py` |
| 5 | **No Bulk Player Import** | Tournaments have 50-200+ players | Manual entry is tedious | Low | `participants_panel.py`, `events_draws.py` |

### High Priority Gaps

| # | Gap | Why It Matters | Impact | Complexity | Affected Modules |
|---|-----|---------------|--------|------------|------------------|
| 6 | **No Check-In System** | Players must confirm presence | Delays tournament start | Medium | `models.py` (Entry), new UI |
| 7 | **No Round Robin Tie-Breakers** | Groups often have tied records | Manual tie-breaking required | Medium | `bracket_manager.py`, standings UI |
| 8 | **No Tournament-Specific Dashboard** | Operators need at-a-glance status | Must navigate multiple pages | Medium | `dashboard.py`, new components |
| 9 | **No Auto-Scheduling** | Manual scheduling is error-prone | Table conflicts, idle time | High | `scheduler.py`, `operator_console.py` |
| 10 | **No Real-Time Updates** | Stale data causes confusion | Manual refresh required | High | API, frontend, caching strategy |

### Medium Priority Gaps

| # | Gap | Why It Matters | Impact | Complexity | Affected Modules |
|---|-----|---------------|--------|------------|------------------|
| 11 | **No Consolation/Plate Brackets** | Players want to play more matches | Lower engagement | High | `tournament_engine.py`, bracket renderer |
| 12 | **No Third-Place Match** | Standard in table tennis | Missing from knockout | Low | `tournament_engine.py` |
| 13 | **No Data Export** | Organizers need reports | Manual data extraction | Low | `admin.py`, new export service |
| 14 | **No Keyboard Shortcuts** | Operators need fast actions | Slower operations | Low | `operator_console.py` |
| 15 | **No Accessibility Features** | Inclusive design required | Excludes users | Medium | All pages, `design_system.py` |

### Low Priority Gaps

| # | Gap | Why It Matters | Impact | Complexity | Affected Modules |
|---|-----|---------------|--------|------------|------------------|
| 16 | **No Team Events** | Club/team tournaments | Niche requirement | High | `models.py`, `tournament_engine.py` |
| 17 | **No Double Elimination** | Alternative format | Niche requirement | High | `tournament_engine.py` |
| 18 | **No Live Commentary** | Audience engagement | Nice-to-have | Medium | `commentary_service.py` |
| 19 | **No Photo/Video Gallery** | Tournament memories | Nice-to-have | Low | New models, UI |
| 20 | **No Payment/Registration Fee** | Monetization | Out of scope | High | New models, payment integration |

---

## Prioritized Improvement Opportunities

### Quick Wins (Small Effort, High Impact)

| Priority | Opportunity | Effort | User Value |
|----------|-------------|--------|------------|
| P0 | Navigation regrouping (sections) | Small | Clearer information architecture |
| P0 | Remove Participants redirect page | Small | Cleaner navigation |
| P0 | Add freshness indicators to Public Board | Small | Trust in data accuracy |
| P0 | Hide experimental pages by default | Small | Reduced cognitive load |
| P1 | Bulk player import (CSV) | Small | Faster tournament setup |
| P1 | Add game-by-game score entry | Medium | Accurate match reporting |
| P1 | Implement seeding in bracket generation | Medium | Fairer tournaments |
| P1 | Add round robin tie-breakers | Medium | Automated standings |
| P2 | Add keyboard shortcuts to Operator Console | Small | Faster operations |
| P2 | Add data export (CSV/JSON) | Small | Reporting capability |

### Medium-Term Improvements (Medium Effort, High Impact)

| Priority | Opportunity | Effort | User Value |
|----------|-------------|--------|------------|
| P1 | Mobile-responsive design | Large | Venue usability |
| P1 | Check-in system | Medium | Tournament readiness |
| P1 | Tournament-specific dashboard | Medium | At-a-glance status |
| P2 | Auto-scheduling with constraints | Large | Efficient table usage |
| P2 | Real-time updates (WebSocket/polling) | Large | Live data freshness |
| P2 | Doubles/mixed doubles support | Large | Complete tournament support |
| P3 | Consolation/plate brackets | Large | More matches per player |
| P3 | Third-place match | Small | Standard tournament feature |

### Long-Term Improvements (Large Effort, Strategic Value)

| Priority | Opportunity | Effort | User Value |
|----------|-------------|--------|------------|
| P2 | Double elimination format | Large | Format flexibility |
| P3 | Team events | Large | Club tournaments |
| P3 | Payment/registration integration | Large | Monetization |
| P3 | Live commentary | Medium | Audience engagement |
| P4 | Photo/video gallery | Small | Tournament memories |
| P4 | Advanced analytics | Medium | Player development |

---

## Detailed Implementation Roadmap

### Phase 1: Foundation & Quick Wins (Weeks 1-3)

**Objective:** Clean up navigation, remove dead ends, and add high-impact small features.

**User Value:** Reduced confusion, faster tournament setup, clearer data freshness.

**Affected Files:**
- `tournament_platform/app/main.py` — navigation restructuring
- `tournament_platform/app/pages/participants.py` — remove redirect
- `tournament_platform/app/pages/public_board.py` — freshness indicators
- `tournament_platform/app/pages/events_draws.py` — bulk import, seeding
- `tournament_platform/app/components/participants_panel.py` — CSV upload
- `tournament_platform/services/ai_tournament_suggestions.py` — seeding integration

**Dependencies:** None (incremental changes)

**Implementation Order:**
1. Navigation regrouping (main.py)
2. Remove Participants redirect
3. Add freshness indicators to Public Board
4. Hide experimental pages
5. Add CSV bulk import to Participants panel
6. Implement seeding in bracket generation
7. Add game-by-game score entry
8. Add round robin tie-breakers

**Risks:**
- Navigation changes may confuse existing users (mitigate with clear section labels)
- CSV import may have encoding issues (validate with common formats)

**Estimated Effort:** 2-3 weeks

---

### Phase 2: Core UX Improvements (Weeks 4-8)

**Objective:** Improve the tournament day experience with better mobile UX, check-in, and dashboard.

**User Value:** Faster match operations, better venue usability, at-a-glance status.

**Affected Files:**
- `tournament_platform/app/design_system.py` — mobile-responsive styles
- `tournament_platform/app/pages/operator_console.py` — mobile optimization, keyboard shortcuts
- `tournament_platform/app/pages/dashboard.py` — tournament-specific dashboard
- `tournament_platform/app/pages/events_draws.py` — check-in system
- `tournament_platform/models.py` — check-in fields
- `tournament_platform/app/pages/admin.py` — data export

**Dependencies:** Phase 1 complete

**Implementation Order:**
1. Mobile-responsive design system updates
2. Operator Console mobile optimization
3. Keyboard shortcuts for Operator Console
4. Check-in system (models + UI)
5. Tournament-specific dashboard
6. Data export functionality

**Risks:**
- Mobile redesign may break existing desktop layouts (test both)
- Check-in system adds complexity to tournament setup

**Estimated Effort:** 4-5 weeks

---

### Phase 3: Advanced Tournament Features (Weeks 9-14)

**Objective:** Add doubles/mixed doubles support and improve bracket features.

**User Value:** Support for complete tournament programs, fairer brackets.

**Affected Files:**
- `tournament_platform/models.py` — doubles support in Entry
- `tournament_platform/services/tournament_engine.py` — doubles bracket generation
- `tournament_platform/app/pages/events_draws.py` — doubles UI
- `tournament_platform/app/components/bracket_renderer.py` — seed display
- `tournament_platform/services/bracket_manager.py` — tie-breakers

**Dependencies:** Phase 2 complete

**Implementation Order:**
1. Extend Entry model for doubles (player2_id already exists)
2. Update tournament creation wizard for doubles selection
3. Implement doubles bracket generation
4. Add seed numbers to bracket display
5. Add consolation/plate bracket option
6. Add third-place match option

**Risks:**
- Doubles bracket generation is complex (byes, seeding pairs)
- Existing bracket renderer may need significant updates

**Estimated Effort:** 5-6 weeks

---

### Phase 4: Live Operations & Scheduling (Weeks 15-20)

**Objective:** Add auto-scheduling and real-time updates for live tournament management.

**User Value:** Reduced manual work, real-time data freshness, efficient table usage.

**Affected Files:**
- `tournament_platform/services/scheduler.py` — auto-scheduler
- `tournament_platform/services/table_availability_service.py` — table assignment
- `tournament_platform/api/server.py` — WebSocket/polling endpoints
- `tournament_platform/app/pages/operator_console.py` — real-time updates
- `tournament_platform/app/pages/public_board.py` — auto-refresh

**Dependencies:** Phase 3 complete

**Implementation Order:**
1. Auto-scheduler with table constraints
2. Automatic table assignment
3. Real-time polling optimization (reduce TTL, add manual refresh)
4. WebSocket investigation (if feasible with Streamlit)
5. Live bracket updates

**Risks:**
- Auto-scheduling is computationally complex
- Real-time updates may increase server load
- Streamlit has limited WebSocket support

**Estimated Effort:** 5-6 weeks

---

### Phase 5: Polish & Accessibility (Weeks 21-24)

**Objective:** Improve accessibility, add advanced features, and polish UX.

**User Value:** Inclusive design, professional feel, advanced capabilities.

**Affected Files:**
- `tournament_platform/app/design_system.py` — accessibility styles
- All pages — ARIA labels, keyboard navigation
- `tournament_platform/app/pages/admin.py` — advanced admin features
- `tournament_platform/services/commentary_service.py` — live commentary

**Dependencies:** Phase 4 complete

**Implementation Order:**
1. Accessibility audit and fixes
2. Advanced admin features (bulk operations, system health)
3. Live commentary (optional)
4. Performance optimization
5. Documentation updates

**Risks:**
- Accessibility fixes may require significant UI changes
- Streamlit has limited accessibility support

**Estimated Effort:** 3-4 weeks

---

## Technical Recommendations

### Architecture

1. **Incremental Refactoring**: Avoid big rewrites. Refactor one page/component at a time.
2. **Service Layer Expansion**: Move business logic from pages to services (already good, but pages like `events_draws.py` and `operator_console.py` are too large).
3. **Read Models**: Continue using the read-model pattern (`tournament_read_models.py`) for complex queries.
4. **API Consistency**: The FastAPI backend is well-structured. Continue adding endpoints for new features.

### Component Organization

1. **Page Size Limit**: No page should exceed 1000 lines. Split `events_draws.py`, `operator_console.py`, and `voice_scorekeeper.py`.
2. **Reusable Components**: Expand `app/components/` with:
   - `match_card.py` — standardized match display
   - `score_input.py` — game-by-game score entry
   - `player_selector.py` — searchable player dropdown
   - `tournament_card.py` — tournament summary card
   - `mobile_nav.py` — mobile-optimized navigation
3. **Design System**: Expand `design_system.py` with:
   - Responsive breakpoints
   - Touch-friendly button sizes (min 44x44px)
   - Accessibility utilities (ARIA helpers)

### State Management

1. **Session State Hygiene**: Many pages use `st.session_state` extensively. Create a `state_manager.py` utility to centralize state initialization and cleanup.
2. **Cache Strategy**: Review `@st.cache_data` TTLs. Consider `@st.cache_resource` for database connections (already used for AI engine).

### Routing

1. **Navigation Sections**: Use `st.navigation` section grouping (already partially implemented).
2. **Deep Linking**: Add query parameter support for direct match/player links.
3. **Breadcrumbs**: Consider adding breadcrumb navigation for deep pages.

### Validation

1. **Pydantic Models**: Expand `api/schemas.py` for all API inputs.
2. **Frontend Validation**: Add client-side validation before API calls (score format, required fields).
3. **Database Constraints**: Add unique constraints where appropriate (e.g., tournament name + event type).

### Error Handling

1. **Consistent Error UI**: Create `error_handler.py` component for standardized error display.
2. **Graceful Degradation**: Handle API failures with cached data and clear messaging.
3. **Logging**: Continue structured logging. Add request IDs for tracing.

### Testing

1. **Test Coverage**: Current tests focus on services. Add page-level integration tests.
2. **E2E Tests**: Consider Playwright for critical user flows (tournament creation, match reporting).
3. **Test Data**: Expand `seed_quick_win_demo.py` for realistic scenarios.

### Maintainability

1. **Type Hints**: All new code should have complete type hints.
2. **Docstrings**: All public functions/classes should have docstrings.
3. **Linting**: Enforce `ruff` or `black` formatting.
4. **Pre-commit Hooks**: Add hooks for linting, type checking, and migration checks.

### Scalability

1. **Database**: Plan PostgreSQL migration for production (already in ARCHITECTURE.md).
2. **Caching**: Add Redis for session caching and rate limiting.
3. **Background Tasks**: Use Celery for async operations (notifications, report generation).
4. **CDN**: Serve static assets (bracket images, logos) via CDN.

---

## UX Recommendations

### Navigation

1. **Section Grouping**: Already implemented. Add clear section headers with descriptions.
2. **Context-Aware Navigation**: Show relevant pages based on tournament state (e.g., hide "Create Tournament" when one is active).
3. **Breadcrumbs**: Add breadcrumb trail for pages deeper than one level.
4. **Search**: Add global search (Ctrl+K) for players, matches, tournaments.

### Page Layout

1. **Consistent Header**: All pages should use `page_header.py` component.
2. **Card-Based Layout**: Use bordered containers for related content.
3. **Whitespace**: Increase padding between sections (currently too dense).
4. **Typography**: Use consistent heading hierarchy (H1 for page title, H2 for sections).

### Tournament Setup Flow

1. **Progressive Disclosure**: Show only relevant fields per step (already implemented in wizard).
2. **Inline Validation**: Validate fields as user types, not just on submit.
3. **Preview**: Show bracket preview before final creation (partially implemented).
4. **Save Draft**: Allow saving tournament setup as draft for later completion.

### Tournament Dashboard

1. **Tournament Selector**: Always visible, persistent across pages.
2. **Quick Actions**: Add "Call Next Match", "Start Next Match" buttons directly on dashboard.
3. **Status Strip**: Show current match, next match, delayed matches at top.
4. **Drill-Down**: Click on any metric to see detailed view.

### Match Management

1. **Match Card**: Standardize match display across all pages.
2. **Score Entry**: Game-by-game input with automatic total calculation.
3. **Bulk Actions**: Allow completing multiple matches at once (e.g., "Complete all round-robin matches").
4. **Conflict Resolution**: Visual table conflict indicators with suggested resolutions.

### Score Entry

1. **Touch-Friendly**: Large buttons for score increments (+, -).
2. **Game-by-Game**: Enter each game score separately (e.g., 11-9, 11-7, 9-11, 11-6).
3. **Validation**: Enforce table tennis rules (must win by 2, max 15 points in old rules, etc.).
4. **Quick Presets**: Buttons for common scores (11-9, 11-8, etc.).

### Player Management

1. **Player Card**: Standardized player display with photo placeholder, name, rating, club.
2. **Bulk Import**: CSV upload with column mapping.
3. **Check-In**: QR code or PIN check-in at venue.
4. **Duplicate Detection**: Real-time duplicate warning during entry.

### Mobile Usability

1. **Responsive Grid**: Use `st.columns` with breakpoint-aware widths.
2. **Touch Targets**: Minimum 44x44px for all interactive elements.
3. **Simplified Forms**: Collapse advanced options behind "Show more" on mobile.
4. **Offline Mode**: Cache critical data for offline viewing (public board).

### Accessibility

1. **ARIA Labels**: Add `aria-label` to all interactive elements.
2. **Keyboard Navigation**: Tab order should be logical; Enter/Space to activate buttons.
3. **Color Contrast**: Meet WCAG AA (4.5:1 for text).
4. **Screen Reader**: Test with NVDA/JAWS for critical flows.

### Consistency Across Pages

1. **Component Library**: All pages should use the same set of components.
2. **Color Palette**: Use `design_system.py` colors consistently.
3. **Iconography**: Use emoji consistently (already done) or migrate to a proper icon library.
4. **Terminology**: Use consistent terms ("Match" not "Game", "Tournament" not "Event" in user-facing text).

---

## Risks and Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Streamlit limitations hinder UX improvements | High | Medium | Accept limitations; consider future migration to React/Vue |
| Mobile redesign breaks desktop layout | Medium | High | Test both viewports; use responsive utilities |
| Doubles support requires significant data model changes | Medium | High | Use existing `player2_id` in Entry; incremental rollout |
| Auto-scheduling is computationally expensive | Medium | Medium | Cache results; limit to small tournaments |
| Real-time updates increase server load | Medium | Medium | Use efficient polling; consider WebSocket only for critical data |
| Users resist navigation changes | Medium | Low | Clear communication; keep old paths as redirects |
| AI features distract from core tournament management | Low | Medium | Clearly label experimental features; hide by default |
| SQLite concurrency issues at scale | Medium | High | Plan PostgreSQL migration; use connection pooling |

### Trade-offs

| Decision | Trade-off | Rationale |
|----------|-----------|-----------|
| Keep Streamlit vs. migrate to React | Streamlit limits UX but faster development | Incremental improvements within Streamlit; plan migration for v3 |
| SQLite vs. PostgreSQL | SQLite limits concurrency but simpler setup | Default to SQLite; provide PostgreSQL migration path |
| Monolithic pages vs. micro-frontend | Monolithic is simpler but harder to maintain | Refactor pages incrementally; avoid premature optimization |
| Feature flags vs. branches | Flags add complexity but enable gradual rollout | Use flags for experimental features only |
| In-memory bracket vs. database | In-memory is faster but less persistent | Use database as source of truth; cache for performance |

---

## Suggested Milestones

### Milestone 1: Navigation Cleanup (Week 2)
- [ ] Navigation sections implemented
- [ ] Participants redirect removed
- [ ] Experimental pages hidden by default
- [ ] Public Board freshness indicators added

### Milestone 2: Tournament Setup Enhancement (Week 4)
- [ ] CSV bulk import working
- [ ] Seeding implemented in bracket generation
- [ ] Game-by-game score entry added
- [ ] Round robin tie-breakers implemented

### Milestone 3: Mobile & Operator UX (Week 8)
- [ ] Mobile-responsive design system
- [ ] Operator Console mobile-optimized
- [ ] Keyboard shortcuts added
- [ ] Check-in system implemented
- [ ] Tournament-specific dashboard

### Milestone 4: Doubles & Advanced Features (Week 14)
- [ ] Doubles/mixed doubles support
- [ ] Seed numbers in bracket display
- [ ] Consolation bracket option
- [ ] Third-place match option

### Milestone 5: Live Operations (Week 20)
- [ ] Auto-scheduler implemented
- [ ] Real-time updates optimized
- [ ] Automatic table assignment
- [ ] Live bracket updates

### Milestone 6: Polish & Launch (Week 24)
- [ ] Accessibility audit passed
- [ ] Performance optimized
- [ ] Documentation updated
- [ ] User acceptance testing completed

---

## Appendix: Existing Plans Reference

The repository already contains several detailed plans that inform this document:

| Plan | Path | Relevance |
|------|------|-----------|
| UX Redesign Architecture Plan | `plans/ux_redesign_architecture_plan.md` | Navigation restructuring, home page, participants tab |
| Quick Wins Implementation Plan | `plans/quick_wins_implementation_plan.md` | Public board, operator console, player path, voice shortcuts |
| Page Consolidation Plan | `plans/page_consolidation_plan.md` | Page structure and navigation |
| AI Operator Implementation Plan | `plans/AI_OPERATOR_IMPLEMENTATION_PLAN.md` | AI-powered operator features |
| Voice Scorekeeper Plans | `plans/voice_scorekeeper_*.md` | Voice-based match reporting |

This implementation plan builds upon these existing plans, incorporating their recommendations into a unified roadmap with updated priorities based on current codebase analysis.

---

*End of Implementation Plan*
