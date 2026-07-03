# Page Consolidation Architecture Plan

## 1. Current Page Inventory

| # | Page File | Title | Icon | Responsibility | Lines | Status |
|---|-----------|-------|------|----------------|-------|--------|
| 1 | `dashboard.py` | Dashboard | 📊 | Metrics, players table, recent matches, player performance radar, AI insights, quick questions, ranking intelligence (top 3 + leaderboard) | 362 | Active |
| 2 | `participants.py` | Participants | 👥 | Player registration form + player list | 111 | Active |
| 3 | `events_draws.py` | Events & Draws | 🏆 | Tournament creation wizard (4 steps), active tournaments, bracket visualization, round-robin standings, tournament generation | 416 | Active |
| 4 | `rankings.py` | Rankings | 🏆 | Leaderboard table, rating history exploration with line chart | 90 | Active |
| 5 | `public_board.py` | Public Board | 📺 | TV/projector display: now playing, coming up, delayed, standings, recent results, player lookup, announcements | 498 | Active |
| 6 | `operator_console.py` | Operator Console | 🎛️ | Command bar, voice shortcut, table status, match queue (call/start/complete/delay/reset), health dashboard, duplicate player detection, player path, audit log, announcements | 868 | Active |
| 7 | `tournament_setup.py` | Tournament Setup (Legacy) | ⚙️ | Legacy redirect to Participants + Events & Draws | 46 | **Deprecated** |
| 8 | `ai_assistant.py` | AI Assistant | 🤖 | Tournament Assistant chat + Rules Q&A chat (2 tabs) | 326 | Active |
| 9 | `voice_scorekeeper.py` | Voice Scorekeeper | 🔊 | Voice-activated scorekeeping with game-by-game scoring | ~1200 | Active |
| 10 | `video_scorekeeper.py` | Video Scorekeeper | 🎥 | AI-assisted video score suggestions with confirmation | ~500 | Active |
| 11 | `dataset_catalog.py` | Dataset Catalog | 📊 | Browse/manage datasets for multimodal AI | 145 | Active |
| 12 | `coaching_lab.py` | Coaching Lab | 🏓 | Session analysis, intent classification, recommendations | 136 | Active |
| 13 | `experiment_dashboard.py` | Experiment Dashboard | 🧪 | ML experiment tracking | 111 | Active |
| 14 | `admin.py` | Admin | 👨‍💼 | Database overview, match management, system health, danger zone, AI testing | 409 | Admin-only |
| 15 | `live_scoring.py` | Live Scoring | 📊 | **Redirect wrapper** to Voice Scorekeeper | 235 | **Redirect** |
| 16 | `video_scorekeeper_live.py` | (component) | - | Live camera component for Video Scorekeeper | 100 | Component |
| 17 | `voice_rules_chat.py` | Voice Rules Chat | 🎤 | Voice-based rules Q&A (overlaps with AI Assistant Rules Q&A) | 235 | Active |

**Total: 13 active user-facing pages + 1 admin page + 2 redirects/wrappers + 1 component**

---

## 2. Current Navigation Structure (from `app/main.py`)

```python
pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📊"),
    st.Page("pages/participants.py", title="Participants", icon="👥"),
    st.Page("pages/events_draws.py", title="Events & Draws", icon="🏆"),
    st.Page("pages/rankings.py", title="Rankings", icon="🏆"),
    st.Page("pages/public_board.py", title="Public Board", icon="📺"),
    st.Page("pages/operator_console.py", title="Operator Console", icon="🎛️"),
    st.Page("pages/tournament_setup.py", title="Tournament Setup (Legacy)", icon="⚙️"),
    st.Page("pages/ai_assistant.py", title="AI Assistant", icon="🤖"),
    st.Page("pages/voice_scorekeeper.py", title="Voice Scorekeeper", icon="🔊"),
    st.Page("pages/video_scorekeeper.py", title="Video Scorekeeper", icon="🎥"),
    st.Page("pages/dataset_catalog.py", title="Dataset Catalog", icon="📊"),
    st.Page("pages/coaching_lab.py", title="Coaching Lab", icon="🏓"),
    st.Page("pages/experiment_dashboard.py", title="Experiment Dashboard", icon="🧪"),
]
# Admin page added conditionally for admin users
```

---

