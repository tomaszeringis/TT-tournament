# Voice AI Implementation Plan: Phase 3 — Final Release
**Branch:** `ux-redesign-safe-pages`  
**Date:** 2026-07-10  
**Status:** Plan only — no code changes yet.

---

## 1. Executive Summary

**Phase 3 goal:** Expand from reliable voice scoring into operator assistance — voice navigation, tournament administration, rules/umpire assistant, and accessibility — without compromising official score integrity. All admin and navigation commands must be confirmation-gated. AI assistants remain read-only.

**Phase 4 goal:** Add downstream spectator experience — live commentary, match summaries, automatic announcements, and exportable reports — generated only from verified structured events. Commentary must never mutate official state.

**Final hardening goal:** Production-readiness pass — offline validation, weak-hardware testing, tournament-hall noise protocol, full regression suite, documentation, and rollback procedures.

**Deferred out of scope:**
- Video/highlight generation (requires stable scoring + event logging first).
- Cloud ASR as a required dependency (design-only adapter).
- Wake-word implementation (design-only unless a safe foundation already exists).
- SpeechBrain for production scoring (optional research-only).
- Large ASR/LLM fine-tuning.

---

## 2. Current Readiness Assessment

### 2.1 Phase 2 foundations — complete

| Component | Status |
|-----------|--------|
| `VoiceRuntimeState` dataclass + helpers | ✅ Created, tested |
| `VoiceCommandRouter` with `RouteContext` | ✅ Created, tested |
| `VoiceConfirmationStateMachine` | ✅ Created, tested |
| Vosk grammar ASR backend (`VoskGrammarASR`) | ✅ Created, factory-integrated |
| `AudioPipeline` module | ✅ Created |
| `VoiceMetrics` module | ✅ Created |
| Page imports for Phase 2 modules | ✅ Added to `voice_scorekeeper.py` |
| Full test suite | ✅ 711 passing |

### 2.2 Phase 2 foundations — partial / wiring needed

| Component | Gap | Blocker? |
|-----------|-----|----------|
| Router + confirmation wired into page | `route_and_update_context` is called, but old `policy_decision` + duplicate logic still present in `_process_voice_events` | No — dual path is safe but redundant |
| `VoiceRuntimeState` fully adopted | Only `migrate_from_session_state()` is called; page still reads/writes many `st.session_state` keys directly | No — bridge works |
| `VoiceConfirmationStateMachine` used by page | Instantiated and linked to confirm/cancel buttons, but `_process_voice_events` still uses old `pending_confirmations` list logic | No — both paths coexist |
| DB-backed audit log | `VoiceEventRepository` exists but page does not call it after every accepted event | No — in-memory `EventLogger` works, DB persistence is additive |
| `voice_panel` component | Does not exist | No — page still works inline |

### 2.3 Safe to extend

- **Parser (`commands.py`, `parse_result.py`)**: Already has extensible intent enum + regex patterns. New navigation/admin/accessibility intents can be added without changing the interface.
- **ScoreEngine (`score_engine.py`)**: Pure, deterministic, fully tested. No changes needed.
- **MatchManager (`match_manager.py`)**: Stable UI wrapper. No changes needed for Phase 3/4.
- **CommentaryService (`commentary_service.py`)**: Template-based, event-driven, no LLM. Ready for Phase 4.
- **AI/Rules stack**: `RulesRetriever`, `UmpireEngine`, `AIFacade` already exist and are read-only. Can be reused for Phase 3 rules assistant.
- **FastAPI routes**: Operator endpoints (`/api/operator/matches/{id}/call`, `start`, `complete`, etc.) already exist. Voice admin commands can call these via `ApiClient`.
- **Public board (`public_board.py`)**: Read-only, polls DB. Safe for Phase 4 spectator integration.
- **Event logs**: `EventLogger` (in-memory) + `VoiceEventRepository` (DB) + `VoiceEvent` model exist. Sufficient for Phase 4 summaries.

### 2.4 Risky areas

| Area | Risk | Mitigation |
|------|------|------------|
| `voice_scorekeeper.py` size (~2600 lines) | Regression during refactor | Incremental extraction; never remove inline code until component is proven |
| WebRTC session_state key stability | Rerun disrupts audio | Stable `webrtc_streamer` key; processor factory session-pinned |
| `VoiceService` (WebSocket path) | Separate from page path; could diverge | Keep page path as source of truth; WebSocket path can follow later |
| Existing `pending_confirmations` list vs `VoiceConfirmationStateMachine` | Two sources of truth | Phase 2 left both; Phase 3 should consolidate to state machine |
| ChromaDB / Ollama availability | Rules assistant depends on them | Feature-flag; graceful fallback to "rules unavailable" |
| Public board polling frequency | Voice scoring writes could cause missed updates | Eventual consistency is acceptable; add version/timestamp check |

---

## 3. Phase 3 — Advanced Voice Assistance

### 3.1 A. Voice Navigation

