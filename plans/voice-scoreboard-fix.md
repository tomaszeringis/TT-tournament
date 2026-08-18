# Plan: Fix Live Voice Command Scoreboard Update

## 1. Exact Reason for `finalized_invalid = 6`

**Location:** `drain_streaming_events()` in `tournament_platform/app/services/voice_scorekeeper/runtime.py`

```python
if not isinstance(utt, FinalizedUtterance):
    self._streaming_invalid += 1
    continue
```

**Root cause:** Unknown without type logging. The Deepgram backend's `_emit_finalized()` only enqueues `FinalizedUtterance` objects, so non-conforming items must enter through an alternate path (stale backend instance, test contamination, or queue corruption).

**Fix applied:**
- Log `type(utt).__name__`, `type(utt).__module__`, and `repr(utt)[:200]` when `_streaming_invalid` increments.
- Expose `_last_finalized_invalid_type`, `_last_finalized_invalid_module`, `_last_finalized_invalid_repr` in processor diagnostics.
- Merge `backend_finalized_utterances_emitted` and `backend_finalized_queue_depth` from backend diagnostics into processor diagnostics (specific keys only, not blind merge).

---

## 2. Exact Reason `runtime_mode = calibration` While Full Voice Commands Is Active

**Root cause found in `_process_streaming_startup()` (`voice_scorekeeper.py`):**

After successful Deepgram backend attachment, the function sets:
- `voice_streaming_config_frozen = True`
- `voice_streaming_session_id = _new_session_id`
- `voice_continuous_session_id = _new_session_id`
- `voice_listening = True`
- `voice_events_enabled = True`

**It never sets `voice_runtime_mode = VoiceRuntimeMode.LIVE`.**

`get_voice_runtime_mode()` in `event_drain.py` reads **only** from `st.session_state.get("voice_runtime_mode", VoiceRuntimeMode.OFF)`. 

If the user previously ran calibration (or the value was initialized to `None`), the session-state mode stays `CALIBRATION` or defaults to `OFF`. The processor's internal `_runtime_mode` is correctly set to `LIVE` by `set_streaming_backend()` at `runtime.py:720`, but `event_drain.py` ignores the processor and trusts session state.

**Impact:** When `runtime_mode == VoiceRuntimeMode.CALIBRATION`, `_process_voice_events()` at `event_drain.py:397` skips **every** continuous event:

```python
if _event_source == "calibration" or _runtime_mode == VoiceRuntimeMode.CALIBRATION:
    continue
```

This blocks:
- `last_continuous_transcript`
- parser calls
- score application
- visible scoreboard updates

---

## 3. Fix Applied (Summary)

### Fix A — Centralized runtime mode setter + streaming startup
**File:** `tournament_platform/app/pages/voice_scorekeeper.py`

Added `_set_voice_runtime_mode(target_mode, *, reason, caller)` which synchronizes:
- `st.session_state.voice_runtime_mode`
- `processor.set_runtime_mode()`
- audit trace

`_process_streaming_startup()` now calls `_set_voice_runtime_mode(VoiceRuntimeMode.LIVE, reason="streaming_started", ...)` after backend attachment.

### Fix B — Calibration exit never restores CALIBRATION
**File:** `tournament_platform/app/components/voice_scorekeeper/voice_calibration.py`

`_enter_calibration_mode()` and `_exit_calibration_mode()` now use the centralized setter.

`_exit_calibration_mode()` includes guard:
```python
if target_mode == VoiceRuntimeMode.CALIBRATION:
    target_mode = _compute_post_calibration_runtime_mode()
```

This ensures calibration can never restore itself.

### Fix C — Backend finalized counts in processor diagnostics
**File:** `tournament_platform/app/services/voice_scorekeeper/runtime.py`

`get_streaming_diagnostics()` now merges specific backend fields:
- `backend_finalized_utterances_emitted`
- `backend_finalized_queue_depth`
- `expected_finalized_utterance_module`

### Fix D — Enhanced invalid-item logging
**File:** `tournament_platform/app/services/voice_scorekeeper/runtime.py`

`drain_streaming_events()` now records type name, module, and short repr when rejecting non-`FinalizedUtterance` items.

---

## 4. Files Changed

1. `tournament_platform/app/pages/voice_scorekeeper.py` — centralized setter + streaming startup LIVE
2. `tournament_platform/app/components/voice_scorekeeper/voice_calibration.py` — use centralized setter + guard
3. `tournament_platform/app/services/voice_scorekeeper/runtime.py` — backend diagnostics merge + invalid logging
4. `tests/test_runtime_mode_regression.py` — new regression tests

---

## 5. Focused Tests / Results

**Passing:**
- `tests/test_post_calibration_live_scoring_fix.py` — 41 passed
- `tests/test_continuous_voice_drain.py` — 24 passed
- `tests/test_runtime_mode_regression.py` — 5 passed (new)

**Pre-existing failures (not caused by this fix):**
- `tests/test_voice_regression_continuous.py::test_duplicate_provider_callback_scores_once`
- `tests/test_voice_score_pipeline.py` (7 tests in `TestPhase6ContinuousSessionAndStalePrevention`, `TestLithuanianVoiceCommands`, `TestContinuousPipelineFixes`)

These failures stem from earlier `is_voice_scoring_enabled()` guard additions and MagicMock session-state setup issues, not from the runtime-mode fix.

---

## 6. What Still Requires Real Browser Verification

1. Saying *"taškas kairė"* updates scoreboard `0-0 → 1-0`
2. Saying *"taškas dešinė"* updates scoreboard `1-0 → 1-1`
3. Calibration wizard exit restores `runtime_mode = live` and subsequent commands score normally
4. `backend_finalized_utterances_emitted` shows >0 in diagnostics after real speech
5. `_last_finalized_invalid_*` fields remain empty (no invalid items in normal operation)
