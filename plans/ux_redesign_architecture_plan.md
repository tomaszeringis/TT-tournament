# UX Redesign Architecture Plan

## 1. Current State Summary

### App Architecture
The Tournament Platform is a Streamlit/FastAPI application with:
- **Frontend**: Streamlit 1.35+ with `st.navigation` for multi-page routing
- **Backend**: FastAPI with async endpoints
- **Database**: SQLAlchemy ORM with SQLite/PostgreSQL support
- **AI Engine**: Ollama-based for match insights and Q&A

### Current Navigation Structure
```
main.py (entry point)
├── Dashboard (📊) - Overview, Rankings, Recent/Upcoming matches, AI insights
├── Participants (👥) - Redirect to Events & Draws
├── Events & Draws (🏆) - Tournament creation wizard, active tournaments, brackets
├── Rankings (🏆) - Player rankings
├── Public Board (📺) - Read-only public view
├── Operator Console (🎛️) - Match control, table status, audit log
├── AI Assistant (🤖) - AI-powered features
├── Video Scorekeeper (🎥) - Video-based match tracking
├── Admin (👨‍💼) - Admin-only page
└── [Debug/Admin] Dataset Catalog, Coaching Lab, Experiment Dashboard
```

### Key Issues Identified
1. **Flat Navigation**: All pages are at the same level, no grouping by user job or tournament phase
2. **No Home/Getting Started**: Users land directly on Dashboard without clear next steps
3. **Participants Page**: Just a redirect wrapper, no real functionality
4. **Operator Console**: Dense interface with many controls, not optimized for match-day operations
5. **Public Board**: Lacks freshness indicators and clear refresh behavior
6. **AI/ML Pages**: Experimental features (Dataset Catalog, Coaching Lab, Experiment Dashboard) exposed in main navigation
7. **Video Scorekeeper**: Appears in main nav but is experimental/unfinished
8. **No Player Profile**: No dedicated page for individual player history/stats

### High-Risk Areas
- `tournament_platform/app/main.py` - Navigation configuration, authentication
- `tournament_platform/app/pages/operator_console.py` - Complex match management logic
- `tournament_platform/app/pages/events_draws.py` - Tournament creation and bracket logic
- `tournament_platform/app/components/participants_panel.py` - Player list uses `st.code()` instead of proper table

## 2. Proposed Information Architecture

### New Navigation Structure
```
Home (🏠) - Getting started, current event status, quick actions, tour
Setup (⚙️)
├── Events & Draws (🏆) - Tournament creation, participant management (tab), seeding, onboarding
└── Rankings (🏆) - Player ratings and history
Tournament Day (🎮)
├── Match Center (🎛️) - Focused match operations (renamed from Operator Console)
├── Public Board (📺) - Live audience view
└── Voice Scorekeeper (🔊) - Voice-based match reporting
Insights (📊)
├── Dashboard (📊) - Analytics and overview
└── AI Assistant (🤖) - AI-powered insights (clearly labeled as experimental)
Admin (👨‍💼) - System administration
Experimental (🧪) - Hidden by default, accessible via DEBUG_UI_ENABLED
├── Video Scorekeeper
├── Dataset Catalog
├── Coaching Lab
└── Experiment Dashboard
```

### Page Mapping
| Current Page | Proposed Destination | Notes |
|-------------|---------------------|-------|
| Dashboard | Insights/Dashboard | Keep as analytics hub |
| Participants | **REMOVED** - Functionality merged into Events & Draws | Remove redirect page, use tab in Events & Draws |
| Events & Draws | Setup/Events & Draws | Keep, add seeding preview, add Participants tab |
| Rankings | Setup/Rankings | Move to Setup section |
| Public Board | Tournament Day/Public Board | Keep, add freshness indicators |
| Operator Console | Tournament Day/Match Center | Rename, simplify |
| AI Assistant | Insights/AI Assistant | Keep, label as experimental |
| Voice Scorekeeper | Tournament Day/Voice Scorekeeper | Keep |
| Video Scorekeeper | Hidden/Experimental | Remove from main nav |
| Admin | Admin/Admin | Keep as-is |
| Dataset Catalog | Experimental | Hidden by default |
| Coaching Lab | Experimental | Hidden by default |
| Experiment Dashboard | Experimental | Hidden by default |

## 3. Phase 1: Quick Wins

### 3.1 Navigation Regrouping
**Files touched:**
- `tournament_platform/app/main.py`