## 3. Identified Overlaps and Issues

### 3.1 Duplicate/Overlapping Functionality

| Overlap | Pages Involved | Description |
|---------|---------------|-------------|
| **Rankings** | `dashboard.py` (Ranking Intelligence section) + `rankings.py` | Dashboard already shows top 3 + full leaderboard. Rankings page adds rating history exploration. |
| **Participants** | `participants.py` + `events_draws.py` (wizard Step 3) + `app/components/player_registration.py` | Three places handle player registration. Events & Draws wizard already selects participants. |
| **Tournament Setup** | `tournament_setup.py` (legacy redirect) + `events_draws.py` + `participants.py` | Already deprecated, but still in navigation. |
| **Rules Q&A** | `ai_assistant.py` (Rules Q&A tab) + `voice_rules_chat.py` | Both provide rules Q&A; voice_rules_chat adds voice input. |
| **Live Scoring** | `live_scoring.py` (redirect) + `voice_scorekeeper.py` | Live Scoring redirects to Voice Scorekeeper which now includes game-by-game scoring. |
| **Player Registration Component** | `app/components/player_registration.py` + `app/pages/participants.py` | Duplicate code - component exists but page doesn't use it. |

### 3.2 Pages That Are Mostly Setup/Configuration

| Page | Description |
|------|-------------|
| `tournament_setup.py` | Already a legacy redirect. |
| `dataset_catalog.py` | AI/ML dataset management - experimental. |
| `coaching_lab.py` | AI coaching - experimental, mostly placeholders. |
| `experiment_dashboard.py` | ML experiment tracking - experimental, mostly placeholders. |

### 3.3 Pages That Can Become Tabs/Sections

| Candidate | Target Page | Reasoning |
|-----------|-------------|-----------|
| Participants | Events & Draws | Tournament creation wizard already needs participant selection. Registration is a natural pre-tournament step. |
| Rankings | Dashboard | Dashboard already has Ranking Intelligence. Adding full leaderboard + rating history is natural. |
| Tournament Setup | Remove (already redirect) | Functionality already distributed. |
| Voice Rules Chat | AI Assistant | Rules Q&A already exists in AI Assistant. Voice input can be added as an option. |
| Live Scoring | Remove (already redirect) | Functionality moved to Voice Scorekeeper. |

---

## 4. Required Consolidation Plan

### 4.1 Participants → Events & Draws

**Current state:**
- `participants.py`: Standalone page with registration form + player list (111 lines)
- `events_draws.py`: Tournament creation wizard with Step 3 "Select Participants" (already uses player multiselect)
- `app/components/player_registration.py`: Reusable component that duplicates `participants.py` logic

**Proposed UX:**
- `events_draws.py` gets tabs:
  - **Events** (current: Create Tournament + Active Tournaments)
  - **Participants / Registration** (moved from `participants.py`)
  - **Draws** (current: bracket visualization + standings + generation)
- Users can register players before creating a tournament, or during tournament creation.
- The wizard Step 3 "Select Participants" remains but now draws from the same player pool managed in the Participants tab.

**Implementation approach:**
1. Extract `render_player_registration_section()` from `participants.py` into `app/components/player_registration.py` (already exists, needs cleanup).
2. Add a "Participants" tab to `events_draws.py`.
3. Update wizard Step 3 to reference the Participants tab if no players exist.
4. Remove `participants.py` from navigation.
5. Keep `participants.py` as a compatibility redirect for 1-2 releases.

### 4.2 Rankings → Dashboard

**Current state:**
- `rankings.py`: Leaderboard table + rating history line chart (90 lines)
- `dashboard.py`: Already has "Ranking Intelligence" section with top 3 cards + full leaderboard table (lines 315-358)

**Proposed UX:**
- `dashboard.py` gets tabs:
  - **Overview** (current: metrics, players, recent matches, performance radar, AI insights, quick questions)
  - **Rankings** (moved from `rankings.py`: full leaderboard + rating history exploration)
  - **Recent Results** (moved from current dashboard recent matches section)
  - **Upcoming Matches** (new, from public board data)
- The existing "Ranking Intelligence" section on Overview becomes a summary card linking to the Rankings tab.

