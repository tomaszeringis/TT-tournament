# Voice Scorekeeper Continuous Listening — Debug & Fix Plan

## Implementation Guardrail

**First implementation scope is limited to Phase 0–3 only.**

Do not modify WebRTC, ASR, VAD, RMS thresholds, worker threads, or continuous-listening internals in this pass.

Stop after Phase 0 and report results before continuing to Phase 1+:
- Does "point red" update score?
- Does "point blue" update score?
- Does "undo" work?
- What exact function updates the score?
- What state does the scoreboard read?
- What tests passed?

Do not continue to audio fixes until these are proven.

---

## 1. Summary of Observed Problem

Continuous listening in the Voice Scorekeeper page rejects **every** voice command. The UI displays a message along the lines of *"Last update: Voice command rejected."* No points are added, scores do not change, and the live scoreboard does not refresh. Push-to-talk and manual scoring are reported to still work, but need verification.

The failure is systematic (100 % rejection rate), not intermittent. **Before debugging WebRTC, ASR, VAD, noise gate, or worker threads, we must prove the non-audio text-command path works end-to-end.** If a typed debug command fails, the bug is in parser/router/match/scoring/rerun, not in audio.

---

## 2. Current Voice Pipeline Findings

### 2.1 Page & State
- **File:** `tournament_platform/app/pages/voice_scorekeeper.py` (~5 460 lines)
- Continuous listening is driven by `st.session_state.voice_listening` and `st.session_state.voice_events_enabled`.
- A `VoiceAudioProcessor` (subclass of `AudioProcessorBase`) is created via a factory stored in `st.session_state.voice_webrtc_processor_factory`.
- The `webrtc_streamer` component is rendered inside an `st.expander` with key `"voice_scorekeeper_continuous_webrtc"` and `mode=WebRtcMode.SENDONLY`.

### 2.2 Audio Pipeline
- **File:** `tournament_platform/app/services/voice_audio.py`
- `VoiceAudioBuffer` accumulates raw WebRTC frames, applies amplitude-based VAD/silence detection, and emits `AudioChunk` objects.
- `AudioChunk.to_pcm_bytes()` mixes to mono, resamples to 16 kHz, and emits int16 PCM.
- The buffer’s default `silence_threshold` is `0.01`; default `min_speech_duration_ms` is `300`; default `silence_duration_ms` is `600`.
- The worker thread skips chunks with `chunk.rms < 0.01`.

### 2.3 ASR Layer
- **Files:**
  - `tournament_platform/app/services/voice_asr.py` (`LocalASR`)
  - `tournament_platform/app/services/asr_backends/faster_whisper_backend.py` (`FasterWhisperBackend`)
  - `tournament_platform/app/services/asr_backends/factory.py` (`ASRBackendFactory`)
- Continuous listening uses `ASRBackendFactory.create()` which returns a `FasterWhisperBackend` wrapping the existing `LocalASR`.
- `FasterWhisperBackend.transcribe_pcm()` delegates to `LocalASR.transcribe_chunk()`, which writes a temporary mono 16 kHz int16 WAV and calls `faster-whisper`.
- Push-to-talk uses `LocalASR` directly (`st.session_state.voice_asr`).

### 2.4 Parser
- **Files:**
  - `tournament_platform/app/services/voice_parser.py` (legacy `VoiceParser` — now delegates to `commands.parse()`)
  - `tournament_platform/app/services/voice/commands.py` (`VoiceCommandGrammar`)
- Parser tests **pass** for all affected commands:
  - `"point red"` → `SCORE_POINT`, player B, confidence 0.85
  - `"blue point"` → `SCORE_POINT`, player A, confidence 0.85
  - `"blue scores"` → `SCORE_POINT`, player A, confidence 0.85
  - `"red scores"` → `SCORE_POINT`, player B, confidence 0.85
  - `"score five four"` → `SET_SCORE` (5-4), confidence 0.80
  - `"undo"` → `UNDO`, confidence 0.90

### 2.5 Router
- **File:** `tournament_platform/app/services/voice/command_router.py`
- Router tests **pass**: confidence gating (threshold 0.5), duplicate suppression (cooldown 1 200 ms), game-index-aware dedupe, and policy decisions all behave correctly.
- Route decisions: `REJECT`, `CONFIRM`, `APPLY`, `IGNORE`.