**Changes:**
- Reorganize pages into logical sections using `st.navigation` section grouping
- Move Video Scorekeeper to experimental section
- Add clear section headers

**Acceptance criteria:**
- Navigation shows 4 main sections: Home, Setup, Tournament Day, Insights, Admin
- Experimental pages only visible when `DEBUG_UI_ENABLED=true`
- All existing functionality preserved

### 3.2 Home / Getting Started Page
**Files to create:**
- `tournament_platform/app/pages/home.py`

**Components to create:**
- `tournament_platform/app/components/page_header.py` - Reusable page header component
- `tournament_platform/app/components/empty_state.py` - Reusable empty state component
- `tournament_platform/app/components/tournament_summary_card.py` - Tournament status card
- `tournament_platform/app/components/getting_started_tour.py` - Interactive tour for first-time users

**Acceptance criteria:**
- Shows "Create Tournament" primary action when no tournaments exist
- Shows "Resume Current Event" card when tournaments are in progress
- Displays setup checklist (players registered, tournament created, matches scheduled)
- Shows recent tournaments list
- Live operations summary strip (current matches, next matches)
- "Getting Started" tour available for first-time users (modal or sidebar)

### 3.3 Participants Tab in Events & Draws
**Files touched:**
- `tournament_platform/app/pages/events_draws.py` - Add Participants tab
- `tournament_platform/app/components/participants_panel.py` - Enhance with table

**Changes:**
- Add Participants tab to Events & Draws page
- Replace `st.code()` player list with interactive AG-Grid table
- Add search/filter functionality
- Add status tags (checked-in, rating)
- Add duplicate warning indicators
- Add inline edit/delete actions

**Acceptance criteria:**
- Players displayed in searchable table within Events & Draws
- Can filter by name, rating, check-in status
- Duplicate detection warnings shown
- Inline actions for edit/delete
- Bulk import placeholder (CSV upload)
- Remove standalone Participants page from navigation

### 3.4 Public Board Freshness Indicators
**Files touched:**
- `tournament_platform/app/pages/public_board.py`

**Components to create:**
- `tournament_platform/app/components/freshness_indicator.py`

**Changes:**
- Add "Last updated: X seconds ago" indicator
- Add stale data warning (data older than 30 seconds)
- Add manual refresh button
- Auto-refresh toggle for kiosk mode

**Acceptance criteria:**
- Shows last update timestamp
- Warning when data is stale
- Manual refresh works
- Kiosk mode auto-refreshes

### 3.5 Hide Experimental Pages
**Files touched:**
- `tournament_platform/app/main.py`

**Changes:**
- Video Scorekeeper moved to experimental section
- Add clear "Experimental" label to AI Assistant
- All experimental pages behind `DEBUG_UI_ENABLED` flag

**Acceptance criteria:**
- Experimental pages not visible in default navigation
- Admin users can still access via debug flag
- Clear labeling of experimental features

## 4. Phase 2: Core Workflow Improvements

### 4.1 Richer Event Setup
**Files touched:**
- `tournament_platform/app/pages/events_draws.py`

**Changes:**
- Add participant count validation (min 2, max 128)
- Add seeding options (random, rating-based, manual)
- Add setup preview showing bracket/draw consequences
- Add event-level configuration (date, venue, description)

**Acceptance criteria:**
- Validation prevents invalid tournament creation
- Seeding options available and functional
- Preview shows expected bracket structure
- Event metadata stored and displayed

### 4.2 Player Profile Page
**Files to create:**
- `tournament_platform/app/pages/player_profile.py`

**Components to create:**
- `tournament_platform/app/components/player_path.py` (exists, may need enhancement)

**Changes:**
- Dedicated page for individual player
- Rating/ranking trend chart
- Match history table
- Current event path visualization
- Upcoming matches list
- Organizer notes/status field

**Acceptance criteria:**
- Player profile accessible from any player link
- Shows complete match history
- Displays rating trend over time
- Shows current tournament path

### 4.3 Match Reporting and Queue Action Cleanup
**Files touched:**
- `tournament_platform/app/pages/operator_console.py`
- `tournament_platform/services/operator_commands.py`

**Changes:**
- Simplify match action buttons
- Add confirmation dialogs for destructive actions
- Add keyboard shortcuts for common actions
- Improve error handling and user feedback

**Acceptance criteria:**
- Actions clearly labeled and grouped
- Destructive actions require confirmation
- Keyboard shortcuts documented
- Clear success/error feedback

