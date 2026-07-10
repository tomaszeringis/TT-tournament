# Voice AI Improvements — TT Tournament (Implementation Plan)

> Branch reviewed: `ux-redesign-safe-pages` · Repo root: `tournament_platform/`
>
> **Important finding:** The codebase is far more mature than the brief assumes.
> Items 2, 5, and 9 of the brief are *largely already implemented* (a reusable
> `VoiceService`, an `ASRBackend` abstraction + factory already wired to
> `VOICE_ASR_BACKEND`/`VOICE_ASR_FALLBACK_BACKEND`, and a grounded LLM interpreter
> that never mutates score). This plan therefore focuses on the **genuine gaps**
> and refines what exists. It does NOT rebuild working components.

## 0. What already exists (do not rebuild)

| Brief item | Status in repo | File(s) |
|---|---|---|
| Local faster-whisper ASR | ✅ Done | `app/services/voice_asr.py` (`LocalASR`, lazy load, env config) |
| ASR backend interface + factory | ✅ Done | `app/services/asr_backends/{base,factory,faster_whisper_backend,speechbrain_backend}.py` |
| WebRTC audio buffering | ✅ Done | `app/services/voice_audio.py` (`VoiceAudioBuffer`, `AudioChunk`) |
| Deterministic parser | ✅ Done (partial) | `app/services/voice_parser.py` (`VoiceParser`) — grammar incomplete, see §7 |
| TTS / commentary | ✅ Done | `app/services/voice_tts.py`, `services/commentary_service.py`, `app/components/spoken_commentary.py` |
| Reusable voice service | ✅ Done | `app/services/voice_service.py` (stateless, no Streamlit dep) |
| Grounded LLM interpreter | ✅ Done | `app/services/voice_llm.py` (proposes only; `MatchManager` validates) |
| In-memory event log / audit | ✅ Done (volatil)e | `app/services/voice_audit.py` (`EventLogger` ring buffer) |
| Pydantic `VoiceEvent` schema | ✅ Done | `services/voice_event_schema.py` |
| Noise profiler / gate | ✅ Done | `app/services/voice_noise.py` |
| Vocabulary / post-processing | ✅ Done | `app/services/voice_vocab.py` |
| Speaker tagger (opt-in) | ✅ Done | `app/services/voice_speaker.py` |
| Match manager / umpire | ✅ Done | `services/match_manager.py`, `services/umpire_engine.py` |

## 1. Repository architecture findings

**Voice data flow today**

```
Browser mic
  → streamlit-webrtc (SENDONLY)            [app/pages/voice_scorekeeper.py: VoiceAudioProcessor]
  → VoiceAudioBuffer (amplitude VAD)       [app/services/voice_audio.py]
  → VoiceAudioProcessor._transcribe_chunk  (background thread)
        → ASRBackend.transcribe_pcm        [asr_backends/faster_whisper_backend.py]
        → TranscriptPostProcessor.process  [app/services/voice_vocab.py]
        → VoiceParser.parse                [app/services/voice_parser.py]
        → queue.Queue (event_queue)        (thread-safe)
  → _process_voice_events()                [main Streamlit thread: voice_scorekeeper.py:511]
        → MatchManager.apply_voice_event
        → TTS confirmation (if enabled)
        → in-memory EventLogger + voice_event_log (session state)
        → persist_voice_match_to_db        (writes Match.score / status)
```

**Tightly coupled / should be refactored**
- `voice_scorekeeper.py` is ~2080 lines. WebRTC processor class, commentary helpers,
  match selector, scoreboard, report form, and event loop all live in the page.
- Session-state mutation happens inside the `_process_voice_events()` rerun loop;
  if the page is ever re-imported, state wiring is fragile.
- Confirmation is *flagged* (`requires_confirmation`, `VOICE_STRICT_MODE`) but **never
  actually confirmed** — the page auto-applies the event whether or not it needs
  confirmation (voice_scorekeeper.py:615-638). This is the biggest safety gap.