### 2.6 Scoring Integration
- **File:** `tournament_platform/services/match_manager.py`
- `MatchManager.apply_voice_event()` routes to `_add_point()`, `_set_score()`, or `undo_last_point()`.
- `_add_point()` delegates to `score_engine.add_point()`, which validates `match_status != "match_won"` and `player in ("A", "B")`, then updates state.
- Manual buttons (`➕ A`, `➖ B`, etc.) call the same `MatchManager` methods and are reported to work.

### 2.7 Live Scoreboard Update Path
- The scoreboard reads directly from `st.session_state.match_manager.state.score_a` / `score_b`.
- `_process_voice_events()` is called **after** the scoreboard is rendered (line ~5 174). Accepted commands call `_request_voice_rerun("applied")`, which triggers a rerun so the scoreboard reflects the new state on the next render cycle.
- A heartbeat (`_maybe_voice_heartbeat()`) runs at the end of the render and also triggers periodic reruns while listening.

### 2.8 Color / Player Mapping (VERIFIED)
- **UI display** (`voice_scorekeeper.py`):
  - Player A score is rendered with `color:#0066FF` (blue)
  - Player B score is rendered with `color:#FF6D00` (orange/red-orange)
- **Parser mapping** (`commands.py`):
  - `blue` → Player A
  - `red` / `orange` / `read` → Player B
- **Conclusion**: The mapping is **consistent** with the displayed scoreboard. Blue = Player A, Red/Orange = Player B. This is not reversed.

---

## 3. Most Likely Root Causes (Ranked by Likelihood)

### 3.1 [HIGH] Missing match-selection gate + silent fallback to default players
`apply_score_event_and_refresh_ui()` does **not** validate that `voice_selected_match_id` is set. When no match is selected, the `MatchManager` silently operates on its default engine (`Player A` vs `Player B`, 0-0). This does not cause rejection by itself, but it means:
- Voice commands appear to do nothing useful (operator is watching a different match).
- The existing test `test_no_match_selected_shows_clear_error` expects a failure when no match is selected, confirming this gate is **missing**.
- If the operator has selected a match but the match state is not propagated to the `MatchManager` (e.g., player prefill failed), the voice command updates the wrong match and the operator perceives it as “rejected / no change.”

### 3.2 [HIGH] Stale score capture in `_process_voice_events`
```python
_current_score_a = st.session_state.match_manager.state.score_a
_current_score_b = st.session_state.match_manager.state.score_b
...
for raw_text, text, event in events:
    result = apply_score_event_and_refresh_ui(
        ...,
        current_score_a=_current_score_a,
        current_score_b=_current_score_b,
    )
```
Scores are captured **once** before the loop. If multiple events are queued, every event after the first uses stale scores. This breaks deuce validation and can cause `set_score` commands to be rejected by `score_engine.set_score()` (which validates bounds) or produce incorrect server recomputation.

### 3.3 [HIGH] Manual and voice paths do not share the same scoring wrapper
Manual buttons call `st.session_state.match_manager._add_point("A")` directly. Voice commands call `apply_score_event_and_refresh_ui()` → `parse_command()` → `route_and_update_context()` → `mm.apply_voice_event()` → `mm._add_point()`.
While both eventually reach `MatchManager._add_point()`, the voice path adds parser/router/confirmation layers that the manual path bypasses. If any layer in the voice path rejects or drops the command, the operator sees “rejected” while the manual button works.

### 3.4 [MEDIUM] Match context mismatch
`voice_selected_match_id`, the active/current match ID used by MatchManager, and the match ID rendered on the scoreboard may refer to different matches. If they do not match, the voice command updates one match while the operator watches another, appearing as “nothing happens.”

### 3.5 [MEDIUM] WebRTC processor recreation on rerun
The `webrtc_streamer` is inside an expander. Although the key is stable, Streamlit’s component tree can recreate the processor when:
- The `media_stream_constraints` dict identity changes between reruns (it is rebuilt as a local variable each render).
- `async_processing=True` combined with `SENDONLY` mode causes the component to reset its internal audio track after certain browser events.
If the processor is recreated, the background worker thread, `_chunk_queue`, and `event_queue` are all lost. Any chunks already buffered or events already queued vanish silently. The operator sees “listening” UI but no transcripts are ever processed.