**New intents to add to `commands.py`:**
```python
NAVIGATE_DASHBOARD = "navigate_dashboard"
NAVIGATE_BRACKET = "navigate_bracket"
NAVIGATE_RANKINGS = "navigate_rankings"
NAVIGATE_PUBLIC_BOARD = "navigate_public_board"
NAVIGATE_CURRENT_MATCH = "navigate_current_match"
NAVIGATE_SCORING = "navigate_scoring"
NAVIGATE_HELP = "navigate_help"
```

**Patterns:**
- `"open dashboard"` → `NAVIGATE_DASHBOARD`
- `"show bracket"` / `"bracket"` → `NAVIGATE_BRACKET`
- `"show rankings"` / `"rankings"` → `NAVIGATE_RANKINGS`
- `"show public board"` / `"public board"` → `NAVIGATE_PUBLIC_BOARD`
- `"show current match"` / `"current match"` → `NAVIGATE_CURRENT_MATCH`
- `"back to scoring"` / `"scoring"` → `NAVIGATE_SCORING`
- `"show command help"` / `"voice help"` → `NAVIGATE_HELP`

**Safety layer — `NavigationCommandHandler`:**
- New module: `tournament_platform/app/services/voice/navigation.py`
- Methods:
  - `can_navigate(state: VoiceRuntimeState) -> bool` — returns False if pending confirmations exist or match is in progress with unsaved score
  - `execute(intent: VoiceIntent, context: Dict) -> str` — returns target page name or query param
- Navigation never mutates match state.
- If blocked, voice says: "Navigation blocked: pending confirmation. Cancel or confirm first."
- If risky (e.g., leaving page during active match), show Streamlit confirmation dialog.

**Files to create:**
- `tournament_platform/app/services/voice/navigation.py`

**Files to modify:**
- `tournament_platform/app/services/voice/commands.py` — add navigation intents + patterns
- `tournament_platform/app/services/voice/command_router.py` — add navigation routing decision
- `tournament_platform/app/pages/voice_scorekeeper.py` — import handler, wire into main loop

**Tests to add:**
- `tests/voice/test_navigation.py`:
  - `test_can_navigate_when_idle`
  - `test_can_navigate_blocked_by_pending_confirmation`
  - `test_can_navigate_blocked_by_active_match`
  - `test_execute_returns_correct_target`
  - `test_navigation_intents_parsed_correctly`

### 3.2 B. Voice Tournament Administration

**New intents:**
```python
ADMIN_CALL_NEXT = "admin_call_next"
ADMIN_TABLE_READY = "admin_table_ready"
ADMIN_ASSIGN_TABLE = "admin_assign_table"
ADMIN_MARK_UNAVAILABLE = "admin_mark_unavailable"
ADMIN_PUBLISH_RESULT = "admin_publish_result"
ADMIN_MARK_NO_SHOW = "admin_mark_no_show"
ADMIN_DROP_PLAYER = "admin_drop_player"
ADMIN_START_NEXT_ROUND = "admin_start_next_round"
```

**Handler — `AdminCommandHandler`:**
- New module: `tournament_platform/app/services/voice/admin.py`
- All methods require `VoiceConfirmationStateMachine` confirmation.
- Destructive commands (`DROP_PLAYER`, `MARK_NO_SHOW`, `PUBLISH_RESULT`) show explicit warning in confirmation card.
- Commands call existing `ApiClient` operator endpoints:
  - `ADMIN_CALL_NEXT` → `api_client.call_next_match(tournament_id)`
  - `ADMIN_TABLE_READY` → `api_client.update_table_status(table_id, "ready")`
  - `ADMIN_ASSIGN_TABLE` → `api_client.assign_table(match_id, table_id)`
  - `ADMIN_PUBLISH_RESULT` → `api_client.report_match(match_id, ...)`
- Every action is logged to `VoiceEventRepository` with `source="voice_admin"`.
- If API call fails, show error and do not retry.

**Files to create:**
- `tournament_platform/app/services/voice/admin.py`

**Files to modify:**
- `tournament_platform/app/services/voice/commands.py`
- `tournament_platform/app/services/voice/command_router.py`
- `tournament_platform/app/pages/voice_scorekeeper.py`

**Tests to add:**
- `tests/voice/test_admin_commands.py`:
  - `test_admin_call_next_requires_confirmation`
  - `test_admin_drop_player_requires_visual_warning`
  - `test_admin_publish_result_calls_api_client`
  - `test_admin_command_failure_shows_error`
  - `test_admin_commands_logged_to_audit`

### 3.3 C. Rules / Umpire Assistant

**Reuse existing stack:**
- `UmpireEngine` (`services/umpire_engine.py`) — already has `ask_rules_voice()` with RAG + streaming TTS.
- `AIFacade` (`services/ai_facade.py`) — has `answer_rules_question()`.
- `RulesRetriever` (`services/rules_retrieval.py`) — ChromaDB-based.
- FastAPI endpoint: `POST /api/rules/ask` already exists.

