# Voice Scorekeeper and Sports Commentary Implementation Plan

## A. Current-State Findings

### Existing Voice Capture Path
- **Streamlit Audio Input**: `st.audio_input` in `voice_scorekeeper.py` captures audio
- **Audio Format**: WAV format (handled by Streamlit), 16kHz sample rate (per `config/__init__.py` `AUDIO_RATE=16000`)
- **Transcription**: `UmpireEngine.transcribe_audio_file()` uses faster-whisper locally
- **TTS**: Two options available:
  - `pyttsx3` (offline, Python-based) in `speak_text()`
  - Browser-native SpeechSynthesis in `spoken_commentary.py`

### Existing ASR Path
- **Primary**: `UmpireEngine` with faster-whisper model (base size by default)
- **Alternative**: `speech_service.py` exists but not used in main flow
- **Vosk adapter**: `vosk_adapter.py` available as alternative
- **Local-first**: All transcription happens locally, no cloud APIs

### Existing Intent Classification Path
- **Location**: `tournament_platform/multimodal_ai/intent_classifier.py`
- **Method**: Regex pattern matching (deterministic, no ML training required)
- **Current Intents**:
  - `SCORE_UPDATE` - score/point/game/set patterns
  - `COACHING_QUERY` - technique/tip/analyze patterns
  - `SESSION_CONTROL` - start/stop/session patterns
  - `PLAYER_INFO` - who/what/player patterns
  - `UNKNOWN` - fallback
- **Missing**: No `MATCH_RESULT` intent for "Alice beat Bob 3-1" patterns

### Existing Score Update Path
- **Location**: `MatchManager.update_score()` in `match_manager.py`
- **Method**: Keyword matching (simple, rule-based)
- **Features**:
  - Point scoring for Player A/B
  - Undo last point
  - Score query
  - Match history tracking
- **Limitations**:
  - No match result parsing (e.g., "Alice beat Bob 3-1")
  - No server change detection
  - No explicit game point/deuce detection in command path

### Existing Match Parse/Submit Path
- **Parse Endpoint**: `/api/match/parse` in `server.py` (read-only, no DB writes)
- **Parser**: `match_parser.py` with deterministic fallback + optional AI
- **Patterns**: "X beat Y score", "X defeated Y score", "X wins over Y score"
- **Submit Endpoint**: `/api/report` (separate, writes to DB)
- **Good**: Clear separation between parse and submit

### Existing Commentary Modules
- **CommentaryService**: `tournament_platform/services/commentary_service.py` (EXISTS)
  - Deterministic template-based generation
  - No LLM required, no network calls
  - Supports: POINT_A, POINT_B, UNDO, DEUCE, ADVANTAGE, GAME_POINT, GAME_WON, MATCH_WON, RESET
- **SpokenCommentary**: `tournament_platform/app/components/spoken_commentary.py` (EXISTS)
  - Browser-native SpeechSynthesis
  - No network calls, works offline
- **Integration**: Already integrated in `voice_scorekeeper.py`

### Import/Runtime Risks
- **UmpireEngine**: Requires `pyaudio`, `faster-whisper`, `ollama`, `RealtimeTTS` - may fail if not installed
- **CommentaryService**: Already imported and used
- **SpokenCommentary**: Already imported and used
- **No missing imports** - all required modules exist

---

## B. Proposed File Changes

### 1. `tournament_platform/multimodal_ai/intent_classifier.py`
**Purpose**: Add table-tennis specific intent types and improve entity extraction
**Key Changes**:
- Add `MATCH_RESULT` intent type
- Add `SCORE_QUERY` intent type (separate from SCORE_UPDATE)
- Add `UNDO` and `RESET` as explicit intent types
- Add `SERVER_CHANGE` intent type
- Improve player name extraction patterns
- Add `match_score` slot for "3-1" format extraction

**Risk Level**: LOW - additive changes, backward compatible
**Tests Needed**: `tests/test_multimodal/test_intent_classifier_table_tennis.py`

