# TT Sounds Integration — Audio Rally Assistant Plan

## 1. Repository Findings: Reusable Modules

| Module | Path | Why Reused |
|--------|------|------------|
| Voice Audio Processor | `tournament_platform/app/pages/voice_scorekeeper.py:1117` (`VoiceAudioProcessor`) | Existing WebRTC audio callback, queue-based worker pattern, format detection, graceful ASR fallback. We will extend it to share the microphone pipeline. |
| Audio Buffer / Chunk | `tournament_platform/app/services/voice_audio.py` (`VoiceAudioBuffer`, `AudioChunk`) | Frame buffering, RMS calculation, mono/PCM conversion, sample-rate handling. **We will NOT reuse ASR-sized chunks for impact detection.** Instead, the rally detector receives raw WebRTC frames or short 1–20 ms normalized windows from the shared callback. |
| Score Engine | `tournament_platform/app/services/score_engine.py` | Single source of truth. Audio events must never touch this. |
| Match Manager | `tournament_platform/services/match_manager.py` | Wraps score engine; audio events must never call `apply_voice_event`. |
| Commentary Service | `tournament_platform/services/commentary_service.py` | Generates `CommentaryLine` objects. Phase 1 will append a conservative audio line without changing the template bank. |
| Commentary Orchestrator | `tournament_platform/app/services/commentary/orchestrator.py` | Page-facing API; defer template-bank integration to Phase 2. |
| Commentary Templates | `tournament_platform/app/services/commentary/template_bank.py` | Already has `rally_length` placeholders for `point_won`. Phase 2 may add `audio_rally_detected` templates. |
| Settings / Env | `tournament_platform/services/settings.py` | All feature flags are env-driven with safe defaults. New flags follow this pattern. |
| Config | `tournament_platform/config/__init__.py` | Pydantic settings for paths; already has `TT_*` data dirs for multimodal assets. |
| UI Patterns | `voice_scorekeeper.py` | `st.toggle` for feature flags, `st.expander` for debug panels, session-state-driven enable/disable, `disable_*_and_clear_pending_state` pattern. |
| Tests | `tests/` | pytest + mocked Streamlit. Existing patterns in `test_voice_webrtc_safe.py`, `test_voice_audio.py`, `test_match_analytics.py`. |

**Critical constraint confirmed:** `VoiceAudioProcessor._ingest_frame` runs in the WebRTC callback thread. Heavy processing must be offloaded to a background worker, exactly as ASR transcription is.

---

## 2. Proposed Architecture and Data Flow

```
WebRTC Audio Frames
        │
        ▼
Shared VoiceAudioProcessor._ingest_frame()
   (callback thread — non-blocking)
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
ASR path (voice scoring)       Impact detection path (Audio Rally Assistant)
- buffers into speech chunks    - raw frames → short 5 ms windows
- queues for ASR worker         - normalize float [-1.0, 1.0]
                                   - adaptive peak detection
                                   - emits TTAudioEvent into event_queue
        │                              │
        ▼                              ▼
ASR worker thread            TTRallyProcessor worker thread
- transcribe                  - detect impacts
- emit VoiceScoreEvent        - manage rally boundaries
        │                              │
        └──────────────┬───────────────┘
                       ▼
           Main Streamlit loop
   - _process_voice_events() (ASR)
   - _process_tt_sounds_events() (impacts)
   - _maybe_tt_sounds_heartbeat()
       │
       ▼
   Commentary / Analytics (read-only enrichment)
```

**Capture gating:**
```python
audio_capture_enabled = voice_scoring_enabled or tt_sounds_enabled
```
A single `VoiceAudioProcessor` instance handles both paths. Do not create a second WebRTC microphone component.

**Isolation rules:**
- `TTRallyProcessor` never imports `MatchManager` or `ScoreEngine`.
- `TTRallyProcessor` never mutates session state directly; it only emits events.
- The main loop is the *only* bridge between audio events and match state.
- All Torch/torchaudio/model imports are inside `try/except` in a lazy loader.
- Impact detection uses raw frames or short windows, NOT ASR-sized `AudioChunk` objects.