**New intent:**
```python
RULES_QUERY = "rules_query"
```

**Handler — `RulesAssistantHandler`:**
- New module: `tournament_platform/app/services/voice/rules_assistant.py`
- Method: `answer(transcript: str, match_context: Dict) -> str`
- Logic:
  1. If question is about current match (contains "serve", "score", "deuce"), answer from deterministic `MatchManager` state first.
  2. Otherwise, call existing `/api/rules/ask` via `ApiClient` or `AIFacade.answer_rules_question()`.
  3. Display answer in UI `st.info` box.
  4. Never call scoring endpoints.
  5. If ChromaDB/Ollama unavailable, show: "Rules assistant unavailable. Please consult the rulebook."

**Files to create:**
- `tournament_platform/app/services/voice/rules_assistant.py`

**Files to modify:**
- `tournament_platform/app/services/voice/commands.py`
- `tournament_platform/app/services/voice/command_router.py`

**Tests to add:**
- `tests/voice/test_rules_assistant.py`:
  - `test_rules_query_does_not_mutate_score`
  - `test_current_match_question_uses_deterministic_state`
  - `test_fallback_when_chromadb_unavailable`
  - `test_rules_query_parsed_correctly`

### 3.4 D. Accessibility Commands

**New intents:**
```python
ACCESS_REPEAT = "access_repeat"
ACCESS_ANNOUNCE_SCORE = "access_announce_score"
ACCESS_LOUDER = "access_louder"
ACCESS_QUIETER = "access_quieter"
ACCESS_MUTE = "access_mute"
ACCESS_UNMUTE = "access_unmute"
ACCESS_SLOWER = "access_slower"
ACCESS_FASTER = "access_faster"
ACCESS_LARGE_TEXT = "access_large_text"
ACCESS_HIGH_CONTRAST = "access_high_contrast"
ACCESS_HELP = "access_help"
```

**Handler — `AccessibilityCommandHandler`:**
- New module: `tournament_platform/app/services/voice/accessibility.py`
- Stores state in `VoiceRuntimeState`:
  - `accessibility_large_text: bool = False`
  - `accessibility_high_contrast: bool = False`
  - `accessibility_tts_volume: int = 100`
  - `accessibility_tts_rate: int = 150`
- `ACCESS_REPEAT` / `ACCESS_ANNOUNCE_SCORE` → triggers `TTSConfirmationAdapter.speak()` with current score.
- `ACCESS_MUTE` / `ACCESS_UNMUTE` → toggles `VoiceRuntimeState.commentary_muted`.
- `ACCESS_LOUDER` / `ACCESS_QUIETER` → adjusts volume by 10%.
- `ACCESS_SLOWER` / `ACCESS_FASTER` → adjusts TTS rate by 20%.
- `ACCESS_LARGE_TEXT` / `ACCESS_HIGH_CONTRAST` → sets Streamlit theme toggles (query params or `st.config` if available; otherwise session state flags consumed by CSS).

**Files to create:**
- `tournament_platform/app/services/voice/accessibility.py`

**Files to modify:**
- `tournament_platform/app/services/voice/commands.py`
- `tournament_platform/app/services/voice/command_router.py`
- `tournament_platform/app/components/voice_panel.py` (to expose accessibility toggles)

**Tests to add:**
- `tests/voice/test_accessibility.py`:
  - `test_mute_toggles_commentary_muted`
  - `test_louder_increases_volume`
  - `test_large_text_sets_flag`
  - `test_accessibility_commands_do_not_mutate_score`

### 3.5 E. Optional Wake-Word Plan (Design Only)

**Decision:** Do not implement in Phase 3. Document design constraints:

| Constraint | Rationale |
|------------|-----------|
| Opt-in only | Prevents surprise activation in tournament halls |
| Requires active match context | Avoids commands when no match is selected |
| Cannot execute risky commands directly | Wake word only activates listening or repeats last score |
| Separate lightweight thread | Must not block scoring path |
| False-positive guard | Require 2 detections within 500ms + active match context before activating |

**Possible implementations to evaluate later:**
- Porcupine (cloud validation, good accuracy, requires internet).
- Vosk keyword grammar (fully offline, lower accuracy).

**Action:** Add `VOICE_ENABLE_WAKE_WORD` and `VOICE_WAKE_WORD` settings placeholders. Add no code beyond config.

### 3.6 F. Multilingual Command Aliases

**Plan:**
- English is the primary language. All Phase 3 commands have English patterns.
- Lithuanian aliases are deferred until English tests are stable.
- Add a configurable alias file: `tournament_platform/data/voice_aliases.json` (new file, not a DB table).
- Format:
  ```json
  {
    "en": {
      "point red": ["point red", "red point"],
      "undo": ["undo", "take back"]
    },
    "lt": {
      "point red": ["taškas raudona", "raudona taškas"]
    }
  }
  ```