**Implementation approach:**
1. Extract ranking display logic from `rankings.py` into a reusable function.
2. Add tabs to `dashboard.py`.
3. Move full leaderboard + rating history into the Rankings tab.
4. Remove `rankings.py` from navigation.
5. Keep `rankings.py` as a compatibility redirect.

### 4.3 Tournament Setup → Remove

**Current state:**
- `tournament_setup.py`: Already a legacy redirect page (46 lines)
- Already marked "This page is deprecated" in code

**Proposed UX:**
- Remove from navigation entirely.
- Setup actions redistributed:
  - Tournament metadata → Dashboard or Events & Draws wizard
  - Event creation → Events & Draws
  - Participant import/registration → Events & Draws (Participants tab)
  - Draw generation → Events & Draws (Draws tab)
- If first-run onboarding is needed, add an inline checklist on Dashboard.

**Implementation approach:**
1. Remove `tournament_setup.py` from `main.py` navigation.
2. Delete `tournament_setup.py` after confirming no broken imports.
3. Add a "Getting Started" checklist on Dashboard for new users.

---

## 5. Additional Recommended Merges

### 5.1 Voice Rules Chat → AI Assistant

**Current state:**
- `ai_assistant.py`: Has "Rules Q&A" tab with text input
- `voice_rules_chat.py`: Separate page with voice input + text fallback for rules Q&A

**Proposed UX:**
- Merge into AI Assistant's Rules Q&A tab:
  - Add voice input option (st.audio_input) alongside text input
  - Keep the same chat history and response display
- This reduces navigation by 1 page and consolidates all AI chat in one place.

**Implementation approach:**
1. Add voice input to `ai_assistant.py` Rules Q&A tab.
2. Remove `voice_rules_chat.py` from navigation.
3. Keep as redirect if needed.

### 5.2 Live Scoring → Remove (Already Redirect)

**Current state:**
- `live_scoring.py`: Redirects to `voice_scorekeeper.py` via `st.switch_page()`
- Already deprecated in code comments

**Proposed UX:**
- Remove from navigation.
- Voice Scorekeeper is the canonical scorekeeping page.

**Implementation approach:**
1. Remove `live_scoring.py` from `main.py` navigation.
2. Delete `live_scoring.py` after confirming no broken imports.

### 5.3 AI/ML Experimental Pages → Developer Tools Section

**Current state:**
- `dataset_catalog.py`: Dataset management for multimodal AI
- `coaching_lab.py`: Coaching analysis (mostly placeholders)
- `experiment_dashboard.py`: ML experiment tracking (mostly placeholders)

**Proposed UX:**
- Move behind a feature flag or "Developer Tools" section.
- Only visible when `DEBUG_UI_ENABLED=True` or user has admin role.
- This cleans up the main navigation for regular users.

**Implementation approach:**
1. Add feature flag check in `main.py`:
   ```python
   from tournament_platform.config import settings
   if settings.DEBUG_UI_ENABLED or user_role == "admin":
       pages.append(...)
   ```
2. Or create a collapsible "Developer Tools" section in navigation.

### 5.4 Operator Console → Consider Splitting or Keeping

**Current state:**
- `operator_console.py`: 868 lines with many sections (command bar, voice shortcut, table status, match queue, health dashboard, duplicate detection, player path, audit log, announcements)

**Analysis:**
- This is a legitimate operator workflow page. While large, the sections are thematically related (match flow management).
- Splitting would create more pages, not fewer.
- **Recommendation: Keep as standalone** but consider extracting reusable components (match queue items, table status cards).

### 5.5 Public Board → Keep Standalone

**Current state:**
- `public_board.py`: 498 lines, TV/projector display with hidden sidebar

**Analysis:**
- This is a specialized display mode, not a management workflow.
- Merging into Dashboard would clutter the main UI.
- **Recommendation: Keep standalone** but consider adding a "Public Board" button on Dashboard that opens it in a new tab.

---

## 6. Proposed Final Navigation Structure

### 6.1 Regular User Navigation (6 pages)

```
📊 Dashboard
  - Overview (metrics, players, recent matches, AI insights)
  - Rankings (leaderboard, rating history)
  - Recent Results
  - Upcoming Matches

🏆 Events & Draws
  - Events (tournament creation wizard, active tournaments)
  - Participants / Registration
  - Draws (bracket visualization, standings, generation)

🎛️ Matches / Scorekeeper
  - Match Queue
  - Manual Scorekeeper
  - Voice Scorekeeper
  - Video Scorekeeper

🤖 AI Assistant
  - Tournament Assistant
  - Rules Q&A (with voice option)

📺 Public Board
```