---

## 3. Exact Files to Create or Modify

### New files

```
tournament_platform/app/services/tt_sounds/
    __init__.py
    settings.py
    schemas.py
    detector.py
    processor.py
    rally_context.py
    classifier.py          # optional stub for future Torch model
```

### Modified files

| File | Change |
|------|--------|
| `tournament_platform/services/settings.py` | Add `TT_SOUNDS_ENABLED`, `TT_SOUNDS_ABS_MIN_ENERGY`, `TT_SOUNDS_THRESHOLD_MULTIPLIER`, `TT_SOUNDS_NOISE_FLOOR_DECAY`, `TT_SOUNDS_COOLDOWN_MS`, `TT_SOUNDS_WINDOW_MS`, `TT_SOUNDS_EVENT_WINDOW_MS`, `TT_SOUNDS_DEBUG`, `TT_SOUNDS_MODEL_DIR` env flags. |
| `tournament_platform/config/__init__.py` | Add `TT_SOUNDS_MODEL_DIR` pydantic field (gitignored local path). |
| `tournament_platform/app/pages/voice_scorekeeper.py` | Import new module lazily; add toggle, debug panel, rally summary, session-state keys, event drain loop, cleanup on disable, heartbeat helper. |
| `tournament_platform/services/commentary_service.py` | Accept optional `audio_summary` context in commentary build helpers (Phase 1 minimal). |
| `.gitignore` | Add `tt_sounds_models/`, `**/tt_sounds_*/**`, confirm `tt_ai_data/` already covered. |

**Note:** Global `match_analytics` package changes are deferred to Phase 2. Phase 1 keeps audio summaries local to Voice Scorekeeper session state.

---

## 4. New Dataclasses / Schemas

```python
# tt_sounds/schemas.py

@dataclass
class TTAudioEvent:
    timestamp: float
    event_type: str          # "impact"
    energy: float
    confidence: float
    source: str              # "tt_sounds_detector"
    sample_rate: int
    channels: int

@dataclass
class RallyContext:
    rally_start_ts: float
    impacts: List[TTAudioEvent]
    is_active: bool

@dataclass
class AudioRallySummary:
    rally_id: str
    start_ts: float
    end_ts: float
    impact_count: int
    avg_interval_ms: float
    strongest_impact_energy: float
    confidence: float
    last_action: str = "gap"   # "point_scored", "undo", "reset", "gap"
    source: str = "tt_sounds_detector"

@dataclass
class AudioImpactEvent:
    timestamp: float
    energy: float
    confidence: float
```

---

## 5. Environment Variables / Settings

Add to `tournament_platform/services/settings.py`:

```python
TT_SOUNDS_ENABLED: bool = _get_env_bool("TT_SOUNDS_ENABLED", False)
TT_SOUNDS_ABS_MIN_ENERGY: float = _get_env_float("TT_SOUNDS_ABS_MIN_ENERGY", 0.03)
TT_SOUNDS_THRESHOLD_MULTIPLIER: float = _get_env_float("TT_SOUNDS_THRESHOLD_MULTIPLIER", 4.0)
TT_SOUNDS_NOISE_FLOOR_DECAY: float = _get_env_float("TT_SOUNDS_NOISE_FLOOR_DECAY", 0.95)
TT_SOUNDS_COOLDOWN_MS: float = _get_env_float("TT_SOUNDS_COOLDOWN_MS", 80.0)
TT_SOUNDS_WINDOW_MS: float = _get_env_float("TT_SOUNDS_WINDOW_MS", 5.0)
TT_SOUNDS_EVENT_WINDOW_MS: float = _get_env_float("TT_SOUNDS_EVENT_WINDOW_MS", 15.0)
TT_SOUNDS_MIN_INTERVAL_MS: float = _get_env_float("TT_SOUNDS_MIN_INTERVAL_MS", 30.0)
TT_SOUNDS_DEBUG: bool = _get_env_bool("TT_SOUNDS_DEBUG", False)
TT_SOUNDS_MODEL_DIR: str = _get_env_str("TT_SOUNDS_MODEL_DIR", "")
```