- `TranscriptPostProcessor` expands aliases before parsing.
- Every alias must have a corresponding test in `tests/test_voice_parser.py`.

**Files to create:**
- `tournament_platform/data/voice_aliases.json`
- `tournament_platform/app/services/voice/aliases.py`

**Files to modify:**
- `tournament_platform/app/services/voice_vocab.py` — load aliases
- `tournament_platform/app/services/voice/commands.py` — no changes needed if aliases are pre-expanded

**Tests to add:**
- `tests/voice/test_aliases.py`:
  - `test_lithuanian_alias_expands_to_english`
  - `test_unknown_alias_ignored`
  - `test_alias_does_not_break_existing_commands`

---

## 4. Phase 4 — Intelligent Commentary and Analytics

### 4.1 A. Match Summary Generation

**New service — `MatchSummaryService`:**
- New module: `tournament_platform/app/services/voice/match_summary.py`
- Input: `VoiceEventRepository.get_by_match(match_id)` + `Match` metadata.
- Output: Structured summary dict + optional LLM-phrased text.
- Deterministic facts extracted from event log:
  - Players, tournament, final score, game scores, winner, duration.
  - Milestones: deuce, game point, comeback (trailed by >= 5 and won).
- LLM phrasing (optional, feature-flagged `VOICE_ENABLE_LLM_SUMMARY`):
  - Prompt: "You are a table tennis commentator. Write a 2-3 sentence match summary using ONLY these facts: {facts}. Do not invent anything."
  - If LLM unavailable, fall back to template-based summary.
- Validation: `SummaryValidator` checks every fact in the generated text against the event log. Reject if mismatch.

**Files to create:**
- `tournament_platform/app/services/voice/match_summary.py`

**Files to modify:**
- `tournament_platform/app/pages/voice_scorekeeper.py` — add "Generate Summary" button
- `tournament_platform/app/components/voice_panel.py` — expose summary display

**Tests to add:**
- `tests/voice/test_match_summary.py`:
  - `test_summary_facts_match_event_log`
  - `test_llm_summary_falls_back_to_template_when_unavailable`
  - `test_summary_rejects_hallucinated_facts`

### 4.2 B. Live Statistics Narration

**Enhance `CommentaryService`:**
- Add new `ScoreMoment` values: `STREAK_A`, `STREAK_B`, `COMEBACK_A`, `COMEBACK_B`.
- Add throttling: minimum 5 seconds between identical narration lines.
- Trigger from `VoiceEventRepository` after every accepted event.
- Toggle in UI: `commentary_verbosity` controls frequency.

**Files to modify:**
- `tournament_platform/services/commentary_service.py` — add streak/comeback templates + throttling
- `tournament_platform/app/services/voice/event_log.py` — add `last_commentary_ts` for throttling

**Tests to add:**
- `tests/voice/test_commentary.py`:
  - `test_streak_commentary_after_three_points`
  - `test_commentary_throttled_within_five_seconds`

### 4.3 C. Automatic Player and Match Announcements

**New module — `AnnouncementService`:**
- `tournament_platform/app/services/voice/announcements.py`
- Sources: `Tournament` schedule, `Match` state, `VoiceEventRepository`.
- Events:
  - Match start: "Opening game between {A} and {B}."
  - Next match: "Next match on table {n}: {A} versus {B}."
  - Game won: "Game to {A}, {score}."
  - Match won: "{A} wins the match {sets} games to {sets}."
- Deduplication: track last announced event ID in `VoiceRuntimeState`.
- Pronunciation: use existing `format_player_label()` utility; if names contain special chars, warn operator.

**Files to create:**
- `tournament_platform/app/services/voice/announcements.py`

**Files to modify:**
- `tournament_platform/services/commentary_service.py` — integrate announcement lines
- `tournament_platform/app/pages/voice_scorekeeper.py` — add announcement toggle

**Tests to add:**
- `tests/voice/test_announcements.py`:
  - `test_no_duplicate_announcements`
  - `test_announcement_skipped_when_muted`

### 4.4 D. Commentary Style Presets

**Existing:** `CommentaryStyle` enum (`NEUTRAL`, `COACH`, `ANNOUNCER`, `MINIMAL`) and `CommentaryVerbosity` enum already exist in `commentary_service.py`.

**Enhancements:**
- Add `KIDS` style with friendlier language.
- Add `SILENT` verbosity (no spoken commentary, UI-only).
- Wire style selector into `voice_panel` component.
- Ensure style only affects wording, not match data.

**Files to modify:**
- `tournament_platform/services/commentary_service.py` — add `KIDS` templates
- `tournament_platform/app/components/voice_panel.py` — style selector UI

### 4.5 E. Exportable Match Report

**Format:** Markdown first. PDF only if existing repo already has safe PDF generation.

**Include:**
- Tournament name, match name, players, final score, game scores.
- Key events from `VoiceEventRepository`.
- Voice command audit summary (count, intents, confidence stats).
- Optional generated summary.
- Optional commentary transcript.
- Timestamp.