### 3.6 [MEDIUM] Noise gate / worker RMS floor filtering out all speech
- `VoiceAudioBuffer` default `noise_gate_rms` in continuous mode is `0.01` (when filtering is off) or the user-configured `VOICE_NOISE_THRESHOLD` (when filtering is on).
- The worker thread additionally hard-codes `if chunk.rms < 0.01: return`.
If the environment is noisy or the mic gain is low, every emitted chunk can fall below `0.01` RMS and be dropped by the worker. The buffer may still show audio frames moving (VAD reacts to `silence_threshold = 0.01`), but no transcription ever occurs.

### 3.7 [LOW] Worker thread dies silently and is not restarted
If `_get_asr()` returns `None` (ASR unavailable), the worker loop `break`s. `_enqueue_chunk()` calls `_start_worker()` before enqueueing, which would spawn a new thread if the old one is dead. However, if `ASRBackendFactory.create()` raises an uncaught exception during the *first* call, the factory is never stored and the worker never starts. The UI would show `"ASR unavailable"` rather than silently rejecting.

---

## 4. Files Inspected

| File | Purpose |
|------|---------|
| `tournament_platform/app/pages/voice_scorekeeper.py` | Main page, WebRTC processor, event loop, scoring integration |
| `tournament_platform/app/services/voice_audio.py` | Audio buffering, VAD, chunk emission, PCM conversion |
| `tournament_platform/app/services/voice_asr.py` | LocalASR wrapper, lazy model loading, WAV writing |
| `tournament_platform/app/services/asr_backends/faster_whisper_backend.py` | Backend adapter used by continuous listening |
| `tournament_platform/app/services/asr_backends/factory.py` | ASR backend selection logic |
| `tournament_platform/app/services/voice/commands.py` | VoiceCommandGrammar, intent patterns, color aliases |
| `tournament_platform/app/services/voice/command_router.py` | Duplicate suppression, confidence gating, policy routing |
| `tournament_platform/app/services/voice/confirmation.py` | Confirmation policy (apply/confirm/reject) |
| `tournament_platform/app/services/voice_parser.py` | Legacy parser (delegates to `commands.py`) |
| `tournament_platform/app/services/voice_vocab.py` | Vocabulary loading and transcript post-processing |
| `tournament_platform/app/services/score_engine.py` | Pure scoring rules, `add_point`, `set_score` |
| `tournament_platform/services/match_manager.py` | Match state mirror, `apply_voice_event` |
| `tests/test_voice_score_pipeline.py` | Integration-style tests for voice pipeline |
| `tests/test_voice_command_router.py` | Router unit tests |
| `tests/test_voice_parser.py` | Parser unit tests (92 tests, all passing) |

---

## 5. Files Likely to Modify

| File | Reason |
|------|--------|
| `tournament_platform/app/pages/voice_scorekeeper.py` | Add debug text injector, shared `process_voice_transcript()`, match-selection validation, stale score fix, debug panel, dry-run card, pre-render event processing |
| `tournament_platform/app/services/voice/commands.py` | Only if debug injector proves parser failure |
| `tournament_platform/app/services/voice/command_router.py` | Surface structured rejection reasons |
| `tournament_platform/app/services/voice_vocab.py` | Only if debug injector proves post-processing failure |
| `tests/test_voice_score_pipeline.py` | Fix import mocking; add Phase 0 text-command tests, rerun-survival tests, match-mismatch tests |
| `tests/test_voice_command_router.py` | Add tests for no-match-selected rejection once gate is added |
| `tests/test_voice_color_mapping.py` | **NEW** — verify color-to-player mapping matches displayed scoreboard |

---

## 6. Proposed Minimal Fix Plan

### Phase 0 — Prove Non-Audio Voice Command Path (BLOCKING)

**Do not touch WebRTC, ASR, VAD, noise gate, or worker threads until this phase passes.**

#### 6.1 Create Shared Processor: `process_voice_transcript()`

Create exactly **one** function that all voice paths must use:

```python
def process_voice_transcript(
    transcript: str,
    selected_match_id: Optional[int],
    source: str = "debug",
) -> VoiceProcessResult:
    """
    Central voice command processor.

    Steps:
    1. Validate match context (voice_selected_match_id == active match == scoreboard match).
    2. Normalize transcript.
    3. Parse with VoiceParser / VoiceCommandGrammar.
    4. Route with CommandRouter.
    5. If APPLY, call MatchManager.apply_voice_event().
    6. Return structured result for UI display.

    Used by:
    - debug text injector
    - push-to-talk
    - continuous listening worker
    """
```

**Non-negotiable requirement**: All three paths (debug text, push-to-talk, continuous listening) must call this single function. No separate voice scoring logic is allowed.

#### 6.2 Add Debug Text Command Injector

In the Voice Scorekeeper page, add a developer-only section:

- Text input: `"Debug voice command"`
- Button: `"Run voice command"`
- This bypasses microphone and ASR entirely.
- It calls `process_voice_transcript(text, st.session_state.voice_selected_match_id, source="debug")`.
- It uses the **exact same** parser, router, MatchManager, ScoreEngine, persistence, rerun, and scoreboard refresh path as real voice commands.

#### 6.3 Add Voice Dry-Run Result Card

Before actual scoring, display the interpreted command:

**For accepted commands:**
```
Heard: "point red"
Parsed: SCORE_POINT
Target: Player B / red-orange side
Decision: APPLY
Previous score: 0–0
New score: 0–1
```

**For rejected commands:**
```
Heard: "point red"
Parsed: SCORE_POINT
Decision: REJECT
Reason: no_match_selected
```

This makes the bug obvious in the UI.

#### 6.4 Test the Following Typed Commands

Verify each updates the selected match:
- `"point red"` → Player B (red/orange side) score increments
- `"point blue"` → Player A (blue side) score increments
- `"red point"` → Player B score increments
- `"blue scores"` → Player A score increments
- `"score five four"` → score sets to 5-4 (with confirmation if policy requires)
- `"undo"` → last point reversed

#### 6.5 Hard Stop After Phase 0

After implementing the debug text injector, **stop and report**:
- Does "point red" update score?
- Does "point blue" update score?
- Does "undo" work?
- What exact function updates the score?
- What state does the scoreboard read?
- What tests passed?

**Do not continue to Phase 1+ until these are proven.**

---

### Phase 1 — Hard Blocker: No Match Selected + Match Context Mismatch

**Non-negotiable requirement.** Voice scoring must never silently use a default Player A vs Player B match.

#### 1.1 Match-Context Validation

Before applying any voice command, verify:

1. `voice_selected_match_id` exists
2. The active/current match ID in MatchManager matches `voice_selected_match_id`
3. The scoreboard-rendered match ID matches `voice_selected_match_id`

If any do not match, reject with:
```
reason: "voice_match_context_mismatch"
```

#### 1.2 No-Match-Selected Gate

At the top of `process_voice_transcript()`:
```python
if not selected_match_id:
    return VoiceProcessResult(
        success=False,
        reason="no_match_selected",
        ...
    )
```

- Show `"Voice command ignored: no active match selected"` in the UI.
- Do not update default `MatchManager` state.
- Do not call `ScoreEngine`.

#### 1.3 Tests
- `test_no_match_selected_rejects_with_clear_reason`
- `test_voice_match_context_mismatch_rejected`
- `test_voice_selected_match_survives_rerun`
- `test_voice_event_not_applied_twice_after_rerun`

---

### Phase 2 — Fix Stale Score Capture

In `_process_voice_events()`, capture `_current_score_a` / `_current_score_b` **inside** the loop (or re-read from `match_manager.state` after each successful apply) so that batch-processed events always use the latest scores.

Also: **process voice events BEFORE rendering the scoreboard**.

Current order:
1. render scoreboard
2. process voice events
3. rerun

New order:
1. initialize state
2. consume pending voice events via `process_voice_transcript()`
3. apply official score update
4. reload match state
5. render scoreboard
6. rerun only if needed

This reduces the chance that accepted commands feel delayed or invisible.

---

### Phase 3 — Surface Structured Rejection Reasons

Order of debugging must be:
1. Is transcript empty?
2. Is normalized transcript valid?
3. Did parser accept it?
4. Did router accept it?
5. Was match selected?
6. Did match context match?
7. Did ScoreEngine update?
8. Did scoreboard reload?

**Only after** the debug panel confirms the failure layer should thresholds be adjusted.