### 2. `tournament_platform/services/match_manager.py`
**Purpose**: Add structured event generation and improve command handling
**Key Changes**:
- Add `VoiceEvent` dataclass for structured events
- Add `generate_event()` method that returns events instead of just strings
- Add `parse_match_result()` method for "Alice beat Bob 3-1" patterns
- Add `server_change()` method
- Add `reset_match()` to return events

**Risk Level**: MEDIUM - modifies core scoring logic
**Tests Needed**: `tests/test_voice_event_schema.py`

### 3. `tournament_platform/services/voice_event_schema.py` (NEW)
**Purpose**: Define normalized event schema for table-tennis events
**Key Classes**:
- `VoiceEvent` - Pydantic model for all voice events
- `EventType` - Enum for event types
- `EventFactory` - Factory for creating events

**Risk Level**: LOW - new file, no breaking changes
**Tests Needed**: `tests/test_voice_event_schema.py`

### 4. `tournament_platform/services/voice_command_dataset.py` (NEW)
**Purpose**: Define command patterns and training data for intent classifier
**Key Classes**:
- `CommandPattern` - Pattern definition with examples
- `CommandDataset` - Collection of patterns for each intent

**Risk Level**: LOW - new file, no breaking changes
**Tests Needed**: `tests/test_voice_command_dataset.py`

### 5. `tournament_platform/services/commentary_service.py`
**Purpose**: Minor improvements to event handling
**Key Changes**:
- Add `SERVER_CHANGE` to `ScoreMoment` enum
- Add templates for server change events
- Add `generate_event_commentary()` method for VoiceEvent input

**Risk Level**: LOW - additive changes
**Tests Needed**: `tests/test_multimodal/test_commentary_service.py`

### 6. `tournament_platform/app/pages/voice_scorekeeper.py`
**Purpose**: Integrate new intent types and event schema
**Key Changes**:
- Update `process_voice_command()` to handle new intents
- Add match result parsing flow
- Add server change handling
- Ensure commentary is called with proper events

**Risk Level**: MEDIUM - modifies main page logic
**Tests Needed**: `tests/test_multimodal/test_voice_scorekeeper.py`

---

## C. Recommended New Modules

### `tournament_platform/services/voice_event_schema.py`
```python
# Event types for structured voice events
class EventType(str, Enum):
    POINT_WON = "point_won"
    GAME_WON = "game_won"
    MATCH_SUBMITTED = "match_submitted"
    UNDO = "undo"
    RESET = "reset"
    SERVER_CHANGE = "server_change"
    DEUCE = "deuce"
    GAME_POINT = "game_point"
    MATCH_POINT = "match_point"
    SCORE_QUERY = "score_query"
    MATCH_RESULT = "match_result"

# Pydantic model for events
class VoiceEvent(BaseModel):
    event_id: str
    event_type: EventType
    timestamp: datetime
    match_id: Optional[int]
    tournament_id: Optional[int]
    player: Optional[str]
    opponent: Optional[str]
    score_before: str
    score_after: str
    game_number: int
    confidence: float
    source_transcript: str
    entities: Dict[str, Any]
    requires_confirmation: bool = False
```

### `tournament_platform/services/voice_command_dataset.py`
```python
# Command patterns for training/improving intent classifier
COMMAND_PATTERNS = {
    "score_update": [...],
    "score_query": ["what's the score", "current score", ...],
    "undo": ["undo", "take back", "remove point", ...],
    "reset": ["reset", "start over", "new match", ...],
    "match_result": ["beat", "defeated", "wins over", ...],
    "server_change": ["server", "serve", "change ends", ...],
}
```

---

## D. Event Schema Design

