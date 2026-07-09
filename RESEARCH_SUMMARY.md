# Voice Scorekeeper Research Summary

## Branch
`ux-redesign-safe-pages`

## Existing Architecture

### Audio Capture
- **WebRTC path**: `streamlit-webrtc` with `VoiceAudioProcessor` as `AudioProcessorBase`. The `recv_audio()` method receives audio frames from WebRTC, buffers them into `VoiceAudioBuffer`, and spawns a background thread for transcription when a chunk is emitted.
- **st.audio_input path**: `process_voice_command()` uses `UmpireEngine.transcribe_audio_file()` for push-to-talk mode.

### Audio Buffering/Chunking
- `VoiceAudioBuffer` accumulates raw frame bytes, uses RMS-based VAD and silence detection to emit `AudioChunk` objects.
- `AudioChunk.to_pcm_bytes()` converts accumulated frames to mono 16kHz int16 PCM, handling both float32 and int16 input formats, stereo-to-mono conversion, and resampling.

### faster-whisper Loading
- `LocalASR` lazy-loads `WhisperModel` on first `transcribe_chunk()` call.
- Thread-safe via `_load_lock`.
- Environment variables: `VOICE_ASR_MODEL_SIZE` (default: base.en), `VOICE_ASR_DEVICE` (default: cpu), `VOICE_ASR_COMPUTE_TYPE` (default: int8).
- Each `VoiceAudioProcessor` instance creates its own `LocalASR`, which means model loading is per-processor.

### Transcript Parsing
- `VoiceParser.parse()` returns `VoiceScoreEvent` with types: `set_score`, `increment`, `undo`, `unknown`.
- Number word normalization handles ASR mistakes: "for"→"four", "to"/"too"→"two", "oh"/"zero"/"love"→"0".
- Color aliases: blue/teal/green → Player A, red/orange/read → Player B.
- Score pair extraction supports "five four", "6 4", "10-8", "11-9" formats.

### VoiceScoreEvent Application
- `MatchManager.apply_voice_event()` handles `set_score`, `increment`, `undo`.
- Delegates to `_set_score()` and `_add_point()` which use `score_engine` functions.
- `_set_score()` and `_add_point()` both snapshot state for undo via `state.history`.

### MatchManager/ScoreEngine
- `score_engine` is the authoritative source of truth.
- `MatchManager._sync_state()` mirrors engine state to legacy UI state.
- `add_point()` handles game/match completion via `complete_game()`.
- `set_score()` handles direct score setting with validation and game completion.
- `undo_last_action()` restores full snapshot including round_scores, games_won, etc.

### Completed Games/Matches
- `complete_game()` records `round_scores`, increments `games_won`, resets score, sets `match_status = "game_won"`.
- `check_match_winner()` determines match winner.
- Game completion is handled in `score_engine.add_point()` and `score_engine.set_score()`.

### UI Feedback
- `_process_voice_events()` runs in main Streamlit loop, consumes queued events.
- Shows last transcript, parsed event, feedback, debug expander.
- Cooldown (1200ms) prevents duplicate commands.
- `EventLogger` provides structured audit logging.

## Confirmed Issues

### 1. CRITICAL: Background thread accessing st.session_state unsafely
**File**: `tournament_platform/app/pages/voice_scorekeeper.py`, lines 390-391
**Description**: `VoiceAudioProcessor._transcribe_chunk()` runs in a daemon thread spawned from `recv_audio()`. It reads `st.session_state.match_manager.state.score_a` and `score_b` for deuce validation. Streamlit's session state is NOT thread-safe. This can cause race conditions, corrupted state, or crashes.
**Fix**: Remove `st.session_state` access from `_transcribe_chunk()`. Pass current scores as parameters from the main thread, or skip deuce validation in the background thread.

### 2. HIGH: MatchManager.undo_last_point pops legacy history before engine undo succeeds
**File**: `tournament_platform/services/match_manager.py`, lines 284-301
**Description**: `undo_last_point()` pops from `self.state.match_history` BEFORE calling `engine_undo_last_action()`. If the engine undo fails (e.g., no history), the legacy history is already corrupted.
**Fix**: Pop legacy history only after engine undo succeeds.

### 3. MEDIUM: VoiceAudioProcessor creates new LocalASR per instance, potential model reload
**File**: `tournament_platform/app/services/voice_asr.py` and `tournament_platform/app/pages/voice_scorekeeper.py`
**Description**: Each `VoiceAudioProcessor` creates a new `LocalASR()`. While `LocalASR` lazy-loads the model, if the processor is recreated by WebRTC, a new `LocalASR` instance is created. Different instances could each attempt to load the model.
**Fix**: Use a module-level cache for the WhisperModel, shared across all `LocalASR` instances.

### 4. MEDIUM: Thread explosion - new thread per audio chunk
**File**: `tournament_platform/app/pages/voice_scorekeeper.py`, lines 361-365
**Description**: `recv_audio()` spawns a new daemon thread for EVERY emitted chunk. If many chunks are emitted quickly, this can create dozens of threads.
**Fix**: Use a single background worker thread with a queue.

### 5. LOW: Dead code _check_game_completion in MatchManager
**File**: `tournament_platform/services/match_manager.py`, lines 237-256
**Description**: `_check_game_completion()` is never called. Game completion is handled by `score_engine.complete_game()`.
**Fix**: Remove the dead code method.

### 6. LOW: st.set_page_config conflict
**File**: `tournament_platform/app/pages/voice_scorekeeper.py`, line 14
**Description**: `st.set_page_config()` is called in the page file. In Streamlit multi-page apps, this can cause warnings.
**Fix**: Remove the `st.set_page_config` call from the page file.

### 7. LOW: Match completion doesn't stop voice listening
**File**: `tournament_platform/app/pages/voice_scorekeeper.py`
**Description**: When match is won, the UI shows a message but doesn't stop voice listening.
**Fix**: Add logic to stop listening when match is won.

### 8. LOW: Missing tests for voice_audio, voice_asr, and MatchManager voice event edge cases
**Description**: No tests for `AudioChunk.to_pcm_bytes()`, `LocalASR` graceful degradation, or `MatchManager.apply_voice_event` with set_score undo after game completion.
**Fix**: Add comprehensive tests.

## Files to Change

1. `tournament_platform/services/match_manager.py` - Fix undo_last_point, remove dead code
2. `tournament_platform/app/pages/voice_scorekeeper.py` - Fix thread safety, thread explosion, page config, match end listening
3. `tournament_platform/app/services/voice_asr.py` - Add module-level model cache
4. `tests/test_match_manager_engine.py` - Add tests for set_score undo, game completion undo
5. `tests/test_voice_audio.py` - New file for audio tests
6. `tests/test_voice_asr.py` - New file for ASR tests

## Risk Level
**Medium** - The changes are targeted and incremental. The most critical fix is the thread-safety issue in `_transcribe_chunk()`. Removing `st.session_state` access from the background thread is safe because the parser doesn't actually need current scores for most event types.

## Backward Compatibility Notes
- All changes preserve existing API signatures.
- `VoiceScoreEvent` dataclass is unchanged.
- `MatchManager.apply_voice_event()` behavior is unchanged for successful operations.
- `LocalASR` API is unchanged; only internal model caching is added.
- Manual scoring buttons continue to work through the same `MatchManager` path.
- `st.set_page_config` removal from page file is safe because `main.py` already sets it.