**New module — `MatchReportExporter`:**
- `tournament_platform/app/services/voice/report_exporter.py`
- Method: `export_match_report(match_id: int, include_summary: bool, include_commentary: bool) -> str`
- Returns Markdown string.

**Files to create:**
- `tournament_platform/app/services/voice/report_exporter.py`

**Files to modify:**
- `tournament_platform/app/pages/voice_scorekeeper.py` — add "Export Report" button
- `tournament_platform/app/components/voice_panel.py` — expose export action

**Tests to add:**
- `tests/voice/test_report_exporter.py`:
  - `test_export_contains_correct_score`
  - `test_export_excludes_debug_transcripts_by_default`
  - `test_export_includes_summary_when_requested`

### 4.6 F. Public Board / Spectator Mode Integration

**Requirements:**
- Public board already reads verified match state from DB. No structural changes needed.
- Add optional "Spectator Commentary" card that shows last 3 commentary lines.
- Commentary card is read-only and does not write to DB.
- Render throttle: public board `@st.cache_data(ttl=10)` already limits DB queries.

**Files to modify:**
- `tournament_platform/app/pages/public_board.py` — add optional commentary card
- `tournament_platform/app/components/voice_panel.py` — add spectator mode toggle

**Tests to add:**
- `tests/test_public_board.py` — ensure voice scoring does not break render
- `tests/voice/test_public_board_safety.py` — verify no DB writes from spectator view

### 4.7 G. Video/Highlight Plan (Deferred)

**Do not implement.** Document only:
- Event timestamps from `VoiceEvent.created_at` can seed highlight clips.
- Requires video timestamp synchronization and non-Streamlit video pipeline.
- Wait until scoring, commentary, and event logging are stable for at least one full tournament cycle.

---

## 5. Final Hardening and Release Plan

### 5.1 Validation checklist

| Category | Validation |
|----------|------------|
| **Test suite** | Run `python -m pytest tests/ -x` — target 0 failures |
| **Voice regression** | All `tests/test_voice_*.py` + new Phase 3/4 tests pass |
| **Parser regression** | Golden transcript tests + new navigation/admin/accessibility tests pass |
| **Router tests** | Route mapping, confirmation gating, duplicate suppression pass |
| **Admin safety** | No destructive command executes without confirmation (simulated UI test) |
| **Rules assistant** | Read-only tests confirm no state mutation |
| **Commentary factuality** | Summary validator catches hallucinations |
| **Public board sync** | Score update propagates within 10s (polling interval) |
| **Offline mode** | faster-whisper, Vosk, TTS, CommentaryService all work without network |
| **Weak hardware** | Vosk fallback activates when faster-whisper latency > 2000ms |
| **Browser mic** | Permission denied shows graceful degradation |
| **Tournament hall noise** | Noise gate + VAD reject chunks below threshold |
| **Manual fallback** | Manual +/- buttons work during voice scoring |
| **Undo/recovery** | 10-step undo restores full state |
| **`/api/report` compatibility** | Payload/response schema unchanged |
| **DB migration** | `alembic upgrade head` runs cleanly on fresh SQLite |
| **Admin maintenance** | Delete/reset actions in `admin.py` still work |
| **Documentation** | `VOICE_SCOREKEEPER.md`, `README.md`, `TROUBLESHOOTING.md` updated |
| **Dependencies** | New deps documented in `README.md` setup section |
| **Rollback** | Disable voice via `VOICE_ENABLE_CONFIRMATION=0`; manual fallback always works |

### 5.2 Documentation updates

| Document | Updates |
|----------|---------|
| `VOICE_SCOREKEEPER.md` | Architecture diagram, full command list (Phase 3/4), admin safety notes, offline setup |
| `README.md` | Voice setup instructions, hardware requirements, optional extras `[live,voice]` |
| `TROUBLESHOOTING.md` | Mic permissions, ASR latency, Vosk model download, ChromaDB setup for rules |
| `ARCHITECTURE.md` | Voice pipeline section, Phase 3/4 handlers |
| `docs/voice_hall_test_protocol.md` | Tournament hall testing checklist (Phase 2) |

### 5.3 Deployment notes

- **Local-first:** All dependencies work offline after initial install.
- **Model caching:** Document `~/.cache/huggingface/` for faster-whisper and `VOSK_MODEL_PATH` for Vosk.
- **Optional extras:** `pip install ".[live,voice]"` for full voice support.
- **Streamlit Cloud / Docker:** Pre-cache ASR models in image or startup script.
- **Environment flags:** Document all `VOICE_*` env vars.

### 5.4 Rollback instructions

| Failure mode | Rollback |
|--------------|----------|
| Voice scoring instability | `VOICE_ENABLE_CONFIRMATION=0` or disable voice toggle in UI |
| Page crash | Manual scoring buttons always visible and functional |
| DB migration failure | Alembic guards; app starts without new tables |
| Admin command misbehavior | Cancel button in confirmation card; no auto-apply |
| Rules assistant hallucination | Disable `VOICE_ENABLE_LLM_INTERPRETER`; fall back to rulebook |
| Commentary distraction | Mute toggle in UI |
| Public board break | Public board reads DB directly; no voice coupling |