Add to `tournament_platform/config/__init__.py`:
```python
TT_SOUNDS_MODEL_DIR: str = ""
```

**Defaults:** all OFF / zero / safe. No Torch required at import time.

---

## 6. UI Changes (Phase 2)

All changes in `tournament_platform/app/pages/voice_scorekeeper.py` inside `_render_ui()`.

### 6.1 Toggle and Warning

Place immediately after the "Voice Scoring" section toggle (around line 4352):

```python
st.divider()
st.subheader("🏓 Audio Rally Assistant (Experimental)")

_prev_audio = st.session_state.get("tt_sounds_enabled", False)
st.session_state.tt_sounds_enabled = st.toggle(
    "Experimental Audio Rally Assistant",
    value=st.session_state.tt_sounds_enabled,
    help="Detects table-tennis impact sounds for commentary enrichment only. "
         "Does NOT update the score. Disabled by default.",
)
if st.session_state.tt_sounds_enabled:
    st.warning("⚠️ Audio detection does not update the official score. "
               "Manual scoring and voice commands remain the source of truth.")
```

### 6.2 Debug Panel

```python
if st.session_state.tt_sounds_enabled:
    with st.expander("🔬 Audio Rally Debug", expanded=False):
        _dims = st.session_state.get("tt_sounds_recent_events", [])
        if _dims:
            for ev in _dims[-10:]:
                st.caption(f"{ev.timestamp:.2f}s — {ev.event_type} energy={ev.energy:.3f} conf={ev.confidence:.2f}")
        else:
            st.caption("No impacts detected yet.")
```

### 6.3 Rally Summary Widget

```python
if st.session_state.tt_sounds_enabled:
    _ctx = st.session_state.get("tt_sounds_rally_context")
    if _ctx and _ctx.impacts:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Impacts", len(_ctx.impacts))
        with c2:
            dur = (_ctx.impacts[-1].timestamp - _ctx.impacts[0].timestamp) if len(_ctx.impacts) > 1 else 0.0
            st.metric("Rally duration", f"{dur:.1f}s")
        with c3:
            intervals = [
                _ctx.impacts[i+1].timestamp - _ctx.impacts[i].timestamp
                for i in range(len(_ctx.impacts)-1)
            ]
            avg = sum(intervals)/len(intervals) if intervals else 0.0
            st.metric("Avg interval", f"{avg*1000:.0f} ms")
        with c4:
            strongest = max(e.energy for e in _ctx.impacts)
            st.metric("Strongest impact", f"{strongest:.3f}")
    else:
        st.caption("Start a rally to see audio summary.")
```

### 6.4 Toggle-Off Cleanup

```python
elif _prev_audio and not st.session_state.tt_sounds_enabled:
    _clear_tt_sounds_state()
    st.toast("Audio Rally Assistant disabled.", icon="ℹ️")
```

### 6.5 Unavailable Message

```python
if not WEBRTC_AVAILABLE:
    st.info("Audio Rally Assistant requires streamlit-webrtc (unavailable in this environment).")
```

---

## 7. Session State Keys

Add in `voice_scorekeeper.py` near the other voice state initialization blocks:

```python
if 'tt_sounds_enabled' not in st.session_state:
    st.session_state.tt_sounds_enabled = TT_SOUNDS_ENABLED
if 'tt_sounds_recent_events' not in st.session_state:
    st.session_state.tt_sounds_recent_events = []      # bounded list of TTAudioEvent
if 'tt_sounds_rally_context' not in st.session_state:
    st.session_state.tt_sounds_rally_context = None     # RallyContext or None
if 'tt_sounds_audio_summaries' not in st.session_state:
    st.session_state.tt_sounds_audio_summaries = []     # list of AudioRallySummary (Phase 1 local)
if 'tt_sounds_processor' not in st.session_state:
    st.session_state.tt_sounds_processor = None
if 'tt_sounds_unavailable_notice_shown' not in st.session_state:
    st.session_state.tt_sounds_unavailable_notice_shown = False
```

