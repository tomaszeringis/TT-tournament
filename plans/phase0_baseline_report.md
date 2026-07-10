# Phase 0 Baseline Report
**Date:** 2026-07-10  
**Branch:** `ux-redesign-safe-pages`  
**Mode:** Plan verification before implementing Phase 1.

## 1. Test Baseline
- **Command:** `python -m pytest tests/ -x --tb=short -q`
- **Result:** All tests pass (200+ tests)
- **Warnings:** Deprecation warnings (SQLAlchemy `declarative_base`, `datetime.utcnow`) — non-blocking.

## 2. Voice Page Baseline
- **File:** `tournament_platform/app/pages/voice_scorekeeper.py` (2539 lines)
- **Session state keys used:** 30+ keys, including:
  - `match_manager`, `last_feedback`
  - `realtime_mode`, `listening`, `audio_level`
  - `voice_scoring_enabled`, `voice_listening`, `last_voice_transcript`, `last_voice_event`, `last_voice_feedback`, `voice_event_log`
  - `voice_event_logger`
  - `voice_noise_filtering`, `voice_noise_threshold`, `voice_strict_mode`, `voice_rms_samples`, `voice_last_chunk_rms`
  - `voice_asr_status`, `voice_webrtc_ctx`, `voice_webrtc_processor_factory`
  - `voice_speaker_tagger`, `voice_current_speaker`
  - `voice_tts_adapter`
  - `voice_selected_tournament_id`, `voice_selected_match_id`, `voice_selected_player1_id`, `voice_selected_player1_name`, `voice_selected_player2_id`, `voice_selected_player2_name`, `voice_match_options`, `voice_parsed_result`, `voice_score_input`
  - `voice_last_applied_event_key`, `voice_last_applied_event_ts`
  - `pending_confirmations`
  - `voice_dataset_recorder`, `voice_dataset_samples`
  - Commentary keys: `commentary_enabled`, `commentary_style`, `commentary_verbosity`, `commentary_voice`, `commentary_language`, `commentary_muted`, `last_commentary_event_id`, `pending_commentary`, `last_commentary_text`
  - Report keys: `report_transcript`, `report_parsed`, `report_status`

## 3. Voice Architecture Baseline
```
Browser mic
  → st.audio_input (push-to-talk) OR streamlit-webrtc (continuous)
    → VoiceAudioBuffer (chunking, VAD, noise gate)
      → ASRBackend (faster-whisper default, SpeechBrain optional)
        → VoiceParser (deterministic grammar)
          → VoiceParseResult (intent + slots + confidence)
            → ConfirmationPolicy.decide() → apply | confirm | reject
              → MatchManager.apply_voice_event()
                → ScoreEngine (authoritative rules)
                  → UI update + EventLogger + VoiceEventRepository
```

## 4. API / Report Baseline
- **Endpoint:** `POST /api/report`
- **Payload:** `{ match_id, score, winner }` (or `{ player1, player2, score, winner }` for legacy)
- **Response:** `{ status, match_id, message }`
- **Side effects:** Updates Match row, updates ratings via `RatingManager.update_ratings()`, sends Teams webhook if configured.
- **Status:** Unchanged. Must not break.

## 5. DB Models Baseline
- `VoiceEvent` table exists (migration 010) but is underused by the page.
- `VoiceCommand` table exists for dataset recorder.
- `Match`, `Player`, `Tournament`, `AuditLog`, `Announcement`, `VenueTable` exist.

## 6. Admin / Maintenance Baseline
- `admin.py` page has: Database Overview, Match Management, System Health, Danger Zone.
- `services/admin_maintenance.py` provides: counts, player stats, filtered matches, cache clearing, runtime versions, safe status checks.
- `services/test_data_cleanup_service.py`: preview and cleanup test data.
- **Action required:** Do not delete or break these in Phase 1.

## 7. Dependencies Baseline
**Core:**
- streamlit>=1.58.0
- fastapi>=0.137.1
- sqlalchemy>=2.0.51
- alembic>=1.18.4
- faster-whisper>=1.0.0
- pyaudio>=0.2.11
- pyttsx3>=2.90

**Optional extras:**
- `[dev]`: pytest, pytest-asyncio
- `[video]`: opencv-python, numpy
- `[live]`: streamlit-webrtc, av, numpy
- `[speech]`: speechbrain, torch, torchaudio

**Already in project.audio/game logic:** `sounddevice` not used; `play_cue` uses Streamlit HTML audio or no-op.

## 8. Risks Identified
1. Page is 2539 lines — high regression risk.
2. WebRTC processor factory stored in session state can leak across reruns.
3. No formal confirmation state machine — pending list can grow unbounded.
4. `LocalASR` used directly in push-to-talk path, while WebRTC uses `ASRBackendFactory` — inconsistency.
5. `voice_transcription.py` (Vosk) is separate from `asr_backends/` factory.
6. DB persistence (`VoiceEventRepository`) is called only in a few places.

## 9. Phase 1 Scope Verification
- No changes to `/api/report` behavior.
- No changes to admin/maintenance functions.
- No changes to manual scoring controls.
- No removal of existing functionality.
- All new code is additive or extracted refactorings.
