# Voice Scorekeeper — Score Mutation Path Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`

## Path 1: Manual Scoring

Entry points in `_render_ui()` (lines 5846–6035):
- `match_manager._add_point("A")` / `_add_point("B")`
- `match_manager.undo_last_point()`
- `match_manager.undo_last_completed_game()`
- `match_manager.reset_current_game()`
- `match_manager.reset_match()`
- `match_manager.apply_format(new_pts, new_bo, new_fs)`
- `match_manager.rematch()`

Side effects after mutation:
- `prev_state = copy.deepcopy(...)`
- `st.session_state.last_feedback = msg`
- `st.toast(msg, icon="...")`
- `play_cue("point"/"undo")`
- `_maybe_speak_tts(msg, "increment"/"undo")`
- `_build_and_store_commentary(action, state, prev_state)`
- `_mark_last_audio_summary_action(action)` (if tt_sounds)
- `persist_voice_match_to_db(mid, engine)` (if mid)
- `st.rerun()`

## Path 2: Voice Canonical

Entry: `_process_voice_transcript()` → `apply_score_event_and_refresh_ui()` → `match_manager.apply_voice_event()`

## Path 3: Quick Voice

Entry: `_process_quick_voice_event()` → `_apply_quick_voice_point()` → `mm._add_point(player)`

## Path 4: Push-to-Talk

Entry: `st.audio_input` → `_process_push_to_talk_audio()` → `_process_voice_transcript()`

## Path 5: WebRTC

Entry: `webrtc_streamer` → `VoiceAudioProcessor` → `_process_voice_events()` → `_process_voice_transcript()`

## Path 6: Debug Voice Pipeline

Entry: `st.text_input` / `st.button` → `_process_voice_transcript(source="debug")`

## Persistence Paths

| Path | Function | When |
|------|----------|------|
| Live scoring | `persist_voice_match_to_db(mid, engine)` | After every point/undo/reset in manual + voice paths |
| Match submission | `finalize_voice_match(selected_match_id, engine)` | On "Submit Result" click when match complete |

## Commentary Trigger Path

All scoring paths call `_build_and_store_commentary()`, which queues for `render_pending_commentary()` / `play_commentary()`.