**Note:** We do not add `tt_sounds_webrtc_ctx`. The shared `voice_webrtc_ctx` already holds the processor.

---

## 8. New Package: `tournament_platform/app/services/tt_sounds/`

### 8.1 `settings.py`

Re-export env flags from `tournament_platform.services.settings` with the `TT_SOUNDS_` prefix so imports stay localized.

### 8.2 `schemas.py`

Dataclasses from Section 4. Include `asdict()` helpers for JSON serialization.

### 8.3 `detector.py`

Lightweight impact detector. **No Torch dependency. Does not consume ASR-sized AudioChunk objects.**

Receives either:
- raw WebRTC frame bytes / ndarray, or
- short rolling windows (configurable: 1–20 ms, default 5 ms)

```python
class ImpactDetector:
    def __init__(
        self,
        abs_min_energy: float = 0.03,
        threshold_multiplier: float = 4.0,
        noise_floor_decay: float = 0.95,
        cooldown_ms: float = 80.0,
        window_ms: float = 5.0,
        event_window_ms: float = 15.0,
        sample_rate: int = 48000,
    ):
        ...

    def process_window(self, window: np.ndarray, timestamp: float) -> Optional[TTAudioEvent]:
        # 1. normalize to float [-1.0, 1.0]
        # 2. update moving noise floor (decay average)
        # 3. compute RMS
        # 4. if RMS < abs_min_energy → return None
        # 5. if RMS < noise_floor * threshold_multiplier → return None
        # 6. if cooldown not elapsed → return None
        # 7. confidence = clamp(RMS / (noise_floor * threshold_multiplier * 2), 0, 1)
        # 8. return TTAudioEvent with timestamp, energy, confidence
```

**Key design:** The detector works on millisecond-level windows, not ASR utterance chunks. This avoids the 300–4000 ms buffering delay of `VoiceAudioBuffer`.

### 8.4 `processor.py`

Queue-based worker, modeled after `VoiceAudioProcessor`. **Consumes raw frames or short windows, not ASR AudioChunk objects.**

```python
class TTRallyProcessor:
    def __init__(self, detector: ImpactDetector, ...):
        self._detector = detector
        self._chunk_queue = queue.Queue(maxsize=50)   # short windows / raw frames
        self._event_queue = queue.Queue(maxsize=200)
        self._worker_thread = None
        self._stop = threading.Event()

    def ingest_frame(self, frame: Any) -> None:
        """Receive raw WebRTC frame from shared processor."""
        # non-blocking put; drop-oldest if full
        ...

    def ingest_window(self, window: np.ndarray, timestamp: float) -> None:
        """Receive pre-computed short window."""
        ...

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._chunk_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if isinstance(item, tuple) and len(item) == 2:
                window, ts = item
                event = self._detector.process_window(window, ts)
            else:
                # raw frame — convert to window inside worker
                window, ts = self._frame_to_window(item)
                event = self._detector.process_window(window, ts)
            if event:
                try:
                    self._event_queue.put_nowait(event)
                except queue.Full:
                    pass

    def get_events(self) -> List[TTAudioEvent]:
        ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
```

### 8.5 `rally_context.py`

Manages the current in-progress rally and completed summaries.

```python
class RallyManager:
    def __init__(self, max_events: int = 500):
        self._current: Optional[RallyContext] = None
        self._summaries: List[AudioRallySummary] = []
        self._max_events = max_events

    def add_event(self, event: TTAudioEvent) -> Optional[AudioRallySummary]:
        # Start new rally if none active or gap > 2.0 s
        # If gap large → finalize previous rally → return summary
        # Append event; cap list size
        ...

    def finalize_current_rally(self, last_action: str = "gap") -> Optional[AudioRallySummary]:
        ...

    def current_context(self) -> Optional[RallyContext]:
        ...

    def summaries(self) -> List[AudioRallySummary]:
        ...
```

**Rally boundary heuristic:** gap > 2.0 seconds between impacts ends a rally. Configurable via env var later.

### 8.6 `classifier.py` (Phase 5 stub)