```
VoiceEvent
├── event_id: UUID (unique identifier)
├── event_type: EventType enum
├── timestamp: datetime (when event occurred)
├── match_id: Optional[int] (database match ID)
├── tournament_id: Optional[int] (database tournament ID)
├── player: Optional[str] (player name or "A"/"B")
├── opponent: Optional[str] (opponent name)
├── score_before: str (e.g., "5-3")
├── score_after: str (e.g., "6-3")
├── game_number: int (current game, 1-indexed)
├── confidence: float (0.0-1.0)
├── source_transcript: str (original voice text)
├── entities: Dict (extracted slots)
│   ├── player: str
│   ├── opponent: str
│   ├── score: str
│   ├── game_score: str
│   ├── match_score: str
│   ├── stroke_type: str
│   ├── action: str
│   └── server: str
└── requires_confirmation: bool (for match result submission)
```

---

## E. Intent/Slot Taxonomy

### Intent Types
| Intent | Description | Examples |
|--------|-------------|----------|
| `score_update` | Point scoring | "Point to Alice", "Player A scores" |
| `score_query` | Score inquiry | "What's the score?", "Show me the score" |
| `undo` | Revert last point | "Undo", "Take that back" |
| `reset` | Reset match | "Reset", "Start over" |
| `coaching_query` | Technique advice | "How to improve backhand?" |
| `match_result` | Match result | "Alice beat Bob 3-1" |
| `session_control` | Session start/stop | "Start match", "End session" |
| `player_info` | Player information | "Who is Alice?" |
| `server_change` | Server/serve changes | "Server change", "Alice serves" |
| `unknown` | Unrecognized | - |

### Slots
| Slot | Description | Extraction Method |
|------|-------------|-------------------|
| `player` | Player name | Regex: `player\s+(\w+)` or name matching |
| `opponent` | Opponent name | From match context or "beat X" patterns |
| `score` | Game score | Regex: `(\d+)[-\s](\d+)` |
| `game_score` | Individual game score | From "11-5" format |
| `match_score` | Full match score | From "3-1" format (games) |
| `stroke_type` | Stroke type | Regex: backhand/forehand/serve/etc |
| `action` | Action verb | start/stop/undo/reset |
| `server` | Server indicator | "Alice serves", "server change" |
| `confidence` | Classification confidence | From intent classifier |

---

## F. Commentary Architecture

```
┌─────────────────┐
│ Voice Transcript  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ IntentClassifier│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ MatchManager    │───► VoiceEvent (structured)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CommentaryService│
│ (deterministic) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CommentaryLine  │
│ (text + meta)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ speak_commentary│
│ (browser TTS)   │
└─────────────────┘
```

**Key Principles**:
1. Commentary is **side-effect-light** - does not mutate score state
2. Commentary can be **disabled** via settings
3. Commentary is **deterministic** - no LLM required
4. Commentary uses **structured events** as input, not raw transcripts

---

## G. Testing Plan

### Unit Tests Required

1. **Score Command Classification** (`test_intent_classifier_table_tennis.py`)
   - Test "Point to Alice" → SCORE_UPDATE
   - Test "What's the score?" → SCORE_QUERY
   - Test "Undo last point" → UNDO
   - Test "Reset match" → RESET
   - Test "Alice beat Bob 3-1" → MATCH_RESULT

2. **Player/Entity Extraction** (`test_intent_classifier_table_tennis.py`)
   - Test player name extraction from various formats
   - Test score extraction (digit and word forms)
   - Test match score extraction (e.g., "3-1")

3. **Score-State Transitions** (`test_voice_event_schema.py`)
   - Test point addition events
   - Test game completion detection
   - Test match completion detection
   - Test undo event generation

4. **Undo/Reset Event Generation** (`test_voice_event_schema.py`)
   - Test undo creates proper event
   - Test reset creates proper event
   - Test history is preserved

5. **Event-to-Commentary Generation** (`test_commentary_service.py`)
   - Test POINT_A event generates correct commentary
   - Test DEUCE event generates correct commentary
   - Test UNDO event generates correct commentary
   - Test disabled commentary returns empty

6. **Missing Commentary Import Safety** (`test_voice_scorekeeper_imports.py`)
   - Test graceful fallback if CommentaryService unavailable
   - Test graceful fallback if speak_commentary unavailable

