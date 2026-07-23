# 🏗️ Tournament Platform - Technical Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tournament Platform v2.0                      │
└─────────────────────────────────────────────────────────────────┘
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
          ┌──────▼─────┐   ┌──▼────────┐  ┌▼──────────────┐
          │  Frontend   │   │   API     │  │  AI Engine   │
          │ (Streamlit) │   │ (FastAPI) │  │ (Ollama)     │
          └─────┬──────┘   └──┬────────┘  └┬──────────────┘
                │            │             │
          HTTP │            │ Async I/O   │
             ┌─┴──────────────┴─────────────┴─┐
             │   Database Layer               │
             │   • SQLAlchemy ORM             │
             │   • Alembic Migrations         │
             │   • SQLite / PostgreSQL        │
             └─────────────────────────────────┘
```

## Technology Stack (Source of Truth: pyproject.toml)

| Layer | Component | Technology | Version |
|-------|-----------|-----------|---------|
| Frontend | UI Framework | Streamlit | >=1.58.0 |
| | Tables | streamlit-aggrid | >=0.1.0 |
| | Charts | Plotly | >=5.18.0 |
| | Auth | streamlit-authenticator | ==0.3.2 |
| | WebRTC | streamlit-webrtc | >=0.75,<0.76 |
| | Video | av | >=12.0.0 |
| | Audio | pyaudio (optional) | >=0.2.11 |
| API | Server | FastAPI | >=0.137.1 |
| | ASGI | Uvicorn | (via FastAPI) |
| | HTTP Client | requests | >=2.31.0 |
| Database | ORM | SQLAlchemy | >=2.0.51 |
| | Migrations | Alembic | >=1.18.4 |
| | Database | SQLite / PostgreSQL | - |
| AI | LLM | Ollama | >=0.6.2 |
| | Knowledge Base | ChromaDB | >=1.5.9 |
| | Validation | Pydantic | >=2.13.4 |
| | Voice | faster-whisper | >=1.0.0 |
| | Speech | speechrecognition | >=3.10.0 |
| | TTS | pyttsx3 | >=2.90 |
| | RAG | langchain-community | >=0.2.0 |

---

## 1. Frontend Layer (Streamlit)

### Architecture: Multi-Page Modular Design

```
app/
├── main.py                  ← Entry point with auth & navigation
├── pages/
│   ├── dashboard.py         ← Analytics & visualization
│   ├── tournament_setup.py   ← Configuration & reporting
│   ├── voice_scorekeeper.py ← Voice-activated scoring
│   └── admin.py             ← System administration
└── config.yaml              ← Authentication config
```

### Key Technologies:
- **Streamlit >=1.58.0**: Web framework
- **st.navigation**: Multi-page routing
- **AG-Grid**: Advanced data tables
- **Plotly**: Interactive charts
- **streamlit-authenticator**: Authentication
- **streamlit-webrtc**: WebRTC audio/video capture

### Data Flow:
```
User Input → Streamlit UI → HTTP Request → FastAPI → Database
```

---

## 2. Voice Pipeline Architecture

### Architecture: Three-Mode Voice Input

```
Input Source (push-to-talk / continuous / debug)
    ↓
TranscriptPostProcessor (normalize + vocabulary)
    ↓
VoiceCommandGrammar (parse → VoiceParseResult)
    ↓
RouteContext (duplicate suppression, confidence, policy)
    ↓
RouteDecision: REJECT | IGNORE | CONFIRM | APPLY
    ↓
MatchManager.apply_voice_event()
    ↓
ScoreEngine (pure rules)
    ↓