```python
class TTClassifier:
    def __init__(self, model_dir: str = ""):
        self._model_dir = model_dir
        self._available = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch
            import torchaudio
            # attempt to load model files from model_dir
            # self._available = True
        except ImportError:
            self._available = False
        except Exception:
            self._available = False

    def classify(self, chunk: AudioChunk) -> Dict[str, Any]:
        if not self._available:
            return {"surface": "unknown", "spin_hint": "unknown", "available": False}
        # future: real inference
        return {"surface": "unknown", "spin_hint": "unknown", "available": True}
```

**Important:** The main loop must check `classifier.available` and silently skip if missing.

---

## 9. Integration Points in `voice_scorekeeper.py`

### 9.1 Shared Processor Attachment

Extend `VoiceAudioProcessor` with optional `tt_sounds_processor` so both ASR and impact detection share the same callback thread and WebRTC component.

```python
audio_capture_enabled = voice_scoring_enabled or tt_sounds_enabled
```

In `VoiceAudioProcessor.__init__`, add optional kwargs:
```python
def __init__(self, ..., tt_sounds_processor=None):
    self.tt_sounds_processor = tt_sounds_processor
```

In `_ingest_frame`, after ASR chunk emission, feed the same raw frame to the rally processor:
```python
if self.tt_sounds_processor is not None:
    try:
        self.tt_sounds_processor.ingest_frame(frame)
    except Exception:
        pass
```

**Critical:** The rally processor must convert frames to short windows inside its worker thread, not in the callback. The callback only does a non-blocking `put_nowait`.

### 9.2 Event Drain Loop and Heartbeat

Add `_process_tt_sounds_events()` and `_maybe_tt_sounds_heartbeat()`.

```python
def _process_tt_sounds_events() -> None:
    """Drain audio events even when voice scoring is disabled."""
    if not st.session_state.get("tt_sounds_enabled"):
        return
    ctx = st.session_state.get("voice_webrtc_ctx")
    proc = ctx.get("tt_sounds_processor") if ctx else None
    if proc is None:
        return
    for event in proc.get_events():
        _handle_tt_sounds_event(event)

def _maybe_tt_sounds_heartbeat() -> None:
    """Rerun UI to update debug panel and rally summary when audio events pending."""
    if not st.session_state.get("tt_sounds_enabled"):
        return
    ctx = st.session_state.get("voice_webrtc_ctx")
    proc = ctx.get("tt_sounds_processor") if ctx else None
    if proc is None:
        return
    has_pending = len(proc.get_events()) > 0
    interval = 0.5 if has_pending else 1.0
    now = time.time()
    last = st.session_state.get("tt_sounds_last_heartbeat", 0.0)
    if now - last < interval:
        return
    st.session_state.tt_sounds_last_heartbeat = now
    time.sleep(0.1)
    st.rerun()
```

Call `_maybe_tt_sounds_heartbeat()` in `_render_ui()` alongside the existing voice heartbeat.

### 9.3 Rally Finalization on Point Scored

The 2-second gap heuristic is only a fallback. The authoritative rally boundary is the scoring event.

Before calling commentary on any manual/voice point update:
```python
audio_summary = finalize_current_audio_rally(reason="point_scored")
```

Apply this to:
- Manual ➕ A / ➕ B
- Quick voice point
- Full voice command point

For `undo` and `reset`, mark the most recent summary with `last_action="undo"` or `last_action="reset"` rather than silently dropping it.

```python
def finalize_current_audio_rally(reason: str = "gap") -> Optional[AudioRallySummary]:
    ctx = st.session_state.get("tt_sounds_rally_context")
    if ctx is None or not ctx.impacts:
        return None
    summary = _build_summary_from_context(ctx, last_action=reason)
    st.session_state.tt_sounds_audio_summaries.append(summary)
    st.session_state.tt_sounds_rally_context = None
    return summary
```

### 9.4 Commentary Enrichment (Minimal)

When a score-changing event is applied and an `audio_summary` exists:

```python
if st.session_state.get("tt_sounds_enabled"):
    audio_summary = st.session_state.get("_pending_audio_summary_for_commentary")
    if audio_summary and audio_summary.confidence >= 0.55:
        _append_audio_commentary_line(audio_summary)
```

`_append_audio_commentary_line` appends one short conservative line to the existing commentary text. No new `TTEventType` or template-bank category is required for Phase 1.

Example appended text:
- EN: "Possible rally of {n} impacts detected before the point."
- LT: "Garso sistema aptiko galimus {n} smūgius prieš tašką."

### 9.5 Analytics Enrichment (Local to Session State)

In the Match Analytics section of `_render_ui()`, after rendering existing momentum/key events:

```python
if st.session_state.get("tt_sounds_enabled"):
    _summaries = st.session_state.get("tt_sounds_audio_summaries", [])
    if _summaries:
        _render_audio_rally_insights(_summaries)
```

`_render_audio_rally_insights` is a local helper in `voice_scorekeeper.py` (or a small `tt_sounds/analytics.py` module). It computes totals, longest rally, fastest tempo, and strongest impact from the session-state summaries and renders them in an expander with an explicit "experimental" warning.

**Do not modify global `match_analytics` package until Phase 2.**

---

## 10. Commentary Integration Strategy

### 10.1 Minimal Phase 1 Approach

**Do not add `TTEventType.AUDIO_RALLY_DETECTED` or modify the template bank in Phase 1.**

Instead, append one conservative audio commentary line directly after the normal score commentary is built:

```python
def _append_audio_commentary_line(audio_summary: AudioRallySummary) -> None:
    n = audio_summary.impact_count
    lang = st.session_state.get("commentary_language", "en")
    if lang == "lt":
        text = f"Garso sistema aptiko galimus {n} smūgius prieš tašką."
    else:
        text = f"Possible rally of {n} impacts detected before the point."
    # Append to pending commentary or speak directly
    st.session_state.pending_commentary = text
```

### 10.2 Conservative Language Rules

- Always use "possible", "detected", "audio suggests", "estimated".
- Never claim a winner, spin type, fault, or let from audio alone.
- If confidence < 0.55, suppress audio commentary entirely.
- Audio commentary is additive only; never replaces existing score commentary.
- No claims about topspin, backspin, serve quality, or fault.

### 10.3 Integration Hook

In `_apply_quick_voice_point` and the success branch of `apply_score_event_and_refresh_ui`, after existing commentary logic:

```python
if st.session_state.get("tt_sounds_enabled"):
    audio_summary = finalize_current_audio_rally(reason="point_scored")
    st.session_state["_pending_audio_summary_for_commentary"] = audio_summary
    if audio_summary and audio_summary.confidence >= 0.55:
        _append_audio_commentary_line(audio_summary)
```

**Defer to Phase 2:** Full `TTEventType.AUDIO_RALLY_DETECTED` template-bank integration, `CommentaryOrchestrator` changes, and `CommentarySettings` extension.

---

## 11. Analytics Integration Strategy

### 11.1 Phase 1: Local Session-State Analytics

**Do not modify `match_analytics` package in Phase 1.**

Add dataclasses in `tt_sounds/schemas.py`:

```python
@dataclass
class AudioImpactEvent:
    timestamp: float
    energy: float
    confidence: float

@dataclass
class AudioRallySummary:
    rally_id: str
    start_ts: float
    end_ts: float
    impact_count: int
    avg_interval_ms: float
    strongest_impact_energy: float
    confidence: float
    last_action: str = "gap"   # "point_scored", "undo", "reset", "gap"
    source: str = "tt_sounds_detector"
```

Store summaries in `session_state.tt_sounds_audio_summaries`.

### 11.2 Local Render Helper

Add `_render_audio_rally_insights(summaries: List[AudioRallySummary])` in `voice_scorekeeper.py` (or `tt_sounds/analytics.py`). Compute from session-state summaries:

```python
{
    "total_impacts": int,
    "total_rallies": int,
    "avg_impacts_per_rally": float,
    "longest_rally": {"impact_count": int, "duration_s": float},
    "fastest_tempo": {"avg_interval_ms": float},
    "strongest_impact": {"energy": float, "rally_id": str},
    "reliability": "experimental — not official scoring data",
}
```

