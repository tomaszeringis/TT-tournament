# Voice Scorekeeper — Continuous Listening Rejects Every Command

## Summary of observed problem
- Continuous listening shows "Last update: Voice command rejected." for every spoken command.
- No point is added, no score change, live scoreboard unchanged.
- "Continuous listening appears to hear/process something" → audio IS captured and chunks ARE transcribed; events reach the router, but are rejected.
- Manual scoring works; push-to-talk is the documented fallback.

## Current voice pipeline findings (traced)
1. **Page loop** (`app/pages/voice_scorekeeper.py`):
   - `VoiceAudioProcessor` (subclass of `AudioProcessorBase`) receives WebRTC frames in `_ingest_frame` → buffers in `VoiceAudioBuffer` → on a complete chunk queues it to a single worker thread → `transcribe_pcm` → `post_processor.process` → `self.parser.parse` (legacy, only for metadata) → `event_queue`.
   - Main thread `_process_voice_events()` (line 960) drains the queue, **re-parses with `parse_command(text, ...)`** (the grammar in `voice/commands.py`), then routes through `route_and_update_context()`.
   - On `RouteDecision.REJECT` it sets `st.session_state.last_voice_feedback = "Voice command rejected"` (line 1041) — this is the exact message seen.
2. **Router** (`voice/command_router.py`): REJECT only when intent is `UNKNOWN`, `disposition` set, `confidence < 0.5`, or `policy_decision == "reject"`. A valid `SCORE_POINT` with confirmation ON returns `CONFIRM` (goes to the confirmation panel), NOT reject. So "rejected" ⇒ the transcript parsed to `UNKNOWN`/low-confidence.
3. **Parser / grammar is correct and tested**: `tests/test_voice_parser.py` golden corpus (lines 359-386) confirms `"point red"→B`, `"point blue"→A`, `"red point"→B`, `"blue scores"→A`, `"score five four"→set_score(5,4)`, `"undo"→undo`. Therefore the parser is NOT the root cause.
4. **ASR path for continuous mode**: `_transcribe_chunk` → `self.asr.transcribe_pcm(pcm_bytes)` → `FasterWhisperBackend.transcribe_pcm` → `LocalASR.transcribe_chunk` (writes mono/16k/int16 WAV, then faster-whisper). This is the SAME `LocalASR` used by push-to-talk, so the model itself is not the differentiator — the **audio bytes fed in** are.
5. **Audio→PCM conversion** (`voice_audio.py` `AudioChunk.to_pcm_bytes`): decodes frames by `sample_format`, mixes stereo→mono, resamples via crude `np.interp` 48k→16k, converts float32/int16→int16. Sample rate / channels / format are mutated **mid-chunk** by `_ingest_frame` calling `audio_buffer.update_format(...)` whenever a frame's detected format differs. A mid-chunk format change makes `to_pcm_bytes` decode a mixed-type buffer as one type → corrupted PCM → whisper returns filler/garbage.
6. **VAD is effectively dead** (`voice/vad.py`): `create_vad()` defaults to `WebRTCVAD` (aggressiveness 2). Its `is_speech` is fed **float32 bytes but expects int16**, and `_infer_frame_duration_ms` assumes int16 (`len//2`) so for float32 frames it computes a wrong duration that is never in {10,20,30}ms ⇒ it always returns `False` (exception also swallowed). Result: `is_speech` falls back to amplitude-only (`rms > 0.01`). Speech detection is coarse; chunks are emitted largely on the 3000 ms max-duration timer, frequently on near-silent/ambient audio.
7. **Confirmation default** (`services/settings.py:92`): `VOICE_ENABLE_CONFIRMATION` defaults to `True`. So even a *correctly transcribed* simple point goes to the CONFIRM panel and needs a manual click; it is never auto-applied in continuous mode. This compounds the "nothing happens" perception.
8. **Scoreboard source is correct**: the live scoreboard renders `st.session_state.match_manager.state` directly, and `MatchManager.apply_voice_event` (match_manager.py:252) mutates that same engine state, then the loop `st.rerun()`s. So once a valid event actually reaches `apply_voice_event`, the scoreboard updates. There is **no separate stale scoreboard source** to fix — the failure is upstream (commands never reach `apply_voice_event`).