### 6.2 Admin-Only Navigation (1 page)

```
👨‍💼 Admin
  - Database Overview
  - Match Management
  - System Health
  - Danger Zone
```

### 6.3 Developer Tools (feature-flagged, admin-only)

```
🧪 Developer Tools (when DEBUG_UI_ENABLED or admin)
  - Dataset Catalog
  - Coaching Lab
  - Experiment Dashboard
```

### 6.4 Removed from Navigation

| Page | Action |
|------|--------|
| `participants.py` | Remove nav link, keep as redirect |
| `rankings.py` | Remove nav link, keep as redirect |
| `tournament_setup.py` | Remove nav link, delete file |
| `live_scoring.py` | Remove nav link, delete file |
| `voice_rules_chat.py` | Remove nav link, merge into AI Assistant |

---

## 7. File-by-File Implementation Plan

### 7.1 Files to Modify

| File | Changes |
|------|---------|
| `tournament_platform/app/main.py` | Update navigation list: remove Participants, Rankings, Tournament Setup, Live Scoring, Voice Rules Chat; add tabs to Dashboard and Events & Draws; add feature flag for dev tools |
| `tournament_platform/app/pages/dashboard.py` | Add tabs (Overview, Rankings, Recent Results, Upcoming Matches); move ranking intelligence to Rankings tab; add upcoming matches section |
| `tournament_platform/app/pages/events_draws.py` | Add Participants tab; integrate player registration component; update wizard Step 3 references |
| `tournament_platform/app/pages/ai_assistant.py` | Add voice input to Rules Q&A tab |
| `tournament_platform/app/pages/operator_console.py` | No structural changes, but consider extracting match queue item component |
| `tournament_platform/app/components/player_registration.py` | Clean up duplicate code with `participants.py`; ensure it's the single source of truth |
| `tournament_platform/config/__init__.py` | Add `DEBUG_UI_ENABLED` setting (already exists) |

### 7.2 Files to Create

| File | Purpose |
|------|---------|
| `tournament_platform/app/components/rankings_panel.py` | Reusable rankings display (leaderboard + rating history) for Dashboard |
| `tournament_platform/app/components/participants_panel.py` | Reusable participants management for Events & Draws |
| `tournament_platform/app/components/match_queue_item.py` | Reusable match queue item for Operator Console |

### 7.3 Files to Delete

| File | Reason |
|------|--------|
| `tournament_platform/app/pages/tournament_setup.py` | Already deprecated legacy redirect |
| `tournament_platform/app/pages/live_scoring.py` | Already redirects to Voice Scorekeeper |
| `tournament_platform/app/pages/voice_rules_chat.py` | Merged into AI Assistant |

### 7.4 Files to Deprecate (keep as redirects)

| File | Action |
|------|--------|
| `tournament_platform/app/pages/participants.py` | Replace with redirect to Events & Draws |
| `tournament_platform/app/pages/rankings.py` | Replace with redirect to Dashboard |

### 7.5 Navigation/Sidebar Changes

**Before (13 active pages):**
```
Dashboard, Participants, Events & Draws, Rankings, Public Board,
Operator Console, Tournament Setup (Legacy), AI Assistant,
Voice Scorekeeper, Video Scorekeeper, Dataset Catalog,
Coaching Lab, Experiment Dashboard
```

**After (6 active + 1 admin + optional dev tools):**
```
Dashboard (with tabs), Events & Draws (with tabs), Matches/Scorekeeper (with tabs),
AI Assistant (with tabs), Public Board, Admin (admin-only)
+ Developer Tools (feature-flagged)
```

---

## 8. Migration Strategy (Phased Rollout)

### Phase 0: Inventory and Baseline (1-2 days)
- [ ] Document current page dependencies and imports
- [ ] Run existing tests to establish baseline
- [ ] Verify all pages load without errors
- [ ] Create feature flag `DEBUG_UI_ENABLED` if not already present