Streamlit UI (session state + rerun)
```

### Voice Modes

| Mode | Capture | Status |
|------|---------|--------|
| **Push-to-Talk** | `st.audio_input` (main thread) | **Recommended** |
| **Full Voice Commands** | `st.audio_input` or WebRTC | Stable |
| **Quick Voice Scoring** | `st.audio_input` (color-word regex) | Stable |
| **Continuous Listening** | `streamlit-webrtc` (background threads) | **Experimental** |

### Input Modes

- **Push-to-talk**: Uses `st.audio_input`. Audio is processed on the main Streamlit thread via `_process_push_to_talk_audio()`.
- **Continuous listening**: Uses `streamlit-webrtc` with `VoiceAudioProcessor`. Audio callbacks run in a WebRTC background thread and write to thread-safe queues.
- **Debug**: Uses a text input to feed transcripts directly into `_process_voice_transcript()` on the main thread.

### Shared Transcript Processor

All modes converge on `VoiceCommandGrammar.parse()` which returns a `VoiceParseResult` with `intent`, `slots`, `confidence`, and `safety_level`.

### Parser / Router / Confirmation Flow

1. **Parse**: `VoiceCommandGrammar` matches the transcript against 40+ intent patterns.
2. **Route**: `CommandRouter` evaluates `RouteContext` for duplicate suppression, confidence thresholds, and confirmation policies.
3. **Decide**: `RouteDecision` is one of `REJECT`, `CONFIRM`, `APPLY`, or `IGNORE`.
4. **Confirm**: If `CONFIRM`, the action is enqueued for the confirmation panel.
5. **Apply**: If `APPLY`, `MatchManager.apply_voice_event()` executes through `ScoreEngine`.

### MatchManager / ScoreEngine Official Scoring Path

Score updates never mutate official state directly from LLMs or unbranched callbacks:

```
VoiceParseResult
    ↓
CommandRouter.route() → RouteDecision.APPLY
    ↓
MatchManager.apply_voice_event()
    ↓
ScoreEngine (pure rules: serve, deuce, win-by-2, best-of)
    ↓
Streamlit UI (session state + rerun)
```

### Voice Audit Events

All voice events are logged to a bounded ring buffer (`EventLogger`, max 1000 events). Events include:
- `source`: `debug`, `push_to_talk`, `continuous`
- `accepted`: bool
- `confidence`: float
- `previous_score` / `new_score`: string
- `note`: rejection reason or duplicate suppression flag

### Continuous WebRTC Audio-Frame Pipeline

```
WebRTC AudioFrame
    ↓
_audio_frame_callback_func() (background thread)
    ↓
_module-level globals under lock (_audio_callback_count, _last_audio_frame_*)
    ↓
Main thread drains queues (_chunk_queue, event_queue)
    ↓
VoiceAudioBuffer (VAD + noise gating + resampling)
    ↓
LocalASR.transcribe_chunk() (module-level cache)
    ↓
event_queue → _process_voice_events()
```

### One-Shot Rerun Strategy

- `_process_voice_events()` no longer calls `st.rerun()` directly.
- `_maybe_voice_rerun()` requests `st.rerun()` once after applying an event, drained at the end of `_render_ui()`.
- `_maybe_voice_heartbeat()` runs in the main thread with adaptive timing (250ms draining / 1000ms idle) to clear the event queue without conflicting rerun calls.

### Thread-Safety Rules

- **Audio callbacks must not call Streamlit APIs directly.** They write to thread-safe queues.
- **Audio callbacks update module-level globals** (`_audio_callback_count`, `_last_audio_frame_*`) under a lock.
- **Diagnostics are read on the main thread**, not from the callback thread.
- **Official score updates happen in the main Streamlit loop** via `_process_voice_events()` and `apply_score_event_and_refresh_ui()`.

### Session State Keys / Runtime State Object

`VoiceRuntimeState` (`tournament_platform/app/services/voice/runtime_state.py`) is a dataclass that centralizes voice scorekeeper state. It provides `get_state()`, `set_state()`, `reset_state()`, `migrate_from_session_state()`, and `sync_legacy_keys()`.

**Dual state sources**: The page reads from both `VoiceRuntimeState` (via `get_state()`) and legacy scattered keys (e.g., `st.session_state.voice_webrtc_streamer_state`). `sync_legacy_keys()` writes back after every state mutation.

### Duplicate / Stale Event Prevention

Events carry `session_id` and `timestamp`. The processor sets `_session_id` from `voice_continuous_session_id` after WebRTC play starts. Stale events are dropped if:
- The event `session_id` does not match the current session
- The event timestamp is before the session start or after the last stop
- The event ID has already been applied (duplicate suppression)
- WebRTC is not playing

Duplicates are suppressed within 1.2s cooldown. Game boundaries automatically reset the cooldown.

### Streamlit Rerun / State Model

- The WebRTC component key (`voice_scorekeeper_continuous_webrtc`) and `_WEBRTC_AUDIO_CONSTRAINTS` must remain stable across reruns or `streamlit-webrtc` resets the component.
- `WEBRTC_AVAILABLE` is computed once at import time via `detect_webrtc_available()`. It can only change on process restart.

---

## 3. API Layer (FastAPI)

### Architecture: RESTful Async API

```python
FastAPI Server
├── Endpoints
│   ├── POST /api/report          ← Async match reporting
│   └── GET /api/tournaments/{id}/matches/active ← Active matches
├── Middleware
│   ├── Exception Handler         ← Global error handling
│   ├── Logging                   ← Request/response logging
│   └── CORS                      ← Cross-origin support
└── Dependencies
    └── Database Session          ← Dependency injection