---

## 6. Target Architecture (Phase 3–Final)

```
Verified match state / event log / voice_command_log
  ↓
VoiceCommandRouter
  ├── Scoring handlers (Phase 2) → ScoreEngine → MatchManager
  ├── NavigationCommandHandler (Phase 3) → safe page transitions
  ├── AdminCommandHandler + VoiceConfirmationStateMachine (Phase 3) → ApiClient
  ├── RulesAssistantHandler (Phase 3) → read-only AI facade
  ├── AccessibilityCommandHandler (Phase 3) → VoiceRuntimeState toggles
  ├── CommentaryService (Phase 4) → structured events → TTS
  ├── MatchSummaryService (Phase 4) → event log validation → export
  └── AnnouncementService (Phase 4) → verified state → TTS
  ↓
Streamlit UI / voice_panel / public board / export report
```

### 6.1 How Phase 3 handlers plug in

- Each handler is a stateless service with a `handle(intent, context) -> ActionResult` method.
- `VoiceCommandRouter` dispatches to handlers based on intent category.
- Handlers return `ActionResult` dataclass: `{ action: str, payload: dict, requires_confirmation: bool, risk: str }`.
- Risky actions enter `VoiceConfirmationStateMachine` before execution.

### 6.2 Risk management

- Navigation: blocked if `pending_confirmations` or `unsaved_changes` exist.
- Admin: all intents require confirmation; destructive intents show explicit warning.
- Rules: always read-only; deterministic answers preferred over LLM.
- Accessibility: no score impact; UI-state only.
- Commentary: downstream of accepted events only; throttled; muteable.

### 6.3 Public board data flow

- Public board queries DB for `Match` status + `VoiceEventRepository` for last commentary.
- Voice scoring writes to DB via existing `persist_voice_match_to_db()` + `VoiceEventRepository`.
- No direct coupling; eventual consistency is acceptable.

---

## 7. Data Model Plan

### 7.1 Current schema (sufficient for Phase 3/4)

| Table | Status | Notes |
|-------|--------|-------|
| `voice_events` | ✅ Exists (migration 010) | Reuse for all voice actions including admin/rules/accessibility |
| `voice_commands` | ✅ Exists | Dataset recorder; no changes needed |
| `matches` | ✅ Exists | Score persistence already works |
| `announcements` | ✅ Exists | Can be reused for match announcements |

### 7.2 New fields (no new tables needed)

| Table | Field | Purpose |
|-------|-------|---------|
| `voice_events` | `source` | Already exists; use values `asr`, `voice_admin`, `rules_query`, `accessibility` |
| `voice_events` | `action_taken` | Already exists; use for admin/rules outcomes |
| `voice_events` | `error_message` | Already exists; capture API failures |

### 7.3 No new tables

- `commentary_events`: reuse `voice_events` with `intent="commentary"`.
- `match_summaries`: generate on demand from event log; no persistent table needed.
- `announcement_preferences`: store in `VoiceRuntimeState` (session-only) or existing `Announcement` model.
- `accessibility_preferences`: session-only in `VoiceRuntimeState`.
- `command_aliases`: JSON file (`data/voice_aliases.json`), not DB table.
- `exported_reports`: on-demand generation; no persistent storage required.

### 7.4 Migration plan

| Phase | Migration | Risk |
|-------|-----------|------|
| Phase 3 | None | Low |
| Phase 4 | None | Low |
| Final | None | Low |

---

## 8. Dependency Plan

### 8.1 Existing dependencies (keep)

| Dependency | Purpose |
|------------|---------|
| `faster-whisper>=1.0.0` | Default ASR |
| `streamlit-webrtc>=0.45.0` | Continuous listening |
| `av>=12.0.0` | Audio resampling |
| `numpy>=1.24.0` | Audio arrays |
| `vosk>=0.3.45` | Grammar fallback ASR |
| `pyttsx3>=2.90` | Offline TTS |
| `speechbrain>=1.0.0` | Optional research ASR |

### 8.2 Dependencies to add

| Dependency | Purpose | Justification |
|------------|---------|---------------|
| None required | — | All Phase 3/4 features can be built with existing deps |

**Optional (feature-flagged, not required):**
- Existing `chromadb` + `ollama` stack — already in project for rules assistant. Keep optional.
- Existing `torch` + `torchaudio` — already in `[speech]` extra. Keep optional.

### 8.3 Dependencies to avoid

| Dependency | Reason |
|------------|--------|
| Cloud ASR SDKs | Violates local-first; design-only adapter |
| SpeechBrain for production | Too heavy; optional research only |
| Video/highlight deps | Out of scope until scoring stable |
| PDF generation deps | Markdown export sufficient for Phase 4 |
| New DB/storage systems | Existing SQLite + SQLAlchemy sufficient |

