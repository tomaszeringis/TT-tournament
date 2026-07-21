# Fix Continuous Voice Scoring — WebRTC Audio Processor Pipeline

## Context

The latest voice audit shows the WebRTC component enters `playing=True` but the audio processor is never created or never receives frames. The audit contains only lifecycle events (`webrtc_playing`, `no_audio_processor`) and is missing the entire audio→chunk→ASR→transcript→score pipeline. This plan fixes the WebRTC audio processor creation, frame handling, and event handoff.

## Root Cause Analysis

After inspecting `tournament_platform/app/pages/voice_scorekeeper.py` and `streamlit-webrtc==0.75.0`:

1. **`no_audio_processor` emitted too aggressively** (line ~5136): The code emits `webrtc_not_playing`/`no_audio_processor` on EVERY rerun where `ctx.audio_processor` is falsy. This is wrong because (a) it uses the wrong stage name, (b) it fires even during async initialization, and (c) it makes diagnostics useless.

2. **Trace events incorrectly marked `accepted=True`**: `_append_continuous_trace` passes `accepted=True` for all diagnostic trace events. Trace events are diagnostics, not accepted commands.

3. **Heartbeat drains the event queue** (line ~752): `_maybe_voice_heartbeat` calls `len(processor.get_events())`, but `get_events()` drains the queue. Events are lost before `_process_voice_events` can consume them.

4. **`_process_voice_events` bypasses shared transcript processor**: It calls `apply_score_event_and_refresh_ui` directly instead of `_process_voice_transcript(source="continuous")`. The task requires using the shared processor.

5. **No `continuous_event_consumed` audit stage**: The main script does not log when it drains the event queue.

6. **Missing `continuous_audio_frame_received` audit stage**: The processor has `_audio_frames_received` but no audit event when frames arrive.

7. **Processor reference not stabilized across reruns**: `_tracked_factory` is recreated every rerun, and the processor reference in `voice_webrtc_ctx` is only updated when `ctx.audio_processor` is truthy.

## Files to Modify

| File | Changes |
|------|---------|
| `tournament_platform/app/pages/voice_scorekeeper.py` | Fix diagnostics, trace events, heartbeat, event consumer, factory tracking |
| `tests/test_voice_webrtc_safe.py` | Add processor/queue tests |
| `tests/test_voice_score_pipeline.py` | Add continuous pipeline tests |

## Implementation Steps

### Step 1: Fix `_append_continuous_trace` — trace events are not accepted

In `_append_continuous_trace` (~line 549), change `accepted=True` to `accepted=False` for all trace events. Trace events are diagnostics, not accepted voice commands.

```python
def _append_continuous_trace(stage: str, note: str = "") -> None:
    _trace_event = VoiceScoreEvent(
        type="trace",
        raw_text="",
        confidence=0.0,
        timestamp=time.time(),
    )
    _append_voice_audit(
        _trace_event,
        source="continuous",
        accepted=False,  # was True — trace events are diagnostics, not accepted commands
        ...
    )
```

### Step 2: Fix processor diagnostics — differentiate exact states

Replace the block at lines ~5126–5136 with a state machine that emits precise stages:

| Condition | Stage | Note |
|-----------|-------|------|
| `ctx` is None | `component_not_mounted` | Component not rendered |
| `ctx.state.playing` is False | `webrtc_not_playing` | Mic stopped |
| `ctx.audio_processor` is None but `playing=True` | `processor_not_created` | Factory not called or failed |
| `ctx.audio_processor` exists, `_audio_frames_received == 0` | `processor_created_no_frames` | Processor attached but no frames |
| `ctx.audio_processor` exists, `_audio_frames_received > 0` | `audio_frames_received` | Pipeline working |

Do NOT emit `no_audio_processor` on every rerun. Emit it once when transitioning to `processor_not_created`, then suppress until state changes.

### Step 3: Add `continuous_audio_frame_received` audit stage

In `VoiceAudioProcessor.recv()` (~line 1800) and `recv_queued()` (~line 1812), after incrementing `_audio_frames_received`, if this is the first frame, append a trace event:

```python
if self._audio_frames_received == 1:
    _append_continuous_trace("continuous_audio_frame_received", "first_frame")
```

Throttle subsequent frame events (e.g., log every 100th frame or when RMS changes significantly) to avoid log flooding.

### Step 4: Add `has_pending_events()` to VoiceAudioProcessor

Add a non-draining queue check:

```python
def has_pending_events(self) -> bool:
    return self.event_queue.qsize() > 0
```

### Step 5: Fix heartbeat — do not drain queue

In `_maybe_voice_heartbeat()` (~line 747), replace:

```python
has_pending = len(processor.get_events()) > 0
```

with:

```python
has_pending = processor.has_pending_events()
```

### Step 6: Add `continuous_event_consumed` audit stage

In `_process_voice_events()` (~line 2475), after draining events from the processor, append:

```python
_append_continuous_trace("continuous_event_consumed", f"{len(events)}_events")
```