Render inside an expander in `_render_ui()` Match Analytics section with a clear warning banner.

### 11.3 Data Retention

- Audio summaries are lightweight dicts; stored in session state only.
- No raw audio frames persisted in Phase 1.
- On match reset / new match, clear `tt_sounds_audio_summaries`.

**Defer to Phase 2:** Global `MatchInsight.audio_rallies`, `match_analytics/analyzer.py` extension, and `formatter.py` rendering.

---

## 12. Testing Plan

### Unit Tests (`tests/test_tt_sounds_*.py`)

| Test File | Coverage |
|-----------|----------|
| `test_tt_sounds_detector.py` | Impulse detection on 5 ms windows, cooldown prevents duplicates, sub-threshold noise ignored, adaptive threshold behavior, boundary RMS values, float normalization |
| `test_tt_sounds_processor.py` | Start/stop thread safety, queue drop-oldest, raw frame → window conversion, event emission, graceful stop |
| `test_tt_sounds_rally_context.py` | Rally start/end boundaries, max event cap, finalization, empty input, finalize on point scored |
| `test_tt_sounds_classifier.py` | Missing Torch/torchaudio/librosa/scipy → available=False, no crash on classify() |
| `test_tt_sounds_import_safety.py` | Importing `tt_sounds` never requires Torch; missing optional deps are safe |

### Integration Tests

| Test | Scenario |
|------|----------|
| `test_voice_scorekeeper_audio_assistant.py` | Toggle on/off clears state; debug panel shows events; rally summary updates; heartbeat works without voice scoring |
| `test_audio_never_modifies_score.py` | Audio events never call `MatchManager.apply_voice_event` or mutate `ScoreEngine` |
| `test_audio_rally_finalized_on_point.py` | Manual point, quick voice, full voice → rally finalized with `last_action="point_scored"` |
| `test_commentary_audio_enrichment.py` | Audio summary appended conservatively; never replaces score commentary; suppressed when confidence < 0.55 |
| `test_streamlit_cloud_safe.py` | Missing `torch`, `torchaudio`, `librosa`, `scipy` → app starts without crash |
| `test_audio_only_mode.py` | Audio Rally Assistant works when voice scoring is disabled |

### Test Fixtures

- Synthetic impulse on 5 ms window: `numpy` array with one high-energy sample surrounded by silence.
- Synthetic rally: sequence of impulses with configurable intervals.
- Mocked raw WebRTC frames and short windows.

---

## 13. Rollback Plan

1. **Feature flag kill-switch:** `TT_SOUNDS_ENABLED=False` (default) means zero code paths execute. Turning the env var off immediately disables the feature with no deploy needed.
2. **Session-state cleanup function:** `_clear_tt_sounds_state()` removes all `tt_sounds_*` keys. Calling it on toggle-off guarantees no stale state.
3. **Isolated package:** The entire feature lives under `tt_sounds/`. Removing the directory and its imports reverts the codebase.
4. **No scoring engine changes:** The score engine is untouched; rollback cannot corrupt match state.
5. **Gitignored models:** No model files are committed, so no cleanup of large binaries is needed.

---

## 14. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| WebRTC callback blocks | `TTRallyProcessor.ingest_frame` only does non-blocking `put_nowait`; worker converts frames to windows and does all math. |
| Torch not on Streamlit Cloud | `classifier.py` uses lazy imports inside `try/except`; feature degrades to detection-only. |
| False positives from noise | Adaptive threshold (noise floor decay + multiplier), absolute min energy, cooldown (80 ms), min interval (30 ms). Debug panel exposes raw events for tuning. |
| Circular imports | `tt_sounds` package imports nothing from `voice_scorekeeper.py`. Page imports `tt_sounds` lazily. |
| Memory leak from unbounded queues | Bounded queues with drop-oldest policy; `RallyManager` caps event list size. |
| Audio events accidentally scoring | Code review gate: `TTAudioEvent` type is never accepted by `apply_voice_event`. Unit test enforces this. |
| Licensing / dataset inclusion | No datasets or models committed. `.gitignore` extended. License note in README. |
| Streamlit Cloud log spam | Rate-limited logging in processor; debug panel only shows last 10 events. |
| Second WebRTC widget | Single shared `VoiceAudioProcessor`; `audio_capture_enabled = voice_scoring_enabled or tt_sounds_enabled`. |
| Impacts missed due to ASR buffering | Rally detector receives raw frames / 5 ms windows, not ASR-sized chunks. No speech buffering delay. |
| tt_sounds source heavy deps | Do not import `tt_sounds` repo modules. Reimplement lightweight detector locally. |

