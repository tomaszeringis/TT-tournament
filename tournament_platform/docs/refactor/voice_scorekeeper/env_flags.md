# Voice Scorekeeper — Environment Flags Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`
Also see: `tournament_platform/services/settings.py`

## Verified Environment Flags

| Flag / Check | Type | Notes |
|--------------|------|-------|
| `WEBRTC_AVAILABLE` | bool | Module-level; `streamlit_webrtc` import success |
| `STREAMLIT_CLOUD` | bool | Detected at runtime |
| `detect_webrtc_available()` | bool | Function wrapper for availability |
| `is_streamlit_cloud()` | bool | Cloud detection |
| `is_running_on_streamlit_cloud()` | bool | Alternate cloud detection |
| `VOICE_DATASET_OPT_IN` | bool | Dataset opt-in flag |
| `get_hf_token()` | callable | HuggingFace token provider |
| `SAMPLE_FORMAT_FLOAT32` | str | Audio format constant |

## ASR / TTS / Cloud-Safe Imports

| Import path | Condition | Notes |
|-------------|----------|-------|
| `streamlit_webrtc.webrtc_streamer` | conditional | Cloud-safe guard |
| `streamlit_webrtc.WebRtcMode` | conditional | Cloud-safe guard |
| `LocalASR` | lazy | Inside audio processing |
| `VoiceVocabulary` | lazy | Inside audio processing |
| `faster_whisper` | lazy | Whisper backend |
| `NoiseProfiler` | inline | Noise calibration |
| `VAD` (create_vad) | inline | Voice activity detection |
| `piper_tts` | conditional | Piper TTS fallback |
| `pyttsx3` | conditional | Fallback TTS |
| `speech_recognition` | conditional | STT fallback |
| `vosk` | optional | Offline STT |
| `ImpactDetector` / `TTRallyProcessor` | lazy | `tt_sounds` service |
| `MatchAnalyticsService` | lazy | Analytics |
| `build_synthetic_engine_from_match` | lazy | Analytics |
| `load_completed_match_options` | lazy | Analytics |
| `MatchFacts` | lazy | Teams recap |
| `build_recap` | lazy | Recap templates |
| `TeamsPublisher` / `TeamsEvent` | lazy | Teams webhook |
| `MatchReportExporter` | lazy | Report export |
