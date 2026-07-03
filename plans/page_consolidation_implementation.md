# Page Consolidation Implementation Plan

## 1. Proposed Final Navigation Structure

```
Home (🏠)
├── Getting Started - Welcome, quick actions, setup checklist, recent tournaments

Setup (⚙️)
├── Events & Draws (🏆) - Tournament creation wizard, participants, brackets, standings
│   ├── Tab: Create Tournament (wizard)
│   ├── Tab: Participants (player management)
│   ├── Tab: Active Tournaments (list + bracket view)
│   └── Tab: Standings (round-robin/group standings)
└── Player Profile (👤) - Individual player view

Tournament Day (🎮)
├── Match Center (🎛️) - Match operations, table status, voice commands
│   ├── Tab: Match Queue (call, start, complete actions)
│   ├── Tab: Table Status (table management)
│   └── Tab: Voice Commands (operator voice input)
├── Public Board (📺) - Read-only public view
├── Schedule (📅) - Calendar view of matches
└── Voice Scorekeeper (🔊) - Voice-based match scoring
    ├── Tab: Live Scoring (voice input)
    └── Tab: Match Selection (select active match)

Insights (📊)
├── Dashboard (📊) - Overview, metrics, recent/upcoming matches, AI insights
│   ├── Tab: Overview (metrics, players, matches)
│   ├── Tab: Rankings (leaderboard)
│   ├── Tab: Recent Results
│   └── Tab: Upcoming Matches
└── AI Assistant (🤖) - AI Q&A (Experimental)
    ├── Tab: Tournament Assistant
    └── Tab: Rules Q&A

Admin (👨‍💼)
└── Admin (👨‍💼) - System admin, maintenance, diagnostics
    ├── Tab: Database Overview
    ├── Tab: Match Management
    ├── Tab: System Health
    └── Tab: Danger Zone

Experimental (🧪) - Hidden by default (DEBUG_UI_ENABLED)
├── Video Scorekeeper (🎥)
├── Dataset Catalog (📊)
├── Coaching Lab (🏓)
└── Experiment Dashboard (🧪)
```

## 2. Page Mapping Table

| Current Page | New Location | Action | Notes |
|-------------|--------------|--------|-------|
| `home.py` | Home/Home | Keep | Already implemented |
| `participants.py` | **REMOVE** | Delete | Redirect wrapper, functionality in Events & Draws |
| `rankings.py` | **REMOVE** | Delete | Redirect wrapper, functionality in Dashboard |
| `events_draws.py` | Setup/Events & Draws | Keep + Tabs | Add Participants tab, organize with tabs |
| `player_profile.py` | Setup/Player Profile | Keep | Move to Setup section |
| `operator_console.py` | Tournament Day/Match Center | Keep + Tabs | Rename, add tabs for organization |
| `public_board.py` | Tournament Day/Public Board | Keep | Keep as-is |
| `schedule_board.py` | Tournament Day/Schedule | Keep | Keep as-is |
| `voice_scorekeeper.py` | Tournament Day/Voice Scorekeeper | Keep + Tabs | Add tabs for organization |
| `ai_assistant.py` | Insights/AI Assistant | Keep + Label | Add "Experimental" label |
| `admin.py` | Admin/Admin | Keep + Tabs | Already has tabs, keep as-is |
| `video_scorekeeper.py` | Experimental | Hide | Move to experimental section |
| `dataset_catalog.py` | Experimental | Hide | Already hidden |
| `coaching_lab.py` | Experimental | Hide | Already hidden |
| `experiment_dashboard.py` | Experimental | Hide | Already hidden |

## 3. File-by-File Change List

### Files to Delete (after verification)
- `tournament_platform/app/pages/participants.py` - Redirect wrapper
- `tournament_platform/app/pages/rankings.py` - Redirect wrapper

### Files to Modify

#### 1. `tournament_platform/app/main.py`
- Remove `participants.py` from navigation
- Remove `rankings.py` from navigation
- Reorganize into 4 main sections: Home, Setup, Tournament Day, Insights, Admin
- Keep experimental pages behind `DEBUG_UI_ENABLED`

**Current structure (lines 66-116):**
```python
# Section 1: Home
home_pages = [...]

# Section 2: Setup
setup_pages = [
    st.Page(..., "Events & Draws", ...),
    st.Page(..., "Rankings", ...),  # REMOVE
    st.Page(..., "Player Profile", ...),
]

# Section 3: Tournament Day
tournament_day_pages = [
    st.Page(..., "Public Board", ...),
    st.Page(..., "Match Center", ...),
    st.Page(..., "Schedule", ...),
    st.Page(..., "Voice Scorekeeper", ...),
]

# Section 4: Insights
insights_pages = [
    st.Page(..., "Dashboard", ...),
    st.Page(..., "AI Assistant", ...),
]
```

