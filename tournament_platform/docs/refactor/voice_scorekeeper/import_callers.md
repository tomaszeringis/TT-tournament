# Voice Scorekeeper — External Import Callers

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`

## Test Files Importing Page Symbols

| Test file | Imported symbols |
|-----------|------------------|
| `tests/test_live_scoreboard_submit.py` | page module, fetch_active_tournaments, etc. |
| `tests/test_voice_scorekeeper_analytics.py` | `_stable_session_key`, `_active_scoring_match_key`, `_pop_successful_point_event`, `_pop_point_events_for_game`, `_last_event_game_index`, `_clear_point_events_for_match`, `_clear_advanced_analytics_state`, `_migrate_legacy_point_log`, `_get_point_log_dict`, `finalize_voice_match`, `SessionLocal`, `apply_selected_match_to_session`, `clear_selected_match` |
| `tests/test_voice_webrtc_safe.py` | `WEBRTC_AVAILABLE`, `_audio_frame_callback_func`, `_append_continuous_trace`, `st`, `_get_voice_webrtc_processor` |
| `tests/test_voice_score_pipeline.py` | `_process_voice_transcript`, `_process_voice_events`, `_get_webrtc_playing_state`, `_is_continuous_mic_active`, `_enable_continuous_listening`, `_disable_continuous_listening`, `VoiceAudioProcessor`, `get_asr_diagnostic`, `_debug_value` |
| `tests/test_voice_asr_diagnostics.py` | `_normalize_status_dict`, `get_asr_diagnostic` |
| `tests/test_voice_game_boundary.py` | module-level symbols, `match_manager`, `engine`, `apply_score_event_and_refresh_ui` |
| `tests/test_voice_audio_converter.py` | Audio conversion helpers |
| `tests/test_voice_scorekeeper_matches_bug.py` | `fetch_active_matches` |
| `tests/test_piper_tts_fallback.py` | `is_streamlit_cloud`, `piper_unavailable_session_key`, `notify_piper_unavailable_once`, `_synthesize_piper_audio`, `play_commentary`, `_event_type_to_tt` |