---

## 15. Step-by-Step Implementation Order

1. **Add settings and gitignore entries**
   - `tournament_platform/services/settings.py`: add `TT_SOUNDS_*` flags with adaptive threshold defaults.
   - `tournament_platform/config/__init__.py`: add `TT_SOUNDS_MODEL_DIR`.
   - `.gitignore`: add `tt_sounds_models/`, `**/tt_sounds_*/**`.

2. **Create `tt_sounds` package core**
   - `schemas.py` (dataclasses: `TTAudioEvent`, `RallyContext`, `AudioRallySummary`, `AudioImpactEvent`)
   - `settings.py` (re-exports)
   - `detector.py` (adaptive energy detection on short windows; no Torch)

3. **Create `tt_sounds/processor.py`**
   - Queue-based worker thread.
   - `ingest_frame` / `ingest_window` API.
   - Converts raw frames to short windows inside the worker.
   - Start/stop lifecycle.
   - Unit tests for start/stop and queue behavior.

4. **Create `tt_sounds/classifier.py` (stub)**
   - Lazy Torch/torchaudio import.
   - `available` flag.
   - Unit test for missing Torch.

5. **Wire processor into shared WebRTC flow**
   - Extend `VoiceAudioProcessor.__init__` with optional `tt_sounds_processor`.
   - Call `tt_sounds_processor.ingest_frame(frame)` in `_ingest_frame`.
   - Ensure `audio_capture_enabled = voice_scoring_enabled or tt_sounds_enabled`.
   - Unit test: mocked frame → processor receives frame.

6. **Add session state, event drain, heartbeat in `voice_scorekeeper.py`**
   - Initialize `tt_sounds_*` keys (remove `tt_sounds_webrtc_ctx`).
   - Add `_process_tt_sounds_events()`.
   - Add `_maybe_tt_sounds_heartbeat()`.
   - Add toggle, warning, debug panel, rally summary widget.
   - Add cleanup on toggle-off.

7. **Rally finalization on point scored**
   - Add `finalize_current_audio_rally(reason)` helper.
   - Call from manual point buttons, quick voice point, and full voice point success branch.
   - Handle undo/reset by marking `last_action`.

8. **Commentary integration (minimal)**
   - Append one conservative audio line after score commentary.
   - Confidence gate at 0.55.
   - No template-bank changes in Phase 1.

9. **Local analytics in session state**
   - Add `_render_audio_rally_insights()` helper in `voice_scorekeeper.py`.
   - Render in Match Analytics expander with experimental warning.
   - Do not touch `match_analytics` package yet.

10. **Write tests**
    - Detector unit tests (adaptive thresholds, short windows).
    - Processor thread-safety tests.
    - Rally context tests (finalize on point).
    - Import-safety tests (missing torch/librosa/scipy).
    - Integration tests for toggle/debug/heartbeat/commentary.
    - Test that score engine is untouched.
    - Test audio-only mode (voice scoring disabled).

11. **Verify lint / typecheck**
    - Run project lint command (ruff/mypy).
    - Fix any import-cycle or typing issues.

12. **Final review**
    - Confirm no Torch import at module load time.
    - Confirm default `TT_SOUNDS_ENABLED=False`.
    - Confirm `.gitignore` covers model paths.
    - Confirm no datasets or large files committed.
    - Confirm shared WebRTC pipeline (no second microphone widget).
    - Confirm heartbeat works without voice scoring.