```

### Key Features:
- **Async/Await**: Non-blocking I/O
- **Dependency Injection**: Clean database session management
- **Exception Handling**: Global error handler with logging
- **Async HTTP Client**: httpx for external API calls
- **Structured Logging**: File and console logging

### Request Flow:
```
Request → Validation → DB Dependency → Processing → Response → Logging
```

---

## 4. Database Layer

### Architecture: SQLAlchemy ORM + Alembic Migrations

```
Data Models
├── Player
│   ├── id (PK)
│   ├── name
│   ├── email
│   └── rating
├── Tournament
│   ├── id (PK)
│   ├── name
│   ├── description
│   ├── created_at
│   └── matches (1→N)
└── Match
    ├── id (PK)
    ├── player1
    ├── player2
    ├── winner
    ├── score
    ├── status (Enum)
    ├── tournament_id (FK)
    └── scheduled_time
```

### Migration System:
```
Model Change
    ↓
alembic revision --autogenerate
    ↓
Review migration file
    ↓
alembic upgrade head
    ↓
Database Updated
```

### Current Migration:
- **001_initial.py**: Creates Player, Tournament, Match tables

---

## 5. AI Engine Layer

### Architecture: RAG + Structured Output

```
Match Data
    ↓
┌─────────────────────┐
│  RAG System         │
│ ┌──────────────┐    │
│ │ ChromaDB     │    │
│ │ (Knowledge   │    │
│ │  Base)       │    │
│ └──────────────┘    │
└─────────────────────┘
    ↓ (Top 3 Rules)
┌─────────────────────┐
│ Ollama LLM          │
│ (JSON Mode)         │
└─────────────────────┘
    ↓
Pydantic MatchReport
├── summary
├── key_play
└── predicted_winner
```

### Components:

**1. MatchReport (Pydantic Model)**
```python
class MatchReport(BaseModel):
    summary: str
    key_play: str
    predicted_winner: str