**Gaps vs. the brief**
- **No DB persistence** of voice events — only Pydantic `VoiceEvent` schema + in-memory `EventLogger`. `models.py` has no `VoiceEvent`/`VoiceCommand` table.
- **No real confirmation/cancel UI** — strict mode sets a flag but scoring proceeds.
- **VAD is amplitude-only** (`VoiceAudioBuffer` RMS threshold); no Silero/WebRTC VAD.
- **Command grammar incomplete** — parser handles `set_score`/`increment`/`undo`/`deuce`/`all` only. Missing: start/pause/resume/next-game/end-game/timeout/server-check/set-server/confirm/cancel/repeat-score.
- **Push-to-talk is a stub** — `🎙️ Push to Talk` button just sets `listening=True` (voice_scorekeeper.py:1750); there is no `st.audio_input` widget wired to the pipeline.
- **Dataset recorder** (`services/voice_command_dataset.py`) only holds static regex patterns/examples — no runtime capture, correction labels, or export-to-disk.
- **Single-operator, single-match scope** — one `st.session_state.match_manager` + `voice_webrtc_ctx`; multi-court sessions are intentionally out of scope (§13).
- **Missing ASR config vars** in `services/settings.py`: `VOICE_ASR_MODEL_SIZE`, `VOICE_ASR_DEVICE`, `VOICE_ASR_COMPUTE_TYPE` exist in `voice_asr.py` env reads but are not centralized as feature flags.

## 2. Target architecture (future)

```
Browser microphone
  ├─ st.audio_input (push-to-talk, MVP / fallback)   ─┐
  └─ streamlit-webrtc (real-time, mature)           ─┤
        ↓ frames
   VoiceAudioBuffer ──(Silero/WebRTC VAD)── chunks    ← vad.py (new)
        ↓ pcm bytes (thread-safe queue)
   ASRBackend.transcribe_pcm        (faster_whisper default; Vosk/Picovoice/… future)
        ↓ text
   TranscriptPostProcessor (vocabulary)
        ↓
   VoiceParser (commands.py grammar) → VoiceParseResult
        ↓
   Confirmation policy (confirmation.py) → auto-apply | needs-confirm | reject
        ↓ (if allowed)
   MatchManager.apply_voice_event  (rules/umpire validation)
        ↓
   VoiceEvent persisted (event_log.py → SQLAlchemy VoiceEvent)  ⨯ NEW
        ↓
   UI panels (components/voice_panel.py …) + TTS + scoreboard
   AI commentary/umpire assistant reads match EVENT LOG only (never mutates score)
```

UI owns session interaction only. All scoring truth lives in `MatchManager`; all
observability lives in persisted `VoiceEvent`s.

## 3. Proposed modules and files

New or modified files (keep existing module names where they already exist):

**New**
- `app/services/voice/commands.py` — canonical intent enum + grammar (replaces ad-hoc `VoiceParser` patterns; see §7).
- `app/services/voice/parse_result.py` — `VoiceParseResult` dataclass (intent, slots, confidence, safety_level, requires_confirmation).
- `app/services/voice/confirmation.py` — `ConfirmationPolicy` (centralizes auto-apply vs confirm vs reject rules; see §8).
- `app/services/voice/vad.py` — `VoiceActivityDetector` wrapping Silero VAD / webrtcvad, with amplitude fallback.
- `app/services/voice/event_log.py` — `VoiceEventRepository` persisting `VoiceEvent` to SQLAlchemy (replaces in-memory only).
- `app/services/voice/dataset_recorder.py` — opt-in recorder (transcript, parsed intent, expected intent, match ctx, mic type, noise); no audio by default.
- `app/components/voice_panel.py` — scoreboard + transcript + parsed + confidence + confirm/cancel + undo + event history.
- `app/components/mic_calibration.py` — noise meter, mic test mode, threshold recommendation (reuses `voice_noise.NoiseProfiler`).
- `app/components/voice_event_log.py` — persisted-event history viewer + export.

**Modified**
- `models.py` — add `VoiceEvent`, `VoiceCommand` SQLAlchemy models (§4) + new alembic revision.
- `services/settings.py` — add `VOICE_ASR_MODEL_SIZE/DEVICE/COMPUTE_TYPE`, `VOICE_ENABLE_CONFIRMATION`, `VOICE_DATASET_OPT_IN`.
- `app/services/voice_parser.py` — delegate to `commands.py`; keep `VoiceScoreEvent` for back-compat but produce `VoiceParseResult`.
- `app/services/voice_service.py` — add `confirm_event`, `persist_event`, `record_dataset_sample`.
- `app/services/asr_backends/base.py` — add optional `supports_streaming`/`vad_hint` hooks (non-breaking).
- `app/pages/voice_scorekeeper.py` — slim down: import components; add `st.audio_input` push-to-talk; wire confirmation panel; remove inline event loop logic into service/component.
- `api/server.py` — add endpoints in §5.