### Phase 1: Extract Shared Components (2-3 days)
- [ ] Create `app/components/rankings_panel.py` with leaderboard + rating history
- [ ] Create `app/components/participants_panel.py` with registration form + player list
- [ ] Create `app/components/match_queue_item.py` for operator console
- [ ] Clean up duplicate code in `player_registration.py`
- [ ] Write unit tests for new components

### Phase 2: Embed Participants into Events & Draws (2-3 days)
- [ ] Add "Participants" tab to `events_draws.py`
- [ ] Integrate `participants_panel.py` component
- [ ] Update wizard Step 3 to link to Participants tab when no players exist
- [ ] Test tournament creation flow with new tab structure
- [ ] Update `participants.py` to be a redirect wrapper

### Phase 3: Embed Rankings into Dashboard (2-3 days)
- [ ] Add tabs to `dashboard.py`: Overview, Rankings, Recent Results, Upcoming Matches
- [ ] Move full leaderboard + rating history to Rankings tab
- [ ] Add upcoming matches section (from public board data)
- [ ] Convert existing Ranking Intelligence section to a summary card
- [ ] Update `rankings.py` to be a redirect wrapper

### Phase 4: Redistribute Tournament Setup (1 day)
- [ ] Remove `tournament_setup.py` from navigation
- [ ] Add "Getting Started" checklist to Dashboard for new users
- [ ] Verify all setup actions are available elsewhere
- [ ] Delete `tournament_setup.py`

### Phase 5: Remove Deprecated Pages from Navigation (1 day)
- [ ] Remove `live_scoring.py` from navigation
- [ ] Remove `voice_rules_chat.py` from navigation
- [ ] Merge voice input into `ai_assistant.py` Rules Q&A tab
- [ ] Delete `live_scoring.py` and `voice_rules_chat.py`
- [ ] Move Dataset Catalog, Coaching Lab, Experiment Dashboard behind feature flag

### Phase 6: Cleanup and Verification (1-2 days)
- [ ] Remove old sidebar links
- [ ] Verify no broken imports
- [ ] Run full test suite
- [ ] Manual QA of core flows
- [ ] Update README/documentation

---

## 9. Testing Plan

### 9.1 Automated Tests

| Test | Description |
|------|-------------|
| **App startup** | Verify `main.py` loads without import errors |
| **Navigation rendering** | Verify `st.navigation` builds with correct pages |
| **Dashboard loads** | Verify dashboard renders with all tabs |
| **Rankings panel** | Verify leaderboard and rating history display correctly |
| **Participants panel** | Verify registration form and player list work |
| **Events & Draws tabs** | Verify all three tabs render correctly |
| **Tournament creation** | Verify wizard flow works with new tab structure |
| **Draw generation** | Verify bracket generation still works |
| **Seeding/registration** | Verify participant selection in wizard works |
| **AI Assistant tabs** | Verify both tabs render and function |
| **Voice input in Rules Q&A** | Verify voice input option works |
| **Public Board** | Verify still loads independently |
| **Operator Console** | Verify still loads independently |
| **Admin page** | Verify admin-only access still works |
| **Feature flag** | Verify dev tools hidden when flag is off |

### 9.2 Manual QA Checklist

- [ ] **Dashboard loads** without errors
- [ ] **Rankings appear correctly** on Dashboard Rankings tab
- [ ] **Events and Draws loads** with all tabs
- [ ] **Participants workflow works** inside Events and Draws
  - [ ] Register new player
  - [ ] View player list
  - [ ] Select participants in tournament wizard
- [ ] **Event creation still works** via wizard
- [ ] **Draw generation still works** for knockout and round-robin
- [ ] **Seeding/registration still works** in wizard
- [ ] **Existing tournament data displays correctly**
- [ ] **Scorekeeper and match reporting still work**
  - [ ] Voice Scorekeeper
  - [ ] Video Scorekeeper
- [ ] **Removed pages no longer appear** in navigation
- [ ] **No import errors** from deleted/deprecated page files
- [ ] **Public Board** still works for TV display
- [ ] **Operator Console** still works for match flow management
- [ ] **AI Assistant** still works with both tabs
- [ ] **Admin page** still accessible for admin users
- [ ] **Core tournament flow**: create event → add participants → create draw → score matches → view rankings/dashboard

---

## 10. MVP Acceptance Criteria

The consolidation is complete when:

- [ ] **Participants is no longer a standalone navigation item**
- [ ] **Participant functionality is available inside Events & Draws** (Participants tab)
- [ ] **Rankings is no longer a standalone navigation item**
- [ ] **Rankings are available inside Dashboard** (Rankings tab)
- [ ] **Tournament Setup is no longer a standalone navigation item**
- [ ] **All useful setup actions are available elsewhere** (Events & Draws, Dashboard)
- [ ] **Navigation has fewer pages and clearer grouping** (6 main + 1 admin + optional dev tools)
- [ ] **No existing tournament workflow is lost**
- [ ] **App starts without errors**
- [ ] **Manual QA confirms core tournament flow still works**:
  - create/manage event → add participants → create draw → score matches → view rankings/dashboard

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Broken imports after deleting pages** | High | Keep deprecated pages as redirects for 1-2 releases; run import checks in CI |
| **User confusion from navigation changes** | Medium | Add tooltips/help text; consider a "What's New" banner for first visit after update |
| **Dashboard becomes too large with tabs** | Medium | Keep tabs focused; use collapsible sections within tabs |
| **Events & Draws becomes too large** | Medium | Use clear tab separation; extract components |
| **Feature flag misconfiguration** | Low | Default to hidden; admin can always enable |
| **Streamlit routing breaks with redirects** | Medium | Test `st.switch_page()` thoroughly; have fallback navigation links |
| **Database queries fail after component extraction** | Low | Keep database logic in services, not components; test thoroughly |
| **Voice Rules Chat users lose functionality** | Medium | Ensure voice input is fully integrated into AI Assistant before removing old page |

---

## 12. Questions and Assumptions for Confirmation

1. **Should the "Matches / Scorekeeper" grouping include both Voice and Video Scorekeeper?** Currently they are separate pages. The plan proposes grouping them under a parent page with tabs, but Streamlit's `st.navigation` doesn't support nested pages natively. We may need to use `st.tabs()` within a single page instead.

2. **Should Public Board remain a standalone page?** It's a specialized TV display. The plan recommends keeping it standalone, but confirm if you want it accessible from Dashboard instead.

3. **Should Operator Console be split?** It's 868 lines with many sections. The plan recommends keeping it standalone, but if you prefer splitting, we could create:
   - Match Queue
   - Table Management
   - Operator Tools (command bar, voice, audit)

4. **Should AI/ML pages (Dataset Catalog, Coaching Lab, Experiment Dashboard) be hidden behind a feature flag or removed entirely?** They are mostly placeholders. The plan recommends feature-flagging them.

5. **Should the "Getting Started" checklist on Dashboard be a modal, expander, or separate tab?** Recommend an expander at the top of the Overview tab.

6. **Should we keep the old page files as redirects or delete them immediately?** Recommend keeping as redirects for 1-2 releases, then deleting.

7. **Is the `DEBUG_UI_ENABLED` setting already in use?** It exists in `config/__init__.py` but may not be referenced in `main.py`. Need to confirm intended usage.

8. **Should the Dashboard "Upcoming Matches" tab use the same data source as Public Board?** Yes, `tournament_read_models.get_public_schedule()` can be reused.

9. **Should we preserve the exact URL/routing for bookmarked pages?** Streamlit doesn't have traditional URLs, but `st.navigation` maintains page state. Redirects should handle this.

10. **Is there a preferred order for the phased rollout?** The plan proposes a specific order, but confirm if you want to prioritize certain merges first.

---

## 13. Summary of Page Count Reduction

| Phase | Pages Removed from Navigation | Pages Added | Net Change |
|-------|------------------------------|-------------|------------|
| Current | - | - | 13 active + 1 admin |
| After Phase 2 | Participants | - | 12 active + 1 admin |
| After Phase 3 | Rankings | - | 11 active + 1 admin |
| After Phase 4 | Tournament Setup | - | 10 active + 1 admin |
| After Phase 5 | Live Scoring, Voice Rules Chat | - | 8 active + 1 admin |
| After Phase 5 (dev tools hidden) | - | - | 5 active + 1 admin + 3 dev (hidden) |

**Final navigation for regular users: 5 pages (Dashboard, Events & Draws, Matches/Scorekeeper, AI Assistant, Public Board) + 1 admin page**

This is a **60% reduction** in visible navigation items for regular users, from 13 to 5, while preserving all functionality through tabs and feature flags.