---

## 9. Test Plan

### 9.1 Phase 3 tests (~60 new tests)

| File | Tests | Focus |
|------|-------|-------|
| `tests/voice/test_navigation.py` | 8 | Route mapping, blocked navigation, safe transitions |
| `tests/voice/test_admin_commands.py` | 12 | Confirmation gating, API payload, audit log, destructive warnings |
| `tests/voice/test_rules_assistant.py` | 10 | Read-only, deterministic answers, ChromaDB fallback |
| `tests/voice/test_accessibility.py` | 10 | TTS toggles, volume, rate, UI flags, no score mutation |
| `tests/voice/test_aliases.py` | 8 | Lithuanian/English alias expansion, no breaking changes |
| `tests/test_voice_parser.py` | +20 | New Phase 3 intents in golden corpus |

### 9.2 Phase 4 tests (~40 new tests)

| File | Tests | Focus |
|------|-------|-------|
| `tests/voice/test_match_summary.py` | 10 | Factual consistency, LLM fallback, regenerate |
| `tests/voice/test_commentary.py` | 8 | Streaks, throttling, style presets |
| `tests/voice/test_announcements.py` | 8 | Deduplication, pronunciation, TTS toggle |
| `tests/voice/test_report_exporter.py` | 8 | Markdown accuracy, fact inclusion, debug exclusion |
| `tests/voice/test_public_board_safety.py` | 6 | No DB writes, stable render |

### 9.3 Final hardening tests

| Category | Tests |
|----------|-------|
| Full regression | Run entire `tests/` suite: target 0 failures |
| Offline mode | Mock network down; verify local deps work |
| Weak hardware | Mock slow ASR; verify UI does not freeze |
| Browser mic | Mock permission denied; verify graceful degradation |
| Tournament hall noise | Synthetic noisy audio; verify noise gate + VAD |
| Manual fallback | Disable voice; verify manual buttons work |
| Undo/recovery | 10-step undo; verify full state restore |
| Admin safety | Destructive commands require confirmation |
| `/api/report` | Payload/response unchanged |
| DB migration | Fresh `alembic upgrade head` |

---

## 10. Implementation Sequencing

### Step 1: Verify Phase 2 baseline
**Goal:** Confirm tests pass, syntax valid, modules importable.  
**Actions:** Run full test suite; verify `voice_scorekeeper.py` syntax; audit Phase 2 module coverage.  
**Acceptance:** 711 tests pass, no syntax errors.

### Step 2: Add Phase 3 intents to parser
**Goal:** Extend `VoiceIntent` enum, `_COMMAND_PATTERNS`, cheat sheet.  
**Files:** `tournament_platform/app/services/voice/commands.py`  
**Tests:** `tests/test_voice_parser.py` — add navigation/admin/rules/accessibility patterns to golden corpus.  
**Acceptance:** Parser recognizes all Phase 3 commands without breaking existing ones.

### Step 3: Create `NavigationCommandHandler`
**Goal:** Safe voice navigation with pending-confirmation guard.  
**Files:** Create `tournament_platform/app/services/voice/navigation.py`  
**Tests:** `tests/voice/test_navigation.py`  
**Acceptance:** Navigation blocked when confirmations pending; execute returns correct target.

### Step 4: Wire navigation into page
**Goal:** Router dispatches navigation intents; UI shows navigation confirmation.  
**Files:** `command_router.py`, `voice_scorekeeper.py`  
**Acceptance:** Voice navigation works from scorekeeper page; no disruption to active match.

### Step 5: Create `AdminCommandHandler`
**Goal:** Voice admin commands with confirmation + audit log.  
**Files:** Create `tournament_platform/app/services/voice/admin.py`  
**Tests:** `tests/voice/test_admin_commands.py`  
**Acceptance:** All admin commands show confirmation card; destructive commands show warning.

### Step 6: Wire admin into page + router
**Goal:** Admin intents routed through `AdminCommandHandler`.  
**Files:** `command_router.py`, `voice_scorekeeper.py`  
**Acceptance:** Admin commands call `ApiClient`; failures shown to user.

### Step 7: Add rules assistant handler
**Goal:** Read-only rules/umpire assistant.  
**Files:** Create `tournament_platform/app/services/voice/rules_assistant.py`  
**Tests:** `tests/voice/test_rules_assistant.py`  
**Acceptance:** Rules queries do not mutate state; deterministic answers preferred.

### Step 8: Add accessibility handler
**Goal:** Accessibility commands with session state.  
**Files:** Create `tournament_platform/app/services/voice/accessibility.py`  
**Tests:** `tests/voice/test_accessibility.py`  
**Acceptance:** Mute/larger text/slower work; score unchanged.