## Most likely root causes (ranked)
1. **(HIGH) Corrupted/incorrect PCM in continuous mode.** Fragile format detection + mid-chunk `update_format` + crude resample ⇒ whisper receives garbage (wrong sample rate / dtype / interleaving) and returns filler text that the grammar maps to `UNKNOWN` → router REJECT → "Voice command rejected." This is the single best explanation for "every command rejected, push-to-talk works."
2. **(HIGH) VAD always returns False** for float32 frames, so chunking relies on a coarse amplitude gate + a 3 s max-duration timer. Long silent stretches still get emitted as chunks, transcribed as filler → reject. Also wastes ASR on silence.
3. **(MEDIUM) Confirmation-on-by-default UX**: even correctly parsed simple points only reach the confirmation panel; without a click, no score change. Acceptable per constraints (risky needs confirmation), but safe points should be auto-applied when confirmation is disabled, and the pending card must be visible/prominent.
4. **(LOW) Rejection reason not surfaced to the user.** The caption shows a generic "Voice command rejected"; the actual `route_result.reason` is only in a `st.warning` (line 1042). Hard for operators to diagnose.
5. **(LOW) Duplicate/cooldown interaction.** Verified not the cause of REJECT (duplicates yield IGNORE/"Duplicate suppressed"), but the page reruns every ~0.1 s while listening and there are two independent cooldown checks (router + page) — keep an eye during QA.

## Files inspected
- `app/pages/voice_scorekeeper.py` (full) — UI, `VoiceAudioProcessor`, `_process_voice_events`, `_process_push_to_talk_audio`, `_apply_pending`, scoring UI.
- `app/services/voice_parser.py` — legacy `VoiceParser` (delegates to grammar).
- `app/services/voice/commands.py` — `VoiceCommandGrammar` / `parse` (the real parser); golden behavior confirmed correct.
- `app/services/voice/parse_result.py` — `VoiceParseResult` → `VoiceScoreEvent`.
- `app/services/voice/command_router.py` — `route_command` / `route_and_update_context`; rejection conditions.
- `app/services/voice/confirmation.py` — `ConfirmationPolicy` / state machine; confirmation default.
- `app/services/voice_audio.py` — `AudioChunk.to_pcm_bytes`, `VoiceAudioBuffer`, format mid-chunk mutation.
- `app/services/voice_asr.py` + `asr_backends/factory.py` + `faster_whisper_backend.py` + `asr_backends/base.py` — ASR path (shared with push-to-talk).
- `app/services/voice/vad.py` — `create_vad`, `WebRTCVAD.is_speech` (float32/int16 mismatch).
- `app/services/voice_vocab.py` — `TranscriptPostProcessor` (no-op with empty vocab; not destructive).
- `services/settings.py` — `VOICE_ENABLE_CONFIRMATION=True`, ASR model/device/compute defaults.
- `services/match_manager.py` (`apply_voice_event`) — correct routing to engine.
- `tests/test_voice_parser.py`, `tests/voice/test_aliases.py`, `tests/test_voice_audio.py` — existing coverage.

## Files likely to modify
- `app/services/voice_audio.py` — make PCM conversion deterministic/robust; force final 16 kHz mono int16; reject/flush empty chunks; guard mid-chunk format changes.
- `app/services/voice/vad.py` — default to `AmplitudeVAD` (or fix `WebRTCVAD` to accept the actual frame dtype/duration); ensure VAD actually gates speech.
- `app/pages/voice_scorekeeper.py` — surface `route_result.reason` in the caption; add always-available lightweight debug panel; ensure safe points auto-apply when confirmation disabled; tune chunk thresholds.
- `app/services/voice/command_router.py` (minor) — keep, but ensure `reason` strings are clear/actionable.
- `services/settings.py` (maybe) — document/optional default for experimental continuous confirmation.

## Proposed minimal fix plan (staged, instrument-first)
**Stage 0 — Debug visibility (ship first, low risk):**
- Add a lightweight, always-on "Voice Debug" panel on the voice page (not gated by `VOICE_DEBUG_EVENTS`) showing, per event: listening mode, active match id, chunk duration ms, sample rate/channels/format, chunk RMS, ASR raw transcript, normalized transcript, parser intent, confidence %, router decision + `reason`, previous→proposed score, final action. Reuse `voice_event_logger` for the audit ring.
- In `voice_scorekeeper.py:1041` change the caption to include `route_result.reason` (e.g., "Voice command rejected: unknown_intent").
- Log (debug) the exact PCM bytes length/sample-rate handed to `transcribe_pcm` so corruption is visible.