```

**2. RAG System (ChromaDB)**
- Stores tournament rules
- Retrieves relevant context
- Embeds rules and queries

**3. Ollama Integration**
- JSON mode enforcement
- Local LLM processing
- Structured responses

### Data Flow:
```
Match Data + Query → Retrieve Rules → Prompt Engineering →
Ollama JSON Mode → Parse Response → Return MatchReport
```

---

## 6. ASR Backend Design

### Pluggable Backend Architecture

`ASRBackendFactory` selects and instantiates ASR backends based on configuration:

```python
name = backend_name or os.environ.get("VOICE_ASR_BACKEND", "faster_whisper").lower().strip()
```

If the primary backend fails, the factory falls back to `VOICE_ASR_FALLBACK_BACKEND`.

### Shared Model Cache

`LocalASR` instances share a module-level model cache keyed by `(model_size, device, compute_type)`:

```python
_ASR_MODEL_CACHE: dict = {}
_ASR_CACHE_LOCK = threading.Lock()
```

This ensures the model is loaded only once per unique configuration.

### Supported Backends

| Backend | Package | Config |
|---------|---------|--------|
| `faster_whisper` | `faster-whisper`, `ctranslate2`, `onnxruntime` | `VOICE_ASR_MODEL_SIZE`, `VOICE_ASR_DEVICE`, `VOICE_ASR_COMPUTE_TYPE` |
| `speechbrain` | `speechbrain`, `torch`, `torchaudio` | `VOICE_SPEECHBRAIN_MODEL_SOURCE` |
| `vosk` | `vosk` | `VOICE_ASR_VOSK_MODEL_PATH` |

---

## 7. Complete Request Flow

### Scenario: Report a Match Result

```
1. FRONTEND (Streamlit)
   └─ User fills form and submits
   
2. HTTP REQUEST
   └─ POST /api/report
   └─ JSON: {player1, player2, score, winner, tournament_id}

3. API (FastAPI)
   ├─ Validate request
   ├─ Get DB session (Dependency Injection)
   └─ Create Match record

4. DATABASE (SQLAlchemy)
   ├─ Insert into matches table
   ├─ Set status to "completed"
   └─ Commit transaction

5. NOTIFICATION
   ├─ Format Teams message
   ├─ Async HTTP call to webhook
   └─ Fire and forget

6. RESPONSE
   └─ Return success JSON to Streamlit

7. LOGGING
   └─ Write request/response to logs/app.log

8. FRONTEND
   └─ Display success message
```

---

## 8. Data Relationships

### Entity-Relationship Diagram

```
┌──────────────┐
│   Player     │
├──────────────┤
│ id (PK)      │
│ name         │
│ email        │
│ rating       │
└──────────────┘
       ▲
       │
    (1:N)
       │
       └─── belongs to ───┐
                           │
                      ┌────▼──────────┐
                      │    Match       │
                      ├────────────────┤
                      │ id (PK)        │
                      │ player1        │
                      │ player2        │
                      │ winner         │
                      │ score          │
                      │ status (Enum)  │
                      │ tournament_id  │
                      │ (FK) ──┐       │
                      │        │       │
                      └────────┼───────┘
                               │
                          (1:N)│
                               │
                      ┌────────▼────────┐
                      │  Tournament     │
                      ├─────────────────┤
                      │ id (PK)         │
                      │ name            │
                      │ description     │
                      │ created_at      │
                      └─────────────────┘
```

---

## 9. Deployment Architecture

### Development Setup
```
localhost:8501 ← Streamlit
localhost:8000 ← FastAPI

Both connect to local SQLite
```

### Production Setup
```
                     ┌─────────────────┐
                     │  Load Balancer  │
                     └────────┬────────┘
                              │
                 ┌────────────┼────────────┐
                 │            │            │
           ┌─────▼──┐   ┌─────▼────┐  ┌──▼──────┐
           │Streamlit│   │ FastAPI  │  │ FastAPI │
           │Instance │   │ Instance │  │Instance │
           └─────┬──┘   └─────┬────┘  └┬──────┘
                 │            │          │
                 └────────────┬──────────┘
                              │
                       ┌──────▼──────┐
                       │ PostgreSQL  │
                       │ (Production)│
                       └─────────────┘
```

---

## 10. Error Handling Flow

```
Exception Occurs
    ↓
Global Exception Handler (@app.exception_handler)
    ↓
├─ Log Error (logs/app.log)
├─ Format Error Response
└─ Return JSON with Details
    ↓
Frontend Displays Error Message
```

### Exception Types Handled:
- **HTTPException**: 400/500 errors
- **JSONDecodeError**: Invalid JSON
- **DatabaseError**: SQL issues
- **ValueError**: Business logic errors
- **Generic Exception**: Catch-all

---

## 11. Logging Architecture

### Three-Level Logging:

```
1. FILE (/logs/app.log)
   └─ Production logs for analysis

