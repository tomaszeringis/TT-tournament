# Voice Scorekeeper — Symbol Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`
Total lines: 6,239 (baseline)

## Top-Level Functions

| Function | Line | Notes |
|----------|------|-------|
| `_audio_frame_callback_func` | 184 | WebRTC audio callback |
| `is_streamlit_cloud` | 223 | Environment detection |
| `piper_unavailable_session_key` | 234 | TTS session guard |
| `notify_piper_unavailable_once` | 239 | TTS notification |
| `detect_webrtc_available` | 257 | Feature detection |
| `ensure_webrtc_diag_state` | 276 | WebRTC state init |
| `get_all_players` | 289 | DB query wrapper |
| `find_player_by_name` | 302 | Player lookup |
| `_request_voice_rerun` | 559 | Rerun request |
| `_maybe_voice_rerun` | 564 | Rerun coalescing |
| `_get_webrtc_playing_state` | 570 | WebRTC state access |
| `_is_continuous_mic_active` | 576 | Mic state check |
| `_append_voice_audit` | 581 | Audit logging |
| `_append_continuous_trace` | 625 | Continuous trace |
| `_reset_voice_game_boundary_state` | 644 | Game boundary reset |
| `is_voice_scoring_enabled` | 684 | Guard |
| `reject_if_voice_disabled` | 689 | Guard |
| `_get_voice_session_epoch` | 700 | Session epoch |
| `_increment_voice_session_epoch` | 707 | Session epoch |
| `disable_voice_scoring_and_clear_pending_state` | 713 | Cleanup |
| `_on_quick_voice_mode_changed` | 739 | Mode handler |
| `_apply_quick_voice_point` | 753 | Quick voice scoring |
| `_process_quick_voice_event` | 775 | Quick voice routing |
| `_maybe_voice_heartbeat` | 803 | Heartbeat |
| `_enable_continuous_listening` | 844 | Listening enable |
| `_disable_continuous_listening` | 877 | Listening disable |
| `_clear_tt_sounds_state` | 934 | TTS cleanup |
| `_process_tt_sounds_events` | 952 | TTS event drain |
| `_handle_tt_sounds_event` | 964 | TTS event handler |
| `_maybe_tt_sounds_heartbeat` | 986 | TTS heartbeat |
| `finalize_current_audio_rally` | 1005 | Rally finalization |
| `_mark_last_audio_summary_action` | 1016 | Audio summary |
| `_append_audio_commentary_line` | 1023 | Commentary line |
| `_render_audio_rally_insights` | 1036 | Insights render |
| `apply_score_event_and_refresh_ui` | 1082 | Central scoring boundary |
| `_process_voice_transcript` | 1420 | Transcript → event |
| `persist_voice_match_to_db` | 2087 | Live persistence |
| `_get_persisted_match_meta` | 2153 | Persisted metadata |
| `finalize_voice_match` | 2184 | Match submission |
| `compute_completed_games` | 2249 | Games derivation |
| `compute_match_score` | 2270 | Score derivation |
| `clear_result_review_state` | 2281 | State cleanup |
| `_frame_to_ndarray` | 2294 | Audio conversion |
| `_audio_input_to_pcm` | 2318 | Audio conversion |
| `_audio_frame_to_mono_float32` | 2378 | Audio conversion |
| `_pcm_float32_to_int16` | 2390 | Audio conversion |
| `_process_push_to_talk_audio` | 2396 | Push-to-talk ASR |
| `_predict_score_after` | 2444 | Score prediction |
| `_handle_phase3_intent` | 2502 | Intent handling |
| `_render_confirm_panel` | 2553 | Confirmation UI |
| `_apply_pending` | 2584 | Pending apply |
| `_process_voice_events` | 2630 | Event drain |
| `_render_dataset_panel` | 2763 | Dataset UI |
| `_get_commentary_settings` | 2873 | Commentary config |
| `_is_critical_moment` | 2903 | Critical moment |
| `_apply_critical_cooldown` | 2919 | Cooldown |
| `_synthesize_piper_audio` | 2949 | TTS synthesis |
| `play_commentary` | 2973 | Commentary playback |
| `_event_type_to_tt` | 3066 | Event → TTS mapping |
| `_build_local_commentary` | 3094 | Local commentary |
| `_build_and_store_commentary` | 3172 | Commentary store |
| `_emit_set_win_commentary` | 3255 | Set win commentary |
| `_reconcile_finished_games` | 3431 | Game reconciliation |
| `render_commentary_settings` | 3532 | Commentary UI |
| `render_pending_commentary` | 3919 | Pending commentary |
| `render_commentary_debug` | 3941 | Commentary debug |
| `render_commentary_log` | 3951 | Commentary log |
| `get_current_match_context` | 3974 | Match context |
| `fetch_active_tournaments` | 4003 | Tournament fetch |
| `is_running_on_streamlit_cloud` | 4016 | Cloud detection |
| `_normalize_status` | 4032 | Status normalization |
| `_normalize_status_dict` | 4039 | Status normalization |
| `_get_voice_webrtc_processor` | 4081 | Processor access |
| `_safe_queue_size` | 4106 | Queue safety |
| `_debug_value` | 4121 | Debug formatting |
| `get_asr_diagnostic` | 4130 | ASR diagnostics |
| `get_asr` | 4158 | ASR getter |
| `_quick_voice_asr_ready` | 4169 | ASR readiness |
| `fetch_active_matches` | 4183 | Match fetch |
| `sort_key` | 4210 | Sort helper |
| `format_match_option` | 4250 | Match formatting |
| `apply_selected_match_to_session` | 4272 | Match selection |
| `clear_selected_match` | 4292 | Match clear |
| `_render_match_diagnostics` | 4305 | Diagnostics UI |
| `render_active_match_selector` | 4337 | Match selector UI |
| `render_selected_match_summary` | 4445 | Match summary UI |
| `render_voice_sections` | 4460 | Voice sections entry |
| `_make_processor` | 4610 | Processor factory |
| `_tracked_factory` | 4659 | Factory wrapper |
| `_render_ui` | 5675 | Page root render |

## Classes

| Class | Line | Base | Notes |
|-------|------|------|-------|
| `ScoreApplyResult` | 1070 | — | Named tuple / dataclass for apply result |
| `VoiceAudioProcessor(AudioProcessorBase)` | 1603 | `AudioProcessorBase` | WebRTC audio processor |

## VoiceAudioProcessor Methods

| Method | Line | Notes |
|--------|------|-------|
| `__init__` | 1620 | Initializes queues, buffers, ASR, VAD |
| `_get_asr` | 1685 | Lazy ASR init |
| `_set_status` | 1711 | Status update |
| `_log_rate_limited` | 1715 | Rate limit log |
| `_start_worker` | 1736 | Thread start |
| `_worker_loop` | 1741 | Background transcribe loop |
| `_ingest_frame` | 1762 | Audio frame ingest |
| `_enqueue_chunk` | 1872 | Chunk queueing |
| `recv` | 1891 | WebRTC callback |
| `recv_queued` | 1907 | Queued receive |
| `_maybe_log_first_frame` | 1924 | First frame log |
| `get_diagnostics` | 1933 | Diagnostics dict |
| `_transcribe_chunk` | 1950 | ASR transcription |
| `get_events` | 2018 | Event drain |
| `has_pending_events` | 2031 | Event check |
| `peek_events` | 2036 | Event peek |
| `peek_chunks` | 2049 | Chunk peek |
| `stop` | 2063 | Stop worker |