#### 3.1 Structured Rejection Reasons

Log structured rejection reasons to `st.session_state.last_voice_feedback`:
- `unknown_intent`
- `low_confidence:<value>`
- `duplicate_suppressed`
- `no_match_selected`
- `voice_match_context_mismatch`
- `policy_rejected`
- `match_already_decided`
- `disposition:<reason>`

#### 3.2 Debug Panel

Add a collapsible **“🩺 Voice Diagnostics”** panel showing:
- Listening mode
- Active match ID
- Last raw transcript
- Last normalized transcript
- Parser intent + confidence
- Router decision + reason
- Rejection reason
- Worker thread alive / dead status
- Event queue depth

#### 3.3 Clear Stale UI on Start

In `_enable_continuous_listening()`, reset:
- `last_voice_transcript`
- `last_voice_event`
- `last_voice_feedback`

---

## 7. Parser / Router Changes (Only If Tests Fail)

**Do not modify `VoiceCommandGrammar` unless the debug text injector proves parser failure.**

If parser already accepts:
- `"point red"`
- `"point blue"`
- `"red point"`
- `"blue scores"`
- `"score five four"`
- `"undo"`

…then do not refactor parser patterns in this bug-fix PR. The parser tests already pass for these commands.

Only if debug injector shows parser rejection:
- Add explicit multi-word point patterns to `commands.py`
- Harden `_extract_score_pair` robustness
- Strip punctuation in `voice_vocab.py` post-processor

---

## 8. Scoring Integration Changes

| Change | Description |
|--------|-------------|
| Shared `process_voice_transcript()` | Single function used by debug text, push-to-talk, and continuous listening |
| Match context validation | Verify three IDs match before scoring |
| Re-read scores inside event loop | After each successful apply, re-read `mm.state.score_a/b` |
| Pre-render event processing | Process voice events before rendering scoreboard |
| Clear stale UI on start | Reset voice feedback state when listening starts |

**Do not add `apply_scoring_action()` to `match_manager.py` unless it removes duplicate logic without changing existing behavior.** Prefer reusing existing `MatchManager` public methods first.

---

## 9. Audio / ASR / WebRTC Changes

**DO NOT IMPLEMENT IN THIS PASS.**

These are deferred until Phase 0–3 prove the text path works:
- Configurable worker RMS floor
- Chunk metadata on debug panel
- Test Mic button
- WebRTC processor recreation fixes
- Worker restart safety

---

## 10. Test Plan

### 10.1 Phase 0 Tests (BLOCKING)
| Test | Description |
|------|-------------|
| `test_debug_text_command_point_red` | Typed `"point red"` via debug input updates Player B score |
| `test_debug_text_command_point_blue` | Typed `"point blue"` via debug input updates Player A score |
| `test_debug_text_command_red_point` | Typed `"red point"` updates Player B score |
| `test_debug_text_command_blue_scores` | Typed `"blue scores"` updates Player A score |
| `test_debug_text_command_score_five_four` | Typed `"score five four"` sets score (with confirmation if required) |
| `test_debug_text_command_undo` | Typed `"undo"` reverses last point |
| `test_debug_text_command_no_match_selected` | Typed command with no match selected shows clear error |
| `test_process_voice_transcript_shared_path` | Verify debug, push-to-talk, and continuous all call same function |

### 10.2 Phase 1–3 Tests
| Test | Description |
|------|-------------|
| `test_no_match_selected_rejects_with_clear_reason` | `apply_score_event_and_refresh_ui` returns `success=False, reason="no_match_selected"` |
| `test_voice_match_context_mismatch_rejected` | Mismatched match IDs are rejected |
| `test_voice_selected_match_survives_rerun` | Selected match remains selected after rerun |
| `test_voice_event_not_applied_twice_after_rerun` | Same event ID does not increment score twice |
| `test_process_voice_events_uses_live_scores` | Second event in batch uses updated scores |
| `test_rejection_reason_surface` | `last_voice_feedback` contains exact router reason |
| `test_post_processor_strips_punctuation` | `"point red."` and `"blue scores!"` parse correctly |
| `test_color_mapping_matches_scoreboard` | Parser `blue→A`, `red→B` matches UI `#0066FF` (A) and `#FF6D00` (B) |