### Step 7: Route continuous events through shared processor

In `_process_voice_events()` (~line 2559), replace the direct `apply_score_event_and_refresh_ui` call with:

```python
result = _process_voice_transcript(
    text,
    source="continuous",
    enable_confirmation=VOICE_ENABLE_CONFIRMATION,
)
```

Update downstream code to handle dict result from `_process_voice_transcript` instead of `ScoreApplyResult`:
- `result.success` → `result.get("success")`
- `result.reason` → `result.get("reason")`
- `result.parsed` → `result.get("parsed")`
- `result.parsed.type` → check dict access

### Step 8: Stabilize factory and processor reference

Store `_tracked_factory` in `st.session_state` so it is not recreated on every rerun. Update the processor reference in `voice_webrtc_ctx["processor"]` on every run when `ctx.audio_processor` is available.

Add module-level diagnostics:

```python
class VoiceProcessorRegistry:
    latest_processor: VoiceAudioProcessor | None
    created_count: int
    last_error: str | None
```

But keep it simple — use `st.session_state` keys with a lock for thread safety from the factory.

### Step 9: Add explicit diagnostics

In the mic status panel and diagnostics expander, add:

- `audio_processor_factory called count`
- `audio_processor_factory last error`
- `processor constructor called count`
- `processor id`
- `processor class name`
- `processor callback/recv called count`
- `last processor exception`
- `webrtc_playing: yes/no`
- `audio_frames_received`
- `chunks_created`
- `dropped_chunks`
- `last_frame_timestamp`
- `last_chunk_timestamp`
- `asr_ready`
- `asr_error`

### Step 10: Fix stale event handling in `_process_voice_events`

Ensure every continuous event includes `session_id`. Before processing, reject events with:
- `stale_event_old_session`
- `stale_event_before_session_start`
- `stale_event_after_stop`
- `duplicate_event_id`

These already exist in the code but should be verified to work correctly after the pipeline fix.

## Tests to Add/Update

### `tests/test_voice_webrtc_safe.py`

- `test_has_pending_events_true_when_events_queued`
- `test_has_pending_events_false_when_empty`
- `test_trace_event_not_accepted`

### `tests/test_voice_score_pipeline.py`

- `test_continuous_event_enqueued_audit_stage`
- `test_continuous_event_consumed_audit_stage`
- `test_process_voice_events_calls_shared_processor`
- `test_processor_callback_increments_frame_count`
- `test_webrtc_playing_with_no_processor_reports_processor_not_created`
- `test_processor_created_but_no_frames_reports_processor_created_no_frames`
- `test_chunk_enqueue_starts_worker`
- `test_asr_transcript_creates_continuous_event`
- `test_main_consumer_calls_process_voice_transcript_continuous`
- `test_continuous_transcript_point_blue_updates_player_a`
- `test_continuous_transcript_point_red_updates_player_b`
- `test_stale_old_session_events_ignored`
- `test_manual_scoring_still_works`
- `test_push_to_talk_still_works`
- `test_debug_text_scoring_still_works`

## Manual QA

1. Open Voice Scorekeeper, select active match.
2. Confirm debug text "point blue" updates score.
3. Confirm push-to-talk still works.
4. Open Experimental Continuous Listening, click WebRTC START.
5. Confirm diagnostics show `playing: yes`, `processor created count > 0`, `processor id not empty`.
6. Speak — confirm `audio frame count increasing`, `last audio frame timestamp updated`, `RMS changing`.
7. Say "point blue" — confirm `chunk created` or `ASR started`, `transcript received`, `continuous event enqueued`, `continuous event consumed`, `process_voice_transcript source=continuous`, `score_update_success`.
8. Confirm scoreboard updates.
9. Say "point red" — confirm Player B score updates.
10. Say "undo" — confirm last point undone.
11. Stop WebRTC — confirm old events ignored.
12. Export audit — confirm it includes audio-frame/chunk/ASR/transcript/event/score stages.

## Acceptance Criteria

- WebRTC START/STOP UI works.
- When `playing=True`, `VoiceAudioProcessor` is created.
- Audio frame callback is invoked.
- Diagnostics show audio frame count and processor id.
- Audit includes audio-frame/chunk/ASR stages.
- Continuous transcript events are enqueued and consumed.
- Continuous transcript "point blue" updates scoreboard.
- Continuous transcript "point red" updates scoreboard.
- Trace events are not incorrectly marked `accepted=true`.
- If continuous fails, diagnostics identify exact layer.
- Debug text scoring still works.
- Push-to-talk still works.
- Manual scoring still works.
- Existing tests pass.
- New relevant tests pass.

## Completion Report Requirements

Report:
- why audit previously showed only `webrtc_playing` / `no_audio_processor`
- whether `audio_processor_factory` was called
- whether processor callback was called
- what exact callback method was fixed
- how audio frames are counted
- how continuous transcript events are enqueued
- how main Streamlit script consumes events
- exact manual QA result for "point blue"
- tests added/passed
