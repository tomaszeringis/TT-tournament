# Voice Scorekeeper — Session-State Key Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`
Total keys: 90+

## Match Context

| Key | Type | Notes |
|-----|------|-------|
| `voice_selected_match_id` | str/int | Selected tournament match ID |
| `voice_selected_player1_id` | int | Player A DB ID |
| `voice_selected_player1_name` | str | Player A display name |
| `voice_selected_player2_id` | int | Player B DB ID |
| `voice_selected_player2_name` | str | Player B display name |
| `voice_selected_tournament_id` | int | Selected tournament ID |
| `match_manager` | MatchManager | Scoring engine wrapper |
| `selected_player_a` | dict | Player A dict |
| `selected_player_b` | dict | Player B dict |

## Voice Enable & Control

| Key | Type | Notes |
|-----|------|-------|
| `voice_scoring_enabled` | bool | Master toggle |
| `quick_voice_mode` | str | `"off"`, `"full"`, `"quick"` |
| `voice_listening` | bool | Continuous listening active |
| `voice_events_enabled` | bool | Events processing enabled |
| `voice_continuous_requested` | bool | Continuous mode requested |
| `voice_continuous_session_id` | str | Current session UUID |
| `voice_continuous_session_start` | float | Session start timestamp |
| `voice_session_epoch` | int | Session epoch for invalidation |
| `voice_stale_events_ignored` | int | Stale event counter |

## Transcripts & Events

| Key | Type | Notes |
|-----|------|-------|
| `last_voice_transcript` | str | Last raw transcript |
| `last_voice_event` | object | Last parsed event |
| `last_voice_feedback` | str | Last success message |
| `last_voice_raw_transcript` | str | Last raw transcript (alias) |
| `last_voice_continuous_transcript` | str | Last continuous transcript |
| `last_voice_push_to_talk_transcript` | str | Last push-to-talk transcript |
| `last_voice_debug_transcript` | str | Last debug transcript |
| `voice_last_applied_event_key` | str | Deduplication key |
| `last_voice_rejection_reason` | str | Rejection reason |
| `last_voice_success_message` | str | Success message |
| `last_voice_action_taken` | str | Action taken |

## Quick Voice

| Key | Type | Notes |
|-----|------|-------|
| `quick_voice_last_phrase` | str | Last quick phrase |
| `quick_voice_last_status` | str | Last quick status |
| `quick_voice_last_player` | str | Last player |
| `quick_voice_last_ts` | float | Last timestamp |

## WebRTC Runtime

| Key | Type | Notes |
|-----|------|-------|
| `voice_webrtc_ctx` | dict | WebRTC context (processor, etc.) |
| `voice_webrtc_streamer_state` | dict | Streamer state |
| `voice_webrtc_processor_factory` | callable | Processor factory |
| `_voice_processor_cache_cleared` | bool | Cache clear flag |
| `_voice_factory_call_count` | int | Factory call count |
| `_voice_factory_last_error` | str | Last factory error |
| `_voice_last_processor_id` | int | Last processor id |
| `_voice_last_processor_class` | str | Last processor class |
| `_voice_processor_callback_count` | int | Callback count |
| `_voice_last_processor_exception` | Exception | Last exception |
| `_voice_prev_webrtc_playing` | bool | Previous playing state |
| `_voice_prev_processor_stage` | str | Previous processor stage |
| `_voice_main_thread_frame_audit_count` | int | Frame audit count |

## ASR / Noise

| Key | Type | Notes |
|-----|------|-------|
| `voice_noise_filtering` | bool | Noise gate enabled |
| `voice_strict_mode` | bool | Strict confirmation mode |
| `voice_noise_threshold` | float | RMS threshold |
| `voice_last_chunk_rms` | float | Last chunk RMS |
| `voice_rms_samples` | list | Ambient RMS samples |
| `voice_asr` | object | ASR instance |
| `voice_asr_status` | dict | ASR status |
| `voice_current_speaker` | str | Current speaker |
| `voice_speaker_tagger` | object | Speaker tagger |

## Duplicate Suppression

| Key | Type | Notes |
|-----|------|-------|
| `voice_last_applied_event_key` | str | Applied event dedup key |
| `voice_last_applied_transcript` | str | Applied transcript |
| `voice_last_applied_score` | str | Applied score snapshot |
| `voice_last_applied_at` | float | Applied timestamp |
| `voice_last_rejected_at` | float | Rejected timestamp |
| `voice_last_rejected_reason` | str | Rejection reason |
| `_voice_pending_event` | object | Pending event |

## Confirmation

| Key | Type | Notes |
|-----|------|-------|
| `voice_pending_events` | list | Pending confirmation events |

## Commentary / TTS

| Key | Type | Notes |
|-----|------|-------|
| `commentary_last_server` | str | Last server |
| `commentary_announced_match_won` | bool | Match win announced |
| `commentary_announced_result_submitted` | bool | Result submitted announced |
| `sound_cues_enabled` | bool | Sound enabled |
| `voice_tts_adapter` | object | TTS adapter |
| `tt_sounds_enabled` | bool | Audio rally assistant |
| `tt_sounds_recent_events` | list | Recent audio events |
| `tt_sounds_rally_context` | object | Rally context |
| `tt_sounds_audio_summaries` | list | Audio summaries |
| `_pending_audio_summary_for_commentary` | object | Pending audio summary |
| `pending_commentary_lines` | list | Pending commentary |
| `commentary_queue` | list | Commentary queue |

## Dataset

| Key | Type | Notes |
|-----|------|-------|
| `voice_dataset_opt_in` | bool | Dataset opt-in |

## Analytics / Teams

| Key | Type | Notes |
|-----|------|-------|
| `analytics_selected_match_id` | int | Analytics selected match |
| `completed_games` | list | Completed games |
| `match_complete` | bool | Match completion flag |
| `result_submitted` | bool | Result submitted flag |
| `pending_result_submission` | bool | Pending submission flag |
| `voice_ai_summary` | str | AI summary text |
| `teams_recap_preview` | str | Teams recap preview |
| `teams_recap_pending` | str | Pending recap |
| `recap_tone` | str | Recap tone |

## Diagnostics / Debug

| Key | Type | Notes |
|-----|------|-------|
| `voice_audit_events` | list | Audit log |
| `voice_event_log` | list | Event log |
| `voice_webrtc_mount_error` | str | Mount error |
| `_voice_debug_last_result` | dict | Last debug result |
| `voice_debug_mode` | bool | Debug mode flag |
| `last_feedback` | str | Last UI feedback |

## Component Keys

| Key | Type | Notes |
|-----|------|-------|
| `voice_scorekeeper_continuous_webrtc` | str | WebRTC component key (stable) |