## 5. Phase 3: Tournament-Day Operations

### 5.1 Match Center (Refactored Operator Console)
**Files touched:**
- `tournament_platform/app/pages/operator_console.py` → rename to `match_center.py`

**Components to create:**
- `tournament_platform/app/components/match_queue_table.py` - Compact match rows
- `tournament_platform/app/components/status_chip.py` - Visual status indicators
- `tournament_platform/app/components/match_action_dialog.py` - Row-level actions

**Changes:**
- Turn into focused match center
- Use compact match rows with state chips
- Add filters (by status, by table, by player)
- Use dialogs/popovers for match actions
- Prioritize actions: call, start, assign table, delay, reschedule, enter result, announce

**Acceptance criteria:**
- Clean, focused interface
- Quick action buttons for each match
- Filter controls work correctly
- Dialogs for detailed actions
- Mobile-friendly layout

### 5.2 Live Board Improvements
**Files touched:**
- `tournament_platform/app/pages/public_board.py`

**Changes:**
- Separate TV/public board needs from operator controls
- Add predictable refresh behavior
- Add "last updated" and stale-data indicators
- Add match countdown timers
- Add winner celebration animations

**Acceptance criteria:**
- Clean read-only view
- Reliable auto-refresh
- Clear data freshness
- Visual match status indicators

### 5.3 Schedule/Calendar Board
**Files to create:**
- `tournament_platform/app/pages/schedule.py`

**Components to create:**
- `tournament_platform/app/components/schedule_board.py` - Visual schedule grid

**Changes:**
- Table/venue lanes
- Drag/drop or staged equivalent
- Delay propagation
- Conflict warnings

**Acceptance criteria:**
- Visual schedule grid
- Table assignments clear
- Conflicts highlighted
- Delays propagate correctly

## 6. Phase 4: Scale, Trust, and AI

### 6.1 Design System Hardening
**Files to create:**
- `tournament_platform/app/components/__init__.py` - Export all components
- `tournament_platform/app/components/action_bar.py` - Consistent action bars
- `tournament_platform/app/components/kpi_row.py` - Metric display
- `tournament_platform/app/components/card.py` - Consistent card styling

**Changes:**
- Create reusable UI components
- Standardize page headers, action bars, status chips
- Add empty states for all list views
- Add loading states

**Acceptance criteria:**
- Consistent UI across all pages
- Reusable components documented
- Empty states for all data views
- Loading indicators for async operations

### 6.2 Modularization of Long Pages
**Files to refactor:**
- `tournament_platform/app/pages/operator_console.py`
- `tournament_platform/app/pages/events_draws.py`
- `tournament_platform/app/pages/dashboard.py`

**Changes:**
- Split into page containers + reusable components
- Move service/domain logic to services/
- Keep Streamlit page files focused on UI

**Acceptance criteria:**
- Page files under 200 lines
- Business logic in services
- Components reusable across pages

### 6.3 Production-Quality AI Assistant Placement
**Files touched:**
- `tournament_platform/app/pages/ai_assistant.py`

**Changes:**
- Add clear "Experimental" label
- Hide by default, show only for admin or with flag
- Add disclaimer about AI accuracy
- Focus on core tournament Q&A

**Acceptance criteria:**
- Clear experimental labeling
- Not in main user flow
- Disclaimers visible
- Core features work reliably

### 6.4 Lab/Experimental Feature Governance
**Files touched:**
- `tournament_platform/app/main.py`
- `tournament_platform/config/__init__.py`

**Changes:**
- All experimental features behind `DEBUG_UI_ENABLED`
- Clear visual separation
- Documentation of experimental features

**Acceptance criteria:**
- Experimental features hidden by default
- Clear labeling when visible
- No confusion with production features

## 7. Component Extraction Plan

### Proposed Reusable Components