#### 2. `tournament_platform/app/pages/events_draws.py`
- Add `st.tabs` for: Create Tournament, Participants, Active Tournaments, Standings
- Move `render_tournament_creation_wizard()` to "Create Tournament" tab
- Add `render_participants_panel()` to "Participants" tab
- Move bracket/standings rendering to appropriate tabs

**Proposed structure:**
```python
def render_events_draws():
    st.title("🏆 Events & Draws")
    
    tabs = st.tabs(["Create Tournament", "Participants", "Active Tournaments", "Standings"])
    
    with tabs[0]:
        render_tournament_creation_wizard()
    
    with tabs[1]:
        render_participants_panel()
    
    with tabs[2]:
        # Active tournaments list + bracket view
    
    with tabs[3]:
        # Standings view
```

#### 3. `tournament_platform/app/pages/operator_console.py`
- Add `st.tabs` for: Match Queue, Table Status, Voice Commands
- Keep all existing functionality

**Proposed structure:**
```python
def render_match_center():
    st.title("🎛️ Match Center")
    
    tabs = st.tabs(["Match Queue", "Table Status", "Voice Commands"])
    
    with tabs[0]:
        # Match queue rendering
    
    with tabs[1]:
        # Table status rendering
    
    with tabs[2]:
        # Voice commands rendering
```

#### 4. `tournament_platform/app/pages/voice_scorekeeper.py`
- Add `st.tabs` for: Live Scoring, Match Selection
- Keep all existing voice/AI functionality

**Proposed structure:**
```python
def render_voice_scorekeeper():
    st.title("🔊 Voice Scorekeeper")
    
    tabs = st.tabs(["Live Scoring", "Match Selection"])
    
    with tabs[0]:
        # Voice input and scoring
    
    with tabs[1]:
        # Match selection
```

#### 5. `tournament_platform/app/pages/ai_assistant.py`
- Add "Experimental" label to title
- Keep existing tabs (Tournament Assistant, Rules Q&A)

**Change:**
```python
st.title("🤖 AI Assistant (Experimental)")
st.caption("Ask tournament, rules, ranking, schedule, and operations questions. (Experimental feature)")
```

## 4. Session State Compatibility

The following session state keys must be preserved:
- `ai_assistant_messages` - AI chat history
- `ai_rules_messages` - Rules Q&A history
- `ai_rules_last_answer` - Last rules answer
- `ai_rules_pending_question` - Pending question
- `ai_feedback` - AI feedback
- `match_manager` - Match state management
- `umpire_engine` - Voice transcription engine
- `intent_classifier` - Intent classification
- `coaching_service` - Coaching feedback
- `voice_rules_audio_hash` - Voice audio hash
- `last_audio_hash` - Audio processing guard
- `last_feedback` - Feedback message
- `realtime_mode` - Real-time mode state
- `listening` - Listening state
- `audio_level` - Audio level
- `voice_selected_tournament_id` - Voice scorekeeper selections
- `voice_selected_match_id` - Voice match ID
- `voice_selected_player1_id/name` - Player 1 selection
- `voice_selected_player2_id/name` - Player 2 selection
- `voice_match_options` - Match options
- `voice_parsed_result` - Parsed result
- `voice_score_input` - Score input
- `commentary_*` - Commentary settings
- `wizard_step` - Tournament creation wizard step
- `tournament_name/desc/format/participants/seeding` - Tournament wizard state
- `num_groups/qualifiers_per_group/swiss_rounds` - Format-specific settings
- `operator_tournament_select` - Operator console tournament
- `kiosk_mode` - Public board kiosk mode

## 5. Implementation Sequence

1. **Phase 1**: Update `main.py` navigation (safe, no functionality changes)
2. **Phase 2**: Add tabs to `events_draws.py` (consolidate participants)
3. **Phase 3**: Add tabs to `operator_console.py` (organize match center)
4. **Phase 4**: Add tabs to `voice_scorekeeper.py` (organize scoring)
5. **Phase 5**: Add "Experimental" label to `ai_assistant.py`
6. **Phase 6**: Delete redirect pages after verification
7. **Phase 7**: Run tests and verify all functionality

## 6. Risk Mitigation

- All changes are additive (tabs) or organizational (navigation)
- No database schema changes required
- Session state keys preserved
- Old pages kept as redirect wrappers until verification complete
- Tests run after each phase

## 7. Test Verification Checklist

- [ ] Navigation shows 4 main sections: Home, Setup, Tournament Day, Insights, Admin
- [ ] Participants page removed from navigation
- [ ] Rankings page removed from navigation
- [ ] Events & Draws has tabs for Create Tournament, Participants, Active Tournaments, Standings
- [ ] Match Center has tabs for Match Queue, Table Status, Voice Commands
- [ ] Voice Scorekeeper has tabs for Live Scoring, Match Selection
- [ ] AI Assistant has "Experimental" label
- [ ] All existing functionality preserved
- [ ] Session state survives navigation
- [ ] No obsolete page is the only place where a feature exists