**Keep as-is (do not touch):** `voice_asr.py`, `asr_backends/factory.py`, `faster_whisper_backend.py`, `speechbrain_backend.py`, `voice_vocab.py`, `voice_tts.py`, `voice_noise.py`, `voice_audit.py`, `voice_speaker.py`, `voice_llm.py`, `commentary_service.py`, `match_manager.py`, `umpire_engine.py`.

### 3.1 Wire-type compatibility decision (critical)

`services/match_manager.py:252` `apply_voice_event(event: VoiceScoreEvent)` is the
authoritative scoring funnel and is used by scoreboard buttons, undo, reset, and the
WebRTC loop. **Do not change its signature.** Therefore:

- `VoiceScoreEvent` (dataclass in `voice_parser.py`) remains the *wire type* that
  `MatchManager` consumes. Keep it.
- `voice/commands.py` (new) produces `VoiceParseResult` (intent + slots +
  confidence + safety_level + requires_confirmation). It exposes `.to_score_event()`
  that returns a `VoiceScoreEvent`, so existing `MatchManager` / `VoiceService` code
  keeps working unchanged.
- The existing `VoiceParser.parse(...)` stays as a thin wrapper that builds a
  `VoiceScoreEvent` from a `VoiceParseResult`, preserving backward compatibility for
  any external callers (tests, report flow at voice_scorekeeper.py:1823-1840).

## 4. Data model plan

Add to `models.py` (auto-created via `Base.metadata.create_all` at models.py:464 for dev, **plus** an alembic revision `0xx_add_voice_events.py` for prod parity).

```python
class VoiceEvent(Base):
    __tablename__ = "voice_events"
    id               = Column(Integer, primary_key=True)
    match_id         = Column(Integer, ForeignKey("matches.id"), index=True, nullable=True)
    intent           = Column(String, index=True)            # from commands.py
    raw_transcript   = Column(Text)
    normalized_text  = Column(Text)
    parsed_slots     = Column(Text)                          # JSON of slots
    confidence       = Column(Float, default=0.0)
    asr_latency_ms   = Column(Float, nullable=True)
    noise_rms        = Column(Float, nullable=True)
    score_before     = Column(String)                        # "5-3"
    score_after      = Column(String)
    status           = Column(String)                        # accepted|rejected|corrected|undone|pending_confirm
    disposition      = Column(String, nullable=True)         # why (noise_rejected, duplicate, low_conf)
    source           = Column(String, default="asr")         # asr|llm|manual
    speaker_label    = Column(String, nullable=True)
    created_at       = Column(DateTime, default=utcnow)
    undone_by        = Column(Integer, ForeignKey("voice_events.id"), nullable=True)  # links undo chain

class VoiceCommand(Base):
    __tablename__ = "voice_commands"      # dataset recorder samples (opt-in)
    id             = Column(Integer, primary_key=True)
    match_id       = Column(Integer, ForeignKey("matches.id"), index=True, nullable=True)
    transcript     = Column(Text)
    parsed_intent  = Column(String, nullable=True)
    expected_intent= Column(String, nullable=True)
    matched        = Column(Boolean, nullable=True)
    correction     = Column(String, nullable=True)           # operator correction label
    match_context  = Column(Text, nullable=True)            # JSON snapshot
    mic_type       = Column(String, nullable=True)
    noise_condition= Column(String, nullable=True)
    audio_stored   = Column(Boolean, default=False)         # NEVER store audio unless true
    created_at     = Column(DateTime, default=utcnow)
```

Relationships: `VoiceEvent 1—? undo VoiceEvent` (self-link via `undone_by`).
Persist via a `VoiceEventRepository` (sessionmaker-bound), called from `VoiceService`
so UI/pipeline stay stateless. Single-operator, single-match scope — **no per-table
sessions** (see §13).

## 5. API and service plan

Both direct service calls (Streamlit) **and** FastAPI endpoints (future PWA/WebSocket)
share the same `VoiceService` + `MatchManager`. Add endpoints to `api/server.py`:

- `POST /api/voice/transcribe` — `{audio_b64, match_id}` → `{text, latency_ms}`
- `POST /api/voice/parse` — `{text, match_id}` → `VoiceParseResult` (intent, slots, requires_confirmation)
- `POST /api/matches/{match_id}/voice-events` — apply a parsed voice event (Go/No-Go via `ConfirmationPolicy`); persists `VoiceEvent`; returns new score.
- `GET /api/matches/{match_id}/voice-events` — history for the event log panel.
- `POST /api/voice/confirm` — confirm a `pending_confirm` event (used by confirm/cancel panel).
- `POST /api/voice/dataset-samples` — append an opt-in dataset sample.

All state-changing routes still funnel through `MatchManager`; none call the LLM to write score.

## 6. Streamlit UI plan (`voice_scorekeeper.py` refactor)

Replace the 2000-line page with thin orchestration + `app/components/*`:
- **Active backend status** — `ASRBackendFactory.backend_status()` chip (already fetched at :1583).
- **Push-to-talk recorder** — `st.audio_input` → `VoiceService.transcribe_audio` → `process_transcript` → confirmation panel. Safest MVP path.
- **Optional real-time mode** — keep `webrtc_streamer` `VoiceAudioProcessor`; do NOT auto-apply — route through confirmation panel instead of auto-apply.
- **Transcript panel** — `last_voice_raw_transcript` + `last_voice_transcript`.
- **Parsed command panel** — intent + slots + safety level.
- **Confidence indicator** — color bar from `VoiceParseResult.confidence`.
- **Confirmation / cancel panel** — appears when `requires_confirmation`; `✅ Confirm` / `✖ Cancel`. (NEW — addresses biggest gap.)
- **Undo button** — always available after any state-changing voice command; one-click undo of last `VoiceEvent`.
- **Event history** — `voice_event_log.py` reading persisted `VoiceEvent`s (not just session-state list).
- **Microphone calibration widget** — `mic_calibration.py` (noise meter, mic test, threshold recommender from `NoiseProfiler`).
- **Command cheat sheet** — generated from `commands.py` grammar (single source of truth).
- **Manual fallback controls** — +/− buttons, score entry (keep existing).

## 7. Command grammar plan (in `voice/commands.py`)

Intents (extend `VoiceParser`):

| Intent | Example utterances | Required slots | Optional | Safety | Confirmation |
|---|---|---|---|---|---|
| `score_point` | "point to player one", "blue", "player A scores" | player | — | simple | auto if conf≥0.85 & not strict |
| `set_score` | "set score seven five", "ten eight" | score_a, score_b | — | medium | **required** |
| `undo` | "undo", "take that back" | — | — | safe | none (always available) |
| `repeat_score` | "what's the score?", "repeat score" | — | — | read-only | none |
| `start_match` | "start match", "begin" | — | — | medium | required |
| `pause_match` | "pause", "timeout break" | — | — | medium | required |
| `resume_match` | "resume", "continue" | — | — | medium | required |
| `start_next_game` | "next game", "new game" | — | — | medium | required |
| `end_game` | "end game", "game over" | — | — | medium | required |
| `timeout_start` | "timeout", "time out" | side? | — | medium | required |
| `timeout_end` | "end timeout", "resume play" | — | — | medium | required |
| `server_check` | "who serves?", "server?" | — | — | read-only | none |
| `set_server` | "player one serves", "server is blue" | player | — | medium | required |
| `confirm` | "confirm", "yes", "accept" | — | — | control | appliqué pending |
| `cancel` | "cancel", "no", "abort" | — | — | control | cancels pending |

Reuse existing number-word normalization (`_normalize_number_words`) and color aliases.
`match_status` transitions must be validated by `MatchManager`/`umpire_engine` (e.g.,
`start_next_game` only when `game_won`; `end_game` guarded).

## 8. Confirmation and safety plan (`voice/confirmation.py`)

New `ConfirmationPolicy.decide(result: VoiceParseResult, context) -> Literal["apply","confirm","reject"]`:

- **Auto-apply** (`apply`): high-confidence simple `score_point` (conf ≥ 0.85, not strict mode, noise gate passed).
- **Require confirmation** (`confirm`): all direct score changes (`set_score`), admin/tournament commands (`start_match`, `pause`, `end_game`, `timeout_*`, `set_server`, `start_next_game`), low-confidence (< 0.85) commands, and any command when `VOICE_STRICT_MODE` or `VOICE_ENABLE_CONFIRMATION` is on.
- **Reject**: noise gate fail (handled earlier), unknown intent, `MatchManager` validation failure, or duplicate within cooldown.
- **Undo**: immediately available after every state-changing voice command; undo creates a new `VoiceEvent` with `status="undone"` and links via `undone_by`.