| Component | Purpose | Files to Create/Modify |
|-----------|---------|------------------------|
| `PageHeader` | Consistent page headers with title, description, actions | `components/page_header.py` |
| `EmptyState` | Standard empty state with icon, message, CTA | `components/empty_state.py` |
| `SetupChecklist` | Visual checklist for tournament setup steps | `components/setup_checklist.py` |
| `ActionBar` | Consistent action button grouping | `components/action_bar.py` |
| `StatusChip` | Visual status indicators (pending, active, completed) | `components/status_chip.py` |
| `FreshnessIndicator` | Last updated timestamp and stale warning | `components/freshness_indicator.py` |
| `PlayerTable` | Searchable, filterable player table with actions | `components/participants_panel.py` (enhance) |
| `MatchQueueTable` | Compact match rows for operator view | `components/match_queue_table.py` |
| `MatchActionDialog` | Dialog for match-level actions | `components/match_action_dialog.py` |
| `TournamentSummaryCard` | Card showing tournament status | `components/tournament_summary_card.py` |
| `KPIRow` | Horizontal metric display | `components/kpi_row.py` |
| `Card` | Consistent card container | `components/card.py` |
| `PublicBoardSection` | Section for public board display | `components/public_board_section.py` |
| `GettingStartedTour` | Interactive tour for first-time users | `components/getting_started_tour.py` |

## 8. Data/API Impact

### No Schema Changes Required in Phase 1
- All proposed changes work with existing models
- Player check-in status can be session-state based initially
- No new database tables needed

### Potential Future Changes
- `Player.check_in_status` - Boolean for check-in tracking
- `Player.notes` - Text field for organizer notes
- `Tournament.venue` - String for venue name
- `Tournament.event_date` - DateTime for event date

## 9. Testing and Verification Plan

### Existing Tests to Run
- `tests/test_phase0_quick_wins.py` - General functionality
- `tests/test_tournament_engine.py` - Tournament creation logic
- `tests/test_match_score.py` - Match scoring
- `tests/test_api.py` - API endpoints

### New Tests to Add
- `tests/test_components.py` - Component rendering tests
- `tests/test_home_page.py` - Home page functionality
- `tests/test_participants_table.py` - Player table interactions

### Streamlit Manual Verification Checklist
- [ ] Navigation groups display correctly
- [ ] Home page shows correct state (empty vs active)
- [ ] Participants table is searchable and filterable
- [ ] Public board shows freshness indicators
- [ ] Experimental pages hidden by default
- [ ] All existing pages still accessible
- [ ] Authentication still works

### Accessibility Checks
- [ ] All controls have visible labels
- [ ] Keyboard navigation works
- [ ] Color is not the only status indicator
- [ ] Responsive layout on mobile

### Regression Risks
- Navigation changes could break existing bookmarks
- Page reorganization could confuse existing users
- Experimental page hiding could break admin workflows

## 10. First Implementation Slice

### Task: Create Home Page, Reorganize Navigation, and Add Getting Started Tour

**Scope:**
1. Create `tournament_platform/app/pages/home.py` with:
   - Welcome message
   - "Create Tournament" primary action (when empty)
   - "Resume Current Event" card (when tournaments exist)
   - Setup checklist
   - Recent tournaments list
   - Live operations summary strip
   - "Getting Started" tour trigger

2. Create `tournament_platform/app/components/page_header.py`:
   - Reusable header with title, description, icon

3. Create `tournament_platform/app/components/empty_state.py`:
   - Reusable empty state component

4. Create `tournament_platform/app/components/getting_started_tour.py`:
   - Interactive tour modal for first-time users

5. Update `tournament_platform/app/main.py`:
   - Add Home as first page
   - Group pages into sections
   - Remove Video Scorekeeper from main navigation
   - Remove Participants page (merged into Events & Draws)

6. Update `tournament_platform/app/pages/events_draws.py`:
   - Add Participants tab with enhanced table
   - Add onboarding tooltips to tournament creation wizard

**Files to create:**
- `tournament_platform/app/pages/home.py`
- `tournament_platform/app/components/page_header.py`
- `tournament_platform/app/components/empty_state.py`
- `tournament_platform/app/components/getting_started_tour.py`

**Files to modify:**
- `tournament_platform/app/main.py`
- `tournament_platform/app/pages/events_draws.py`

**Estimated lines of code:**
- New files: ~200 lines
- Modified files: ~50 lines

## 11. Open Questions

1. **How should we handle the Video Scorekeeper page?**
    - Current: Exists but may be incomplete
    - Decision: Move to experimental section

2. **Should we add a "Getting Started" tour for first-time users?**
    - Decision: Yes, add interactive tour component
    - Implementation: Modal walkthrough on first visit

3. **Do we need user onboarding for tournament creation?**
    - Decision: Yes, add tooltips and inline help
    - Implementation: Step-by-step guidance in the wizard

4. **How should we handle the "public_read" query parameter mode?**
    - Currently allows unauthenticated access to Public Board
    - Should this be preserved in the new structure?