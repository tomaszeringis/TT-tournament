# Voice Scorekeeper — Runtime Objects Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`

## VoiceAudioProcessor

- Factory: `_make_processor()` (line 4610)
- Tracked wrapper: `_tracked_factory()` (line 4659)
- Stored in session: `voice_webrtc_processor_factory` (callable)
- Instance stored in: `st.session_state.voice_webrtc_ctx["processor"]`
- Component key: `voice_scorekeeper_continuous_webrtc`
- State tracking keys:
  - `_voice_factory_call_count`
  - `_voice_factory_last_error`
  - `_voice_last_processor_id`
  - `_voice_last_processor_class`
  - `_voice_processor_callback_count`
  - `_voice_last_processor_exception`
  - `voice_webrtc_streamer_state`
  - `_voice_prev_webrtc_playing`
  - `_voice_prev_processor_stage`
  - `_voice_main_thread_frame_audit_count`

## Queues (inside processor)

- `_chunk_queue` (maxsize=20)
- `event_queue` (maxsize=50)
- `_audio_callback_lock` (threading.Lock)

## Diagnostics dicts (module-level, mirrored to session_state)

- `_factory_diag` (with `_factory_diag_lock`)
- `_audio_callback_count` (int)
- `_last_audio_frame_timestamp` (float)
- `_last_audio_frame_rms` (float)
- `_last_audio_frame_shape` (tuple)
- `_last_audio_frame_sample_rate` (int)
- `_last_audio_frame_method` (str)