7. **No DB Write During Parse** (`test_api_client.py` or new)
   - Verify `/api/match/parse` does not write to database
   - Test parse returns proper structure

8. **Temporary Audio Cleanup** (`test_voice_scorekeeper.py`)
   - Test temp files are cleaned up
   - Test KEEP_AUDIO_FILES flag works

---

## H. Implementation Phases

### Phase 1: Branch/Import Smoke Fixes
- [ ] Verify all imports work correctly
- [ ] Run existing tests to establish baseline
- [ ] Create smoke test for voice_scorekeeper imports

### Phase 2: Event Schema and Command Taxonomy
- [ ] Create `voice_event_schema.py` with VoiceEvent model
- [ ] Create `voice_command_dataset.py` with patterns
- [ ] Add new intent types to `intent_classifier.py`
- [ ] Add unit tests for new schemas

### Phase 3: Intent Classifier Improvements
- [ ] Add MATCH_RESULT intent patterns
- [ ] Add SCORE_QUERY intent patterns
- [ ] Add UNDO/RESET as explicit intents
- [ ] Add SERVER_CHANGE intent patterns
- [ ] Improve entity extraction for table-tennis
- [ ] Add rule-first fallback (already exists, enhance)

### Phase 4: Structured Commentary Service
- [ ] Add SERVER_CHANGE to ScoreMoment enum
- [ ] Add templates for server change
- [ ] Add `generate_event_commentary()` method
- [ ] Ensure commentary doesn't mutate state

### Phase 5: Streamlit Integration
- [ ] Update `process_voice_command()` for new intents
- [ ] Add match result parsing flow
- [ ] Add server change handling
- [ ] Add confirmation step for match results
- [ ] Ensure feature flags work

### Phase 6: Tests, Latency Checks, and Cleanup
- [ ] Run all tests
- [ ] Add latency tests for transcription
- [ ] Add integration tests
- [ ] Clean up temp audio files
- [ ] Document changes

---

## I. Acceptance Criteria

The implementation is complete when:

- [ ] **Existing app launches** - `streamlit run tournament_platform/app/main.py` works
- [ ] **Voice scorekeeper page imports successfully** - No import errors
- [ ] **Voice score commands still work** - "Point to Player A" updates score
- [ ] **Match parse/confirm/submit remains separated** - `/api/match/parse` is read-only
- [ ] **Commentary can be disabled** - Toggle works, no speech when disabled
- [ ] **No cloud dependency introduced** - All processing local
- [ ] **Tests cover new schema and commentary logic** - >80% coverage for new code
- [ ] **No copyrighted dataset ingestion** - Only synthetic/deterministic patterns
- [ ] **Audio format is mono, 16kHz, WAV** - Per config settings
- [ ] **All new intents are deterministic** - No LLM required for basic operation

---

## J. Risks and Rollback Strategy

### High-Risk Changes
1. **MatchManager modifications** - Core scoring logic
   - **Mitigation**: Keep changes additive, use feature flag
   - **Rollback**: Revert to keyword-based matching

2. **Intent classifier changes** - Could break existing commands
   - **Mitigation**: Add patterns, don't remove existing ones
   - **Rollback**: Revert to original patterns

### Medium-Risk Changes
1. **Commentary service templates** - Could affect user experience
   - **Mitigation**: Test all template combinations
   - **Rollback**: Revert to original templates

2. **Streamlit page integration** - Could break UI
   - **Mitigation**: Test in isolation first
   - **Rollback**: Revert page changes

### Low-Risk Changes
1. **New schema files** - No impact on existing code
2. **New test files** - No impact on runtime
3. **Pattern additions** - Backward compatible

### Rollback Procedure
1. `git checkout HEAD -- tournament_platform/services/match_manager.py`
2. `git checkout HEAD -- tournament_platform/multimodal_ai/intent_classifier.py`
3. `git checkout HEAD -- tournament_platform/app/pages/voice_scorekeeper.py`
4. Remove new files: `rm tournament_platform/services/voice_event_schema.py`
5. Run tests to verify rollback