### 10.3 Existing Tests
- Fix `tests/test_voice_score_pipeline.py` import mocking so tests run.
- Ensure `tests/test_voice_parser.py` (92 tests) still pass.
- Ensure `tests/test_voice_command_router.py` (18 tests) still pass.
- Ensure `tests/test_voice_asr.py` (14 tests) still pass.

---

## 11. Manual QA Checklist

1. **Enable Voice Scoring** → toggle on.
2. **Select a match** → pick an active/pending match from the selector.
3. **Debug text injector** → type `"point red"` and click **Run voice command**:
   - Verify dry-run card shows `SCORE_POINT`, `APPLY`, target Player B.
   - Verify Player B (red/orange side) score increments.
   - Verify live scoreboard updates.
4. **Debug text injector** → type `"point blue"`:
   - Verify dry-run card shows target Player A.
   - Verify Player A (blue side) score increments.
5. **Debug text injector** → type `"undo"`:
   - Verify last point is reversed.
6. **Clear selected match** → verify debug commands show `"Voice command ignored: no active match selected"`.
7. **Push-to-talk** → verify it still works and produces the same result as the debug injector.
8. **Manual buttons** → verify `➕ A`, `➖ B`, undo, reset still work.
9. **Match context mismatch** → verify rejection if match IDs diverge.

---

## 12. Acceptance Criteria

- [ ] **Phase 0**: Typed debug command `"point red"` updates the selected match’s Player B score.
- [ ] **Phase 0**: Typed debug command `"point blue"` updates the selected match’s Player A score.
- [ ] **Phase 0**: Typed debug command `"undo"` reverses the last accepted point.
- [ ] **Phase 0**: No selected match gives a clear visible rejection: `"Voice command ignored: no active match selected"`.
- [ ] **Phase 0**: Debug text injector, push-to-talk, and continuous listening all use `process_voice_transcript()`.
- [ ] **Color mapping**: Parser `blue→A`, `red→B` matches the displayed scoreboard colors (`#0066FF` for A, `#FF6D00` for B).
- [ ] **Match context**: `voice_selected_match_id`, active match ID, and scoreboard match ID are all validated before scoring.
- [ ] **Voice events processed before scoreboard render**: Accepted commands appear on the scoreboard without an extra rerun cycle.
- [ ] **Dry-run card**: Every voice command displays parsed intent, target player, decision, previous score, and new score (or rejection reason).
- [ ] **Structured rejection reasons**: `last_voice_feedback` shows the exact reason, not a generic message.
- [ ] Manual scoring still works.
- [ ] No destructive command executes without confirmation when `VOICE_ENABLE_CONFIRMATION` is on.
- [ ] Existing match reporting (`/api/report`) is unaffected.
- [ ] All existing tests pass.
- [ ] New voice tests pass.

---

## 13. Rollback Plan

1. **Git revert** the modified commits if the fix is merged:
   ```bash
   git revert <commit-hash>
   ```
2. **Feature-flag the new validation**: wrap the `no_match_selected` gate and match-context check in a `VOICE_STRICT_MODE` or new `VOICE_REQUIRE_MATCH` flag so it can be disabled without reverting.
3. **Restore factory defaults**: if noise-gate or RMS thresholds are changed later, ensure they can be overridden via environment variables.
4. **Database / match state**: all voice scoring changes go through `MatchManager` → `ScoreEngine`, which already snapshots state for undo. No direct DB writes occur in the voice pipeline, so rollback does not require data migration.

---

## 14. Open Questions / Blockers

1. **Exact function called by manual buttons**: Need to verify whether `➕ A` calls `_add_point("A")` directly or goes through another wrapper. This determines whether the shared `process_voice_transcript()` can call the same public method.
2. **Match context source of truth**: Where is the “active match ID” authoritative? Is it `voice_selected_match_id`, `match_manager.engine` state, or a DB query? Need to verify all three sources can be compared.
3. **Exact “Voice command rejected” string**: The exact phrase does not appear in the current codebase. It may be a paraphrase of `unknown_intent`, `duplicate_suppressed`, or a commentary template. The dry-run card will reveal the exact router reason.
4. **Parser demotion trigger**: If debug injector proves parser works, Phase 4 is skipped entirely. If it fails, we add parser hardening as a separate focused change.