### 8.1 Real-time (continuous) confirmation mechanic

Because streaming WebRTC emits events continuously, the policy is applied per event:

- **`apply` events** mutate score immediately (current behavior at voice_scorekeeper.py:615), then a one-click **Undo** is surfaced.
- **`confirm` events** are NOT applied. They are pushed to a per-session
  `pending_confirmations: list[VoiceParseResult]` in `st.session_state`; the
  confirm/cancel panel renders them with intent + predicted score delta; only an
  explicit `✅ Confirm` (or `POST /api/voice/confirm`) calls `MatchManager`. A
  `⏱️ auto-expire` (e.g., 8 s) drops stale pending items to avoid backlog.
- **`reject` events** are logged and ignored.

This keeps the fast feedback loop for points while guaranteeing no direct/admin
score change happens without operator acknowledgement. The busy-loop `st.rerun()`
at voice_scorekeeper.py:703 is retained only while `voice_listening` and drains the
queue; pending items are re-rendered each rerun.

### 8.2 Pending-event data shape

```
pending_confirmations: [
  { event_id, intent, predicted_score_before, predicted_score_after,
    confidence, received_at, source }
]
```

## 9. ASR backend plan (keep faster-whisper default)

- `VOICE_ASR_BACKEND=faster_whisper` (already default in `settings.py:86`).
- Add to `settings.py` (centralize, currently only in `voice_asr.py` env reads):
  `VOICE_ASR_MODEL_SIZE=base.en`, `VOICE_ASR_DEVICE=cpu`, `VOICE_ASR_COMPUTE_TYPE=int8`.
- `VOICE_ASR_FALLBACK_BACKEND=faster_whisper` (currently `speechbrain` default — change to `faster_whisper` to honor brief, since SpeechBrain is optional/heavy).
- Do **not** implement Vosk/Picovoice/whisper.cpp/SpeechBrain backends in this plan
  beyond the already-present `speechbrain_backend.py` (guarded import). The
  `ASRBackend` interface already supports them; factory already does fallback.

## 10. VAD and audio plan (`voice/vad.py`)

Add a real VAD behind the existing amplitude gate:
- **Primary (lightweight, recommended):** `webrtcvad` — pure-C, ~50 KB, runs at
  8/16/32 kHz, no model download, already in the audio stack vicinity. Best
  default for offline tournament laptops.
- **Optional (accurate):** Silero VAD (`silero-vad`, ONNX) behind an optional dep
  flag; loads a small ONNX model (graceful skip if unavailable). Choose when venues
  are very noisy and webrtcvad false-rejects.
- **Fallback:** keep `VoiceAudioBuffer` RMS amplitude gate when neither is installed
  (no-SpeechBrain/no-VAD import test must still pass).
- Decision: ship `webrtcvad` as the default VAD; Silero behind `VOICE_VAD=silero`
  opt-in. Both satisfy the brief ("Silero VAD or WebRTC VAD").
- Sample rate: target 16 kHz (WebRTC delivers 48 kHz → resample in `AudioChunk.to_pcm_bytes`, already done).
- Chunking: `min_speech_duration_ms=300`, `max_chunk_duration_ms=3000`, `silence_duration_ms=500` (existing defaults are fine); VAD replaces the RMS-only speech decision.
- Noise calibration: recommended threshold + `NoiseProfiler` stats are held in the
  `mic_calibration` component / `st.session_state` and applied via `VOICE_NOISE_THRESHOLD`;
  `recommend_threshold()` seeds the gate. Mic test mode records 3 s ambient → suggests threshold.
- Fallback behavior: if VAD model load fails, log warning and continue with amplitude gate.

## 11. Dataset recorder plan (`voice/dataset_recorder.py`)