**Stage 1 — Harden audio→PCM (primary fix):**
- In `_ingest_frame` / `VoiceAudioBuffer`: detect frame format/dtype **once and consistently** (prefer `frame.to_ndarray().dtype` + true sample_rate). Do NOT mutate `sample_format`/`sample_rate` mid-chunk; if a frame differs, flush the current chunk first, then switch. Add an invariant assertion in `to_pcm_bytes` that output is 16 kHz mono int16 and non-empty-silent.
- Replace/keep the resampler but make it robust; prefer `av` (already a dependency) for resample+mono+dtype conversion for parity with push-to-talk (`_audio_input_to_pcm`).
- Drop chunks whose mean RMS is below a small floor (avoids transcribing pure silence/ambient).

**Stage 2 — Fix VAD / chunking:**
- Default `create_vad()` to `AmplitudeVAD` (reliable, dtype-correct) for the experimental path, or fix `WebRTCVAD.is_speech` to receive int16 of correct duration. Keep aggressiveness modest.
- Tune thresholds: `min_speech_duration_ms` ~250–350, `silence_duration_ms` ~400, and ensure emission only happens when speech was detected (avoid 3 s timer firing on silence).
- Flush remaining buffer on `stop()` (already present) and after a long silence.

**Stage 3 — Routing/UX parity:**
- Confirm push-to-talk and continuous both flow through `parse_command` + `route_and_update_context` (they do). Add a test proving identical transcripts route identically.
- **Continuous mode auto-applies safe `SCORE_POINT`** (no confirmation), so a spoken "point red" updates the score immediately. Implement by having the continuous path set `enable_confirmation=False` (or strip the confirm decision for `SCORE_POINT`) for simple points only, while push-to-talk keeps honoring `VOICE_ENABLE_CONFIRMATION`.
- **Risky commands always require confirmation** (`SET_SCORE`, match-lifecycle, admin) regardless of the flag — protected by `ConfirmationPolicy` safety levels + `requires_confirmation` already in `confirmation.py`.
- The confirmation card stays visible/prominent; a single click applies and the existing loop `st.rerun()` refreshes the scoreboard.

## Parser/router changes needed
- **None required for the listed commands** — the grammar already handles them (verified by golden tests). Do not add redundant aliases that could expand the false-positive surface.
- Optionally add `point red`/`red point`/`point blue`/`blue scores` as explicit golden entries in the router/integration tests (parser golden already covers them).
- Ensure `reason` strings are human-readable ("unknown_intent", "low_confidence:0.30", "policy_rejected", "duplicate_suppressed") and are surfaced in the UI caption.

## Audio/ASR changes needed
- Deterministic final PCM: **16 kHz, mono, int16** for both continuous and push-to-talk (parity).
- Correct, stable format detection; no mid-chunk `update_format`.
- Robust resampling (reuse `av`, as push-to-talk does).
- VAD that actually works for the delivered frame dtype; amplitude fallback only.
- Silence/RMS gating so near-empty chunks are not transcribed.

## Scoreboard update changes needed
- **None structurally**: scoreboard reads `match_manager.state` (the official engine state) and `apply_voice_event` updates it; the loop `st.rerun()` refreshes it. Verify in QA that after a valid continuous command the displayed score increments. Keep `persist_voice_match_to_db` for selected-match persistence.

## Debug visibility plan
- New always-on expander "🔍 Voice Debug" on the voice page with the fields listed in Stage 0. Toggleable off via `VOICE_DEBUG_EVENTS=False` for spectators (default hidden in prod, visible in dev).
- Per-event structured logging via existing `EventLogger` (gated by `VOICE_DEBUG_EVENTS`).
- Expose: raw transcript, normalized transcript, ASR error, ASR latency ms, chunk duration ms, sample rate, channels, format, chunk RMS, parser intent, confidence, rejection reason, router decision, previous/new score, final action, scoreboard-update result.

