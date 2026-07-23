# Voice Scoring Developer Guide

This document covers the technical implementation of the voice scoring pipeline, ASR backend design, WebRTC audio handling, and testing strategy.

## ASR Backend Design

### Pluggable Backend Architecture

The `ASRBackendFactory` (`tournament_platform/app/services/asr_backends/factory.py`) selects and instantiates ASR backends based on configuration. Each backend implements a common interface:

```python
class ASRBackend(ABC):
    def transcribe_pcm(self, pcm_bytes: bytes, sample_rate: int) -> str: ...
    def get_status(self) -> dict: ...
```

### LocalASR Module-Level Cache

`LocalASR` instances share a module-level model cache keyed by `(model_size, device, compute_type)`:

```python
_ASR_MODEL_CACHE: dict = {}
_ASR_CACHE_LOCK = threading.Lock()
```

This ensures the model is loaded only once per unique configuration, even if multiple instances are created during Streamlit reruns.

### Supported Backends

| Backend | Package | Config |
|---------|---------|--------|
| `faster_whisper` | `faster-whisper`, `ctranslate2`, `onnxruntime` | `VOICE_ASR_MODEL_SIZE`, `VOICE_ASR_DEVICE`, `VOICE_ASR_COMPUTE_TYPE` |
| `speechbrain` | `speechbrain`, `torch`, `torchaudio` | `VOICE_SPEECHBRAIN_MODEL_SOURCE` |
| `vosk` | `vosk` | `VOICE_ASR_VOSK_MODEL_PATH` |

### Factory Fallback Logic

1. Read `VOICE_ASR_BACKEND` from env/secrets.
2. Attempt to instantiate the primary backend.
3. If initialization fails and `VOICE_ASR_FALLBACK_BACKEND` is set, attempt the fallback.
4. If both fail, report `model_init_failed` and disable voice scoring.

### Vosk Notes

Vosk is registered in `ASRBackendFactory` but requires explicit installation (`pip install ".[live]"`) and a model directory at `VOICE_ASR_VOSK_MODEL_PATH`. The UI does not surface Vosk-specific setup; document it as "available only if installed and configured".

## WebRTC Audio Pipeline

### Thread Safety Rules

Audio callbacks run in a **WebRTC background thread** and **must not call Streamlit APIs directly**. They use thread-safe queues (`_chunk_queue`, `event_queue`) with bounded capacity and drop-oldest policy:

- `_chunk_queue` (maxsize=20 chunks)
- `event_queue` (maxsize=50 events)

The main Streamlit thread drains these queues in `_process_voice_events()` and `_maybe_voice_heartbeat()`.

### Audio Callback Safety Pattern

```python
def _audio_frame_callback_func(frame):
    with _audio_callback_lock:
        _audio_callback_count += 1
        _last_audio_frame_timestamp = frame.time
        _last_audio_frame_bytes = frame.to_ndarray().tobytes()
```

The callback updates **module-level globals** under a lock, explicitly avoiding `st.session_state`. Diagnostics are read on the main thread, not from the callback thread.

### Factory Diagnostics

`_factory_diag_lock` and `_factory_diag` dict are **module-level**. After `webrtc_streamer()` returns, metrics are snapshotted to `st.session_state` so they survive reruns:

```python
with _factory_diag_lock:
    _factory_diag["call_count"] += 1
    st.session_state._voice_factory_call_count = _factory_diag["call_count"]
```

### One-Shot Rerun + Heartbeat Split

`_process_voice_events()` no longer calls `st.rerun()` directly. Instead:

1. **One-shot rerun**: `_maybe_voice_rerun()` requests `st.rerun()` once after applying an event, drained at the end of `_render_ui()`.
2. **Heartbeat**: `_maybe_voice_heartbeat()` runs in the main thread with adaptive timing (250ms when draining, 1000ms idle).

This split avoids conflicting rerun calls from background threads.

### Session-Boundary Stale Event Prevention

Events carry `session_id` and `timestamp`. The processor (`VoiceAudioProcessor`) sets `_session_id` from `voice_continuous_session_id` after WebRTC play starts. Stale events are dropped in `_process_voice_events()` if:

- The event `session_id` does not match the current session
- The event timestamp is before the session start or after the last stop
- The event ID has already been applied (duplicate suppression)
- WebRTC is not playing

### Stable WebRTC Key

The `webrtc_streamer` key (`voice_scorekeeper_continuous_webrtc`) and `_WEBRTC_AUDIO_CONSTRAINTS` must remain stable across reruns. Streamlit-webrtc resets the component if the key changes.

## Voice Runtime State

`VoiceRuntimeState` (`tournament_platform/app/services/voice/runtime_state.py`) is a dataclass that centralizes voice scorekeeper state. It provides:

- `get_state()`: Returns the current state, initializing if needed.
- `set_state(state)`: Persists a state to session_state.
- `reset_state()`: Clears state and returns a fresh instance.
- `migrate_from_session_state()`: One-time migration from legacy scattered `voice_*` keys.
- `sync_legacy_keys(state)`: Writes key fields back to legacy session_state keys for backward compatibility.

**Dual state sources**: The page reads from both `VoiceRuntimeState` (via `get_state()`) and legacy keys (e.g., `st.session_state.voice_webrtc_streamer_state`). Documentation should not promise a single canonical key unless it is truly canonical. `sync_legacy_keys()` writes back after every state mutation.

## Command Grammar

`VoiceCommandGrammar` in `commands.py` defines ~40 intents beyond scoring:

- **Scoring**: `score_point`, `set_score`
- **Corrections**: `undo`
- **Score queries**: `repeat_score`
- **Match control**: `start_match`, `pause_match`, `resume_match`, `start_next_game`, `end_game`, `timeout_start`, `timeout_end`, `server_check`, `set_server`
- **Confirmation**: `confirm`, `cancel`
- **Navigation**: 7 intents (dashboard, bracket, rankings, public board, current match, scoring, help)
- **Admin**: 8 intents (call next, table ready, assign table, mark unavailable, publish result, mark no show, drop player, start next round)
- **Rules**: `rules_query`
- **Accessibility**: 13 intents (repeat, announce, volume, speech rate, text mode, contrast, help)

`cheat_sheet()` in `commands.py:453` is the canonical command reference. Any doc table should be validated against this function.

### Lithuanian Aliases

Both `commands.py` and `quick_voice.py` already include Lithuanian color alias patterns:
- Player A: `mėlynas`, `melynas`, `žalias`, `žalia`, `zalias`, `zalia`
- Player B: `raudonas`, `raudona`, `oranžinis`, `oranzinis`

## Quick Voice vs Full Voice Split

- **Quick Voice mode** only accepts color words via `QuickVoiceScoringEngine` (regex scan, 1.2s cooldown, game-boundary reset). It does not use the full parser.
- **Full mode** uses the canonical `VoiceCommandGrammar` + `CommandRouter`. All 40+ intents are available.

## Command Router

`RouteContext` encodes the routing policy:

```python
@dataclass
class RouteContext:
    current_score_a: int = 0
    current_score_b: int = 0
    current_game_index: int = 0
    strict_mode: bool = False
    enable_confirmation: bool = True
    cooldown_ms: float = 1200.0
    last_applied_event_key: Optional[str] = None
    last_applied_event_ts: float = 0.0
    min_confidence_to_apply: float = 0.5
    min_confidence_to_confirm: float = 0.5
```

`RouteDecision` enum: `REJECT`, `CONFIRM`, `APPLY`, `IGNORE`.

Duplicate suppression is game-aware: the event key includes `current_game_index` so a command repeated at the start of a new game is never treated as a duplicate of the previous game's last command.

## Audio Buffer and VAD

`VoiceAudioBuffer` in `voice_audio.py` handles:

- Frame chunking from WebRTC audio frames
- Voice Activity Detection (VAD) using `py-webrtcvad` if available, otherwise amplitude gating
- Noise gating with configurable RMS threshold (`VOICE_NOISE_THRESHOLD`)
- Resampling to the ASR-required sample rate

## Voice Audit

`EventLogger` in `voice_audit.py` is a bounded ring buffer (max 1000 events). Events include:
- `source`: `debug`, `push_to_talk`, `continuous`
- `accepted`: bool
- `confidence`: float
- `previous_score` / `new_score`: string
- `note`: rejection reason or duplicate suppression flag

Export as JSONL via the UI or programmatically.

## Test Strategy

### Operator Smoke Test
1. Open Voice Scorekeeper, verify manual scoring works.
2. Select an active match.
3. Push-to-talk: speak "point blue" → Player A score increments.
4. Push-to-talk: speak "undo" → last point removed.
5. Debug: type "five four" → score sets to 5-4.
6. Continuous: click START → speak "red" → Player B score increments.
7. Confirmation: speak "set score ten eight" → confirmation panel appears.
8. Audit export: click Export → file downloads.
9. Reset: switch to Off → voice state clears.

### Unit Tests
- `tests/test_voice_parser.py` — parser unit tests
- `tests/test_voice_command_router.py` — router decisions
- `tests/test_score_engine.py` — ScoreEngine rules
- `tests/test_continuous_listening_rerun.py` — one-shot rerun behavior
- `tests/test_voice_webrtc_safe.py` — WebRTC callback safety
- `tests/test_voice_event_repo.py` — audit/export persistence
- `tests/test_asr_backends.py` — backend factory fallback logic

### Regression Tests
Add parser tests for every documented command example. If a command example is removed, remove its test; if added, add a test.