Privacy-safe, opt-in (`VOICE_DATASET_OPT_IN` default False):
- Capture per utterance: transcript, parsed intent, **expected** intent (operator label), match context snapshot (players, score, game#), mic type, noise condition.
- **No audio stored by default.** Add `audio_stored` only when explicit `record_audio=True` flag set (default off; never default-on).
- Correction labels: operator can mark `matched`/`correction` for accuracy measurement.
- Export format: JSONL (`VoiceCommand` rows) + CSV summary (intent accuracy, confusion matrix).
- Evaluation use: offline grammar/parser accuracy; feed `INTENT_EXAMPLES` (existing `voice_command_dataset.py`).
- Persistence: `voice_commands` table (§4); endpoint `POST /api/voice/dataset-samples`.

## 12. AI commentary and umpire assistant plan

Already grounded — preserve and enforce:
- `commentary_service.build_score_commentary` reads only `SpokenScoreState.from_match_state` (commentary_service.py:69) — **allowed**.
- `voice_llm.LLMInterpreter` only *proposes*; `MatchManager` validates (voice_llm.py) — **allowed**.
- Rule context from `umpire_engine.UmpireEngine` for explanations only.
- **Invariant (add a test):** no AI path may call `MatchManager.apply_voice_event` /
  `engine_*` mutators. Commentary/umpire are read-only over the event log + score state.
- Add a `voice_ai_grounding` check in `VoiceService`: LLM output is converted to a
  `VoiceParseResult` with `source="llm"` and **always** `requires_confirmation=True`.
- Hallucination guard: strip any entity not present in known players/match context.

## 13. Multi-court — OUT OF SCOPE (single-operator, single-match)

Per direction, this plan **does not implement per-table `VoiceSession`s, multi-court
concurrency, or role/permission-scoped sessions.** Rationale: `st.session_state` and
the WebRTC context are per-browser-connection and the app holds one global
`match_manager`; true simultaneous multi-court scoring needs the FastAPI backend to
own match state, which is a separate initiative.

What remains:
- Scope is one operator scoring **one selected match** at a time (already the case via
  `voice_selected_match_id`).
- `VoiceEvent.match_id` still tags every event so multi-court can be added later without
  a schema change; no `session_id`/`table_id`/`owner_id` columns are introduced.
- Manual fallback controls remain available for the operator.

## 14. Testing plan

- **Parser/grammar tests** — `test_voice_commands.py`: every intent in §7 + number-word
  normalization (`_normalize_number_words`), color aliases, deuce gating.
- **Undo tests** — apply point → undo restores score; undo at empty history is no-op.
- **Confirmation policy tests** — `test_confirmation.py`: auto-apply boundary (0.85),
  `set_score`→confirm, strict mode→confirm, low conf→confirm, unknown→reject.
- **ASR backend factory tests** — unknown backend falls back; unavailable backend returns safe default; no import of heavy deps.
- **VoiceEvent persistence tests** — `test_voice_event_repo.py`: insert + read round-trip,
  undo link, retention filter. Use `Base.metadata.create_all` test DB.
- **MatchManager integration tests** — voice event → correct score; invalid → rejected.
- **Streamlit import test** — `test_imports.py`: page imports without faster-whisper/
  streamlit-webrtc/silero loaded (graceful `object` fallback already present).
- **No-optional-dependency import test** — import `asr_backends`, `vad`, `voice_llm`
  with optional packages absent; assert guarded imports succeed.
- **WebRTC queue test** — `test_voice_audio_queue.py`: push frames → drained events; thread-safe queue not blocking; simulated worker loop.
- **Dataset recorder opt-in test** — with opt-in off, no `VoiceCommand` rows; with on, row written; audio never stored unless flag.
- **AI grounding test** — LLM proposal never mutates score; always requires confirmation.

## 15. Implementation phases

**Phase 1 — Safety & UI quick wins (small–medium)**
Transcript panel, parsed-command panel, confidence indicator, command cheat sheet
(generated from `commands.py`), spoken confirmation, one-command undo, and the
**confirmation/cancel panel** wired to `ConfirmationPolicy`. Stop auto-applying
`requires_confirmation` events.

**Phase 2 — Service refactor & persistence (medium)**
Move `VoiceParser` decisions into `voice/commands.py` + `voice/parse_result.py`;
add `VoiceEvent`/`VoiceCommand` models + alembic revision;
`event_log.py` repository; `VoiceService.confirm_event`/`persist_event`; parser tests.

**Phase 3 — Real-time voice & audio robustness (medium)**
`voice/vad.py` (Silero/WebRTC VAD + amplitude fallback); `st.audio_input` push-to-talk
widget; mic calibration component; thread-safe queue already present — keep & test.

**Phase 4 — Dataset recorder & evaluation (medium)**
`dataset_recorder.py` opt-in capture, correction labels, JSONL/CSV export,
evaluation dashboard; accuracy metrics feed grammar improvements.

**Phase 5 — AI commentary & umpire grounding (medium)**
Grounded commentary/umpire unchanged-except-invariant (read-only over event log +
score state); add the `voice_ai_grounding` guard in `VoiceService` (LLM output →
`VoiceParseResult` with `source="llm"` and `requires_confirmation=True`); add the
API endpoints from §5 (transcribe/parse/voice-events/confirm/dataset-samples).
No per-table sessions (see §13).

## 16. Risk assessment

| Risk | Mitigation |
|---|---|
| Wrong score update | Confirmation panel (Phase 1); undo always available; cooldown; `MatchManager` validation |
| Background speech triggers commands | VAD (Phase 3) + noise gate + strict-mode confirmation; directional/headset mic guidance |
| Noisy venue failure | `NoiseProfiler` calibration + threshold recommendation; amplitude fallback |
| Streamlit rerun/threading bugs | Keep background worker + thread-safe `queue.Queue`; never touch `st.session_state` in worker; state changes only in main thread |
| ASR latency | Lazy model cache (already); show latency metric; push-to-talk avoids continuous load |
| User distrust | Visible transcript + parsed panel + confirm/cancel + undo + event history |
| Data privacy | No audio stored by default (Phase 4); transcript-only dataset; `VOICE_RETENTION_DAYS` |
| Optional dependency failures | Guarded imports everywhere; no-optional-dep import test; amplitude VAD fallback |
| Model loading time | Lazy load (no load at import); cache keyed by config; status chip |
| LLM hallucination | LLM proposes only, always confirmed, never mutates score (Phase 5 invariant + test) |

## 17. Effort estimate

- Phase 1: medium
- Phase 2: medium
- Phase 3: medium
- Phase 4: medium
- Phase 5: medium

## 17b. Open decisions / areas for user input

These were resolved in-plan with the stated recommendation; the user may override:

1. **VAD default** — recommended `webrtcvad` (lightweight, no download); Silero
   opt-in. Swap if venues prove too noisy for webrtcvad.
2. **Fallback backend default** — recommended `VOICE_ASR_FALLBACK_BACKEND=faster_whisper`
   (currently `speechbrain` in `settings.py:87`). Change honors the brief.
 3. **API endpoints scope** — recommended: ship the Streamlit-direct `VoiceService`
    path in Phase 1-2; add the FastAPI endpoints (§5) in Phase 5 once the confirm/
    persist flow is proven (they are optional for the single-operator MVP).
 4. **Pending-confirm auto-expire** — recommended 8 s; tune per operator preference.

## 18. Acceptance criteria

- [ ] Existing voice scorekeeper still works (WebRTC + push-to-talk).
- [ ] faster-whisper remains the default backend; factory fallback intact.
- [ ] No heavy model loads at Streamlit import time (lazy load preserved).
- [ ] Every voice score change is visible (transcript + parsed panel) and undoable (1 click).
- [ ] Direct score changes (`set_score`) and admin/tournament commands require confirmation.
- [ ] Voice events are persisted (DB `voice_events`) and viewable in an event-history panel.
- [ ] Parser/grammar tests pass for all intents in §7.
- [ ] Manual controls (buttons, score entry) remain available.
- [ ] App runs without optional voice deps (silero/VAD/speechbrain) — graceful fallback.
- [ ] AI commentary / umpire assistant cannot mutate match score (read-only invariant + test).
- [ ] Dataset recorder stores no audio unless explicitly enabled; opt-in only.

## Recommended order of work (hand-off checklist)

1. Add `ConfirmationPolicy` + stop auto-apply in `_process_voice_events`; add confirm/cancel panel. (Phase 1)
2. Move grammar to `voice/commands.py` + `VoiceParseResult`; generate cheat sheet. (Phase 1–2)
 3. Add `VoiceEvent`/`VoiceCommand` models + alembic revision + `event_log.py`; persist from `VoiceService`. (Phase 2)
 4. Add `st.audio_input` push-to-talk path. (Phase 3)
 5. Add `voice/vad.py` (Silero/WebRTC + amplitude fallback). (Phase 3)
 6. Add `mic_calibration.py` + `NoiseProfiler` wiring. (Phase 3)
 7. Add `dataset_recorder.py` + export. (Phase 4)
 8. Add API endpoints (§5) + `voice_ai_grounding` guard in `VoiceService`. (Phase 5)
 9. Write the test suite (§14) and run `pytest`.