## Test plan (add alongside fix)
- **Audio (`tests/test_voice_audio.py`):** feed a known-good 16k mono int16 sine blob through `to_pcm_bytes` and assert bytes unchanged; feed 48k stereo float32 and assert it becomes ~16k mono int16 (correct length/values); assert mid-chunk format change flushes instead of corrupting; assert near-silent chunk is rejected/dropped.
- **VAD (`tests/test_voice_vad.py`):** `WebRTCVAD.is_speech` with correct int16 input returns True on speech frames; `AmplitudeVAD` works for float32 and int16.
- **Grammar/router (`tests/test_voice_parser.py`, `test_voice_command_router.py`):** add the explicit required phrases as golden/integration cases (`point red`, `point blue`, `red point`, `blue scores`, `score five four`, `undo`) asserting intent + slots.
- **Rejection clarity:** unknown phrase → `REJECT` with reason `unknown_intent` (not just generic).
- **Router:** valid `SCORE_POINT` with active match selected → `APPLY` (confirmation off) or `CONFIRM` (on); with **no** active match still routes (match selection is not required to parse, but score apply needs a match — confirm desired behavior and test accordingly); first valid command is NOT duplicate-suppressed; duplicate within cooldown IS ignored; confirmation state does not block safe points incorrectly; risky commands still require confirmation.
- **Engine/scoreboard:** a valid `increment` event via `MatchManager.apply_voice_event` increments the correct player and `match_manager.state.get_score_string()` reflects it.
- **Parity:** identical transcript string routed identically from push-to-talk and continuous paths.
- **Regression:** risky `SET_SCORE`/match-lifecycle/admin commands still require confirmation.

## Manual QA checklist
1. `streamlit run` the app; open Voice Scorekeeper; enable Voice Scoring; select an active match; set two players.
2. Start continuous listening; open the debug panel.
3. Say "point red" → expect blue/Player B? (note: color alias maps red→B) — verify intent + score increment (after confirm if on).
4. Say "point blue", "red point", "blue scores", "score five four", "undo" → verify each.
5. Verify ASR raw/normalized transcript in debug panel; verify chunk sample rate shows 16000 and RMS > 0 for real speech.
6. Verify "Voice command rejected" now shows a reason.
7. Confirm manual +/- buttons still work; push-to-talk still works.
8. Confirm risky set-score still shows confirmation card and does not apply without confirm.
9. Confirm live scoreboard updates after an accepted voice command.
10. Stop listening; confirm processor stops and no further events.

## Acceptance criteria
- Continuous listening accepts `point red`/`point blue`/`red point`/`blue scores`/`score five four`/`undo` (verified by tests + manual QA).
- `undo` reverses the last accepted point.
- "Voice command rejected" always includes a clear reason when rejection is correct.
- Valid commands are never rejected without explanation.
- Live scoreboard updates after an accepted voice command.
- Manual scoring and push-to-talk still work.
- No destructive command executes without confirmation.
- Existing `/api/report` match reporting unchanged.
- Existing tests pass; new voice tests pass.
- Debug panel can be disabled.

## Rollback plan
- All changes are additive/hardening in `voice_audio.py`, `vad.py`, and the voice page; the parser/grammar/router logic is unchanged. Revert the specific commit(s); no schema/DB/migration changes. Feature flags (`VOICE_DEBUG_EVENTS`, `VOICE_ENABLE_CONFIRMATION`, `VOICE_ENABLE_NOISE_FILTERING`) allow disabling new behavior without code changes.

## Open questions / blockers (RESOLVED)
1. **Default confirmation for experimental continuous mode — RESOLVED (both, reconciled):**
   - Safe `SCORE_POINT` commands auto-apply in continuous mode (so "updates the score" acceptance is met) — do NOT require confirmation there.
   - Risky commands (`SET_SCORE`, match-lifecycle, admin) ALWAYS require confirmation regardless of `VOICE_ENABLE_CONFIRMATION` (protected by `ConfirmationPolicy` safety levels + `requires_confirmation`).
   - `VOICE_ENABLE_CONFIRMATION` remains honored/env-configurable for push-to-talk (the safe default) and for the risky-set behavior.
   - The pending confirmation card stays visible/prominent; a single click applies + the existing loop `st.rerun()` refreshes the scoreboard.
2. **streamlit-webrtc frame format — RESOLVED:** Make the audio fix **format-agnostic** (detect dtype/sample_rate from the frame, never assume). Use the Stage-0 debug panel to record the real frame dtype/sample_rate/RMS on a live mic, confirm the corruption hypothesis, then finalize Stage 1-3. Do not merge Stage 1-3 until the debug panel shows 16 kHz mono int16 reaching `transcribe_pcm` with non-trivial RMS on speech.
3. Cannot execute/run the app in plan mode; Stage 0 (debug panel) is the gating step before Stage 1-3.