2. CONSOLE
   └─ Real-time development feedback

3. STRUCTURED LOGGING
   └─ Format: timestamp | level | module | message
```

### Log Levels:
- **DEBUG**: Detailed development info
- **INFO**: General information flows
- **WARNING**: Warning messages
- **ERROR**: Error conditions
- **CRITICAL**: Critical failures

---

## 12. Dependency Graph

```
Streamlit Frontend
    ↓
requests → FastAPI Server
            ↓
        SQLAlchemy ORM
           ↓
        SQLite / PostgreSQL
        
AI Engine
    ↓
Ollama (Local LLM)
ChromaDB (Knowledge Base)
    ↓
Pydantic Models (Structured Output)
```

---

## 13. Performance Considerations

### Database Optimization:
- Indexes on frequently queried columns
- Connection pooling
- Pagination for large datasets
- Query optimization

### Frontend Optimization:
- Lazy loading of data
- Caching strategies
- Pagination in AG-Grid
- Minimal re-renders

### API Optimization:
- Async processing
- Write operations go to database
- Read operations use caching
- Connection pooling

### AI Optimization:
- Local Ollama (no network latency)
- ChromaDB for cached embeddings
- Batch rule loading
- JSON mode prevents parsing overhead
- Module-level ASR model cache prevents duplicate loads

---

## 14. Security Considerations

### Frontend:
- ✅ Authentication with config.yaml
- ✅ Session management
- ✅ Input validation

### API:
- ✅ Request validation (Pydantic)
- ✅ Error messages don't leak internals
- ✅ Logging for audit trail
- ✅ CORS configuration

### Database:
- ✅ SQL injection prevention (ORM)
- ✅ Connection pooling
- ✅ Transaction safety

### Production:
- ⚠️ Use HTTPS/SSL
- ⚠️ Add authentication tokens
- ⚠️ Use environment variables
- ⚠️ Rate limiting

---

## 15. Scalability Path

### Phase 1: Current (SQLite)
- Single server
- Development/testing
- ~100 concurrent users

### Phase 2: PostgreSQL + Multiple API Instances
- Replace SQLite with PostgreSQL
- Multiple FastAPI instances
- Load balancer
- ~1000 concurrent users

### Phase 3: Distributed System
- Separate Streamlit, API, Database servers
- Redis for caching
- Kubernetes orchestration
- ~10,000 concurrent users

---

## 16. Key Design Patterns

### 1. Dependency Injection
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/api/report")
async def endpoint(db: Session = Depends(get_db)):
    pass
```

### 2. Async/Await
```python
@app.post("/api/report")
async def report_match(request: Request):
    data = await request.json()
    async with httpx.AsyncClient() as client:
        await client.post(url, json=data)
```

### 3. Pydantic Validation
```python
class MatchReport(BaseModel):
    summary: str
    key_play: str
    predicted_winner: str
```

### 4. Repository Pattern (ORM)
```python
db.query(Match).filter(Match.status == "completed")
db.add(new_match)
db.commit()
```

### 5. Thread-Safe State Isolation
```python
# Audio callbacks write to module-level globals under a lock
with _audio_callback_lock:
    _audio_callback_count += 1

# Main thread drains queues and updates Streamlit state
for event in iter(event_queue.get_nowait, None):
    _process_voice_event(event)
```

---

## 📚 References

- [FastAPI Architecture](https://fastapi.tiangolo.com/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/)
- [Alembic Migrations](https://alembic.sqlalchemy.org/)
- [Streamlit Architecture](https://docs.streamlit.io/)
- [RAG Pattern](https://docs.trychroma.com/)
- [Streamlit WebRTC](https://github.com/whitphx/streamlit-webrtc)

---

**Last Updated:** July 22, 2026  
**Architecture Version:** 2.1