### Step 9: Add multilingual aliases
**Goal:** Configurable alias expansion.  
**Files:** Create `data/voice_aliases.json`, `tournament_platform/app/services/voice/aliases.py`  
**Tests:** `tests/voice/test_aliases.py`  
**Acceptance:** Lithuanian aliases expand correctly; English tests still pass.

### Step 10: Create `MatchSummaryService`
**Goal:** Factually consistent match summaries.  
**Files:** Create `tournament_platform/app/services/voice/match_summary.py`  
**Tests:** `tests/voice/test_match_summary.py`  
**Acceptance:** Summary facts validated against event log; hallucinations rejected.

### Step 11: Enhance commentary
**Goal:** Live narration + automatic announcements.  
**Files:** `tournament_platform/services/commentary_service.py`, create `announcements.py`  
**Tests:** `tests/voice/test_commentary.py`, `tests/voice/test_announcements.py`  
**Acceptance:** Throttled narration; deduplicated announcements; muteable.

### Step 12: Add export + public board integration
**Goal:** Exportable reports + spectator mode.  
**Files:** Create `report_exporter.py`; modify `public_board.py`  
**Tests:** `tests/voice/test_report_exporter.py`, `tests/voice/test_public_board_safety.py`  
**Acceptance:** Markdown export accurate; public board stable.

### Step 13: Final docs + hardening
**Goal:** Documentation + full regression.  
**Actions:** Update docs; run full suite; validate offline/weak-hardware scenarios.  
**Acceptance:** 0 test failures; docs updated; rollback instructions verified.

---

## 11. Acceptance Criteria

### Phase 3
- Admin commands never execute without confirmation.
- Voice navigation does not disrupt active scoring.
- Rules assistant cannot mutate official state.
- Accessibility commands work without affecting score.
- Misrecognition recovery remains easy (undo + cancel).
- Existing Phase 2 scoring remains stable.
- All existing tests pass.

### Phase 4
- Summaries are factually consistent with event log.
- Commentary never changes official score.
- TTS can be muted.
- Public board remains stable.
- Spectator mode does not distract operator.
- Exported match reports are accurate.
- Existing scoring/admin features remain stable.

### Final release
- Existing app functionality preserved.
- Voice scoring works offline.
- Manual scoring works if voice fails.
- Risky commands are confirmed.
- Admin commands are confirmed.
- AI assistant is read-only for official state.
- Commentary and summaries are event-log grounded.
- Public board remains stable.
- Audit log captures voice actions.
- Tests pass.
- New dependencies documented.
- Setup instructions clear.
- No hidden cloud dependency.
- No large unplanned refactors.

---

## 12. Risk Mitigation

| Risk | Severity | Likelihood | Mitigation | Test Coverage | Rollback |
|------|----------|------------|------------|--------------|----------|
| Admin command executes accidentally | Critical | Low | All admin commands require confirmation card; confirmation state machine | `test_admin_commands.py` | Cancel button; no auto-apply |
| Navigation loses unsaved state | High | Medium | Block navigation when pending confirmations exist | `test_navigation.py` | "Back to scoring" always available |
| LLM gives wrong rules advice | Medium | Medium | Rules assistant uses RAG; explicit "do not invent" prompt; deterministic answers preferred | `test_rules_assistant.py` | Disable `VOICE_ENABLE_LLM_INTERPRETER` |
| LLM hallucinates match summary | High | Medium | SummaryValidator checks every fact against event log | `test_match_summary.py` | Fall back to template summary |
| Commentary becomes distracting | Medium | Medium | Throttling (5s cooldown); mute toggle; verbosity levels | `test_commentary.py` | Mute toggle in UI |
| TTS annoys users | Medium | Medium | TTS optional; mute toggle; off by default | `test_accessibility.py` | Mute toggle |
| Wake-word false triggers | Medium | Low | Deferred; will require 2-detection guard + active match context | N/A | Disable wake-word toggle |
| Multilingual aliases create ambiguity | Medium | Medium | English primary; aliases configurable; one alias per intent | `test_aliases.py` | Fall back to English |
| Public board exposes private data | Medium | Low | Public board reads DB only; debug transcripts opt-in | `test_public_board_safety.py` | Disable debug mode |
| Exported report contains incorrect score | High | Low | Factual validation before export; source from event log | `test_report_exporter.py` | Regenerate button |
| DB migration breaks installs | Medium | Low | No new tables in Phase 3/4; additive only | `test_voice_event_repo.py` | Alembic downgrade path |
| Cloud dependency becomes required | High | Low | No cloud deps added; all features work offline | Offline test | Feature flags disable cloud paths |
| Manual fallback becomes harder | Medium | Low | Manual buttons always visible; never removed | Manual fallback test | Voice toggle disables voice path |

---

## 13. Open Questions / Blockers

None. All required services, models, and API routes already exist or are straightforward extensions of Phase 2 modules. The only material decision is whether to consolidate the dual `pending_confirmations` + `VoiceConfirmationStateMachine` paths in Phase 2 cleanup before Phase 3 — recommended but not blocking.
