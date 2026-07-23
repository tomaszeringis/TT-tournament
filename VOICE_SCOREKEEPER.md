# Voice Scorekeeper Documentation

## Overview

The Voice Scorekeeper enables hands-free score updates for table tennis matches using local speech recognition. All processing happens on your machine — no audio data leaves your device.

The scoreboard includes PingScore-derived features: configurable formats (first-to-11/15/21, best-of-1/3/5), automatic serve switching, deuce/advantage tracking, round/match winner screens, voice color aliases (including Lithuanian), duplicate-command cooldown, and optional sound cues.

## Voice Modes

The page supports three input modes selectable via the **Voice Mode** segmented control:

| Mode | Description | Status |
|------|-------------|--------|
| **Off** | No voice processing. Manual scoring only. | Default |
| **Push-to-Talk** | Click the microphone, speak, and release to send. | **Recommended** |
| **Full Voice Commands** | Full grammar parsing with 40+ intents (scoring, match control, navigation, admin, accessibility). | Stable |
| **Quick Voice Scoring** | Color-word regex scan only (1.2s cooldown, game-boundary reset). | Stable |

**Push-to-talk is the default reliable mode.** It uses `st.audio_input` on the main Streamlit thread and works with any browser.

**Continuous listening is experimental.** It uses `streamlit-webrtc` for hands-free capture. The app is not listening until the WebRTC component shows `playing=True`. Use the component's built-in **START** button to begin.

## Architecture

```
Input Source (push-to-talk / continuous / debug)
    ↓
TranscriptPostProcessor (normalize + vocabulary)
    ↓
VoiceCommandGrammar (parse → VoiceParseResult)
    ↓
RouteContext (duplicate suppression, confidence, policy)
    ↓
RouteDecision: REJECT | IGNORE | CONFIRM | APPLY
    ↓
MatchManager.apply_voice_event()
    ↓
ScoreEngine (pure rules)
    ↓
Streamlit UI (session state + rerun)
```

## Scoring Engine

The `ScoreEngine` (`app/services/score_engine.py`) is the single source of truth for all scoring rules. It is pure Python (no Streamlit or DB imports) and fully unit-tested.

- **Win-by-two**: A game is won when a player reaches `points_to_win` (11, 15, or 21) with a lead of at least 2.
- **Serve switching**: Before deuce, serve changes every 2 total points. During deuce, serve changes every point.
- **Best-of match**: Match ends when a player wins a majority of `best_of` (1, 3, or 5) games.
- **Full-state undo**: Every action snapshots the complete state (score, server, games, match status) so undo restores everything.

## Enabling Voice Scoring

1. **Install dependencies**:
   ```bash
   pip install streamlit-webrtc av numpy
   ```
   Or use the `[live]` extras:
   ```bash
   pip install ".[live]"
   ```

2. **Install faster-whisper** (if not already installed):
   ```bash
   pip install faster-whisper
   ```

3. **Navigate to the Voice Scorekeeper page** in the app.

4. **Toggle "Enable Voice Scoring"** to on.

5. **Choose a voice mode**:
   - **Push-to-Talk (recommended)**: Click the microphone, speak your command, and release to send. Manual scoring is always available as a fallback.
   - **Full Voice Commands**: Speak commands like "point blue", "undo", "set score five four".
   - **Quick Voice Scoring**: Uses color aliases with cooldown protection. Best for rapid live scoring.
   - **Continuous listening (experimental)**: Click **START** in the microphone component below and allow browser microphone permission. Use the component's own STOP control to end the session.

6. **Speak score commands** clearly (see Supported Voice Commands below).

## Supported Voice Commands

### Score Setting
| Phrase | Action |
|--------|--------|
| "five four" | Set score to 5-4 |
| "six all" | Set score to 6-6 |
| "ten eight" | Set score to 10-8 |
| "eleven nine" | Set score to 11-9 |
| "set score seven five" | Set score to 7-5 |
| "deuce" | Set to deuce (only valid at 10-10 or higher) |

### Point Scoring
| Phrase | Action |
|--------|--------|
| "point to player one" | Add point to Player A |
| "point to player two" | Add point to Player B |
| "player one scores" | Add point to Player A |
| "last point player two" | Add point to Player B |

### Color Aliases (English)
| Phrase | Action |
|--------|--------|
| "blue" / "teal" / "green" | Add point to Player A |
| "red" / "orange" / "read" | Add point to Player B |

### Color Aliases (Lithuanian)
| Phrase | Action |
|--------|--------|
| "mėlynas" / "melynas" / "žalias" / "žalia" / "zalias" / "zalia" | Add point to Player A |
| "raudonas" / "raudona" / "oranžinis" / "oranzinis" | Add point to Player B |

### Corrections
| Phrase | Action |
|--------|--------|
| "undo" | Undo last score change |
| "take back" | Undo last score change |
| "remove point" / "take that back" | Undo last score change |

### Match Control
| Phrase | Action |
|--------|--------|
| "start match" / "begin" | Begin match |
| "pause" / "timeout break" | Pause / timeout |
| "resume" / "continue" | Resume play |
| "next game" / "new game" | Start next game |
| "end game" / "game over" | End current game |
| "timeout" / "time out" | Start timeout |
| "end timeout" / "resume play" | End timeout |

### Score Queries
| Phrase | Action |
|--------|--------|
| "what's the score?" | Read current score |
| "repeat score" / "repeat" | Repeat last score |

### Server
| Phrase | Action |
|--------|--------|
| "who serves?" / "server?" | Check server |
| "player one serves" / "player two serves" | Set server |

### Confirmation / Cancellation
| Phrase | Action |
|--------|--------|
| "confirm" / "yes" / "accept" | Confirm pending action |
| "cancel" / "no" / "abort" | Cancel pending action |

### Navigation
| Phrase | Action |
|--------|--------|
| "open dashboard" | Go to dashboard |
| "show bracket" | Show bracket |
| "show rankings" | Show rankings |
| "show public board" | Show public board |
| "show current match" | Show current match |
| "back to scoring" | Back to scoring |
| "show help" / "show voice help" | Show voice help |

### Admin
| Phrase | Action |
|--------|--------|
| "call next match" | Call next match |
| "table ready" | Mark table ready |
| "assign table" | Assign table |
| "mark unavailable" | Mark unavailable |
| "publish result" | Publish result |
| "mark no show" | Mark no show |
| "drop player" | Drop player |
| "start next round" | Start next round |

### Accessibility
| Phrase | Action |
|--------|--------|
| "repeat" | Repeat last score |
| "announce score" | Announce score |
| "louder" / "quieter" | Volume control |
| "mute" / "unmute" | Mute control |
| "slower" / "faster" | Speech rate |
| "large text" | Large text mode |
| "high contrast" | High contrast mode |
| "accessibility help" | Accessibility help |

## Quick Voice vs Full Voice Command

- **Quick Voice Scoring mode** only accepts color words via `QuickVoiceScoringEngine` (regex scan, 1.2s cooldown, game-boundary reset). It does not use the full `VoiceCommandGrammar`.
- **Full Voice Commands mode** uses the canonical `VoiceCommandGrammar` + `CommandRouter`. All intents in the tables above are available.
- Lithianian color aliases work in both modes.

## Duplicate-Command Cooldown

To prevent double-scoring from repeated or echoed voice commands, identical events within **1.2 seconds** are suppressed. Game boundaries automatically reset the cooldown so the first command of the next game is never blocked.

## ASR Mistake Normalization

The parser handles common speech-to-text errors:
- "for" → "four" (e.g., "for two" → 4-2)
- "to" / "too" → "two"
- "oh" / "zero" / "love" → 0
- "all" → equal score (e.g., "six all" → 6-6)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICE_ASR_MODEL_SIZE` | `tiny.en` | faster-whisper model size |
| `VOICE_ASR_DEVICE` | `cpu` | Device: `cpu`, `cuda`, `auto` |
| `VOICE_ASR_COMPUTE_TYPE` | `int8` | Compute type: `int8`, `float16`, `float32` |
| `VOICE_ASR_BACKEND` | `faster_whisper` | ASR backend: `faster_whisper`, `speechbrain`, `vosk` |
| `VOICE_ASR_FALLBACK_BACKEND` | `faster_whisper` | Fallback backend if primary fails |
| `VOICE_ASR_VOSK_MODEL_PATH` | `model` | Path to Vosk model directory |
| `VOICE_ENABLE_CONFIRMATION` | `true` | Require confirmation for score-setting commands |
| `VOICE_ENABLE_NOISE_FILTERING` | `false` | Enable noise gate |
| `VOICE_NOISE_THRESHOLD` | `0.0` | RMS noise threshold |
| `VOICE_DEBUG_EVENTS` | `false` | Enable verbose voice event logging |
| `HF_TOKEN` | *(empty)* | Hugging Face token for model downloads |
| `SCORE_ENABLE_SOUNDS` | `false` | Enable browser sound cues |
| `VOICE_DATASET_OPT_IN` | `false` | Opt-in dataset recording |
| `KEEP_AUDIO_FILES` | `false` | Keep temp audio files for debugging |

> **Note:** `get_voice_setting()` reads from environment variables **or** Streamlit secrets. On Streamlit Cloud, secrets are NOT injected into `os.environ`, so both sources work.

### Model Recommendations

**CPU (default)**:
- `tiny.en` — fastest, ~75MB download, good for quiet environments (default on Cloud)
- `base.en` — better accuracy, ~140MB download
- `small.en` — best CPU accuracy, ~460MB download

**GPU (CUDA)**:
- `medium.en` — good balance, ~1.5GB download
- `large-v3` — best accuracy, ~3GB download

Example for GPU:
```bash
export VOICE_ASR_MODEL_SIZE=medium.en
export VOICE_ASR_DEVICE=cuda
export VOICE_ASR_COMPUTE_TYPE=float16
```

Example for Streamlit Cloud:
```bash
export VOICE_ASR_MODEL_SIZE=tiny.en
export VOICE_ASR_DEVICE=cpu
export VOICE_ASR_COMPUTE_TYPE=int8
```

## ASR Backends

The voice scorekeeper supports multiple speech recognition backends through a pluggable architecture (`ASRBackendFactory`). By default, it uses **faster-whisper** (local, lightweight). **Vosk** is registered in the factory but is only available if installed and configured. **SpeechBrain** is documented below.

### Available Backends

| Backend | Default | Notes |
|---------|---------|-------|
| `faster_whisper` | Yes | Fast, local, CPU-friendly. |
| `speechbrain` | No | Requires optional `[speech]` dependencies. CPU-first. |
| `vosk` | No | Registered in factory; requires `[live]` extra and model at `VOICE_ASR_VOSK_MODEL_PATH`. |

### Switching Backends

Set the `VOICE_ASR_BACKEND` environment variable before starting the app:

```bash
# Use faster-whisper (default)
export VOICE_ASR_BACKEND=faster_whisper

# Use SpeechBrain (optional)
export VOICE_ASR_BACKEND=speechbrain
```

If the selected backend fails to initialize, the app can optionally fall back:

```bash
export VOICE_ASR_FALLBACK_BACKEND=faster_whisper
```

### SpeechBrain Setup (Optional)

SpeechBrain is **not** installed by default. To enable it:

1. **Install optional dependencies**:
   ```bash
   pip install ".[speech]"
   ```
   This installs `speechbrain`, `torch`, and `torchaudio`.

   For CPU-only systems, use PyTorch CPU wheels:
   ```bash
   pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
   pip install speechbrain
   ```

2. **Configure environment variables**:
   ```bash
   export VOICE_ASR_BACKEND=speechbrain
   export VOICE_SPEECHBRAIN_MODEL_SOURCE=speechbrain/asr-crdnn-rnnlm-librispeech
   export VOICE_SPEECHBRAIN_SAVEDIR=data/models/speechbrain/asr
   export VOICE_SPEECHBRAIN_DEVICE=cpu
   ```

3. **Start the app** and verify the backend status panel shows `speechbrain` as active.

### SpeechBrain Model Cache

Models are saved to `VOICE_SPEECHBRAIN_SAVEDIR` (default: `data/models/speechbrain/asr`). The directory is created automatically on first load.

### Vosk (Optional)

Vosk requires:
- `VOICE_ASR_BACKEND=vosk`
- `[live]` extra installed (`pip install ".[live]"`)
- A model placed in the directory specified by `VOICE_ASR_VOSK_MODEL_PATH`

### Backend Architecture

```
AudioChunk (PCM bytes)
    ↓
ASRBackend.transcribe_pcm()
    ↓
Backend-specific model (faster-whisper, SpeechBrain, or Vosk)
    ↓
Transcript (text)
    ↓
VoiceCommandGrammar (deterministic score phrase parsing)
    ↓
CommandRouter → MatchManager → ScoreEngine → UI
```

**Important**: ASR backends only produce text. They never change match scores directly. All score changes go through `VoiceCommandGrammar` → `CommandRouter` → `MatchManager.apply_voice_event()` → `ScoreEngine`.

## ASR Diagnostics and States

The **Voice ASR Diagnostics** expander shows the exact state of the ASR backend. Possible states:

| State | Meaning |
|-------|---------|
| `not_configured` | `VOICE_ASR_MODEL_SIZE` is unset. |
| `package_missing` | A required package (e.g., `faster-whisper`) is not installed. |
| `model_loading` | The model is being downloaded/loaded. |
| `model_loaded` | The model is ready for transcription. |
| `model_download_failed` | Download failed. Check network or `HF_TOKEN`. |
| `model_init_failed` | Model initialization failed. Check device/compute type. |

If `model_download_failed` or `model_init_failed`, check:
- `VOICE_ASR_DEVICE=cpu` (CUDA requires a compatible GPU + drivers)
- `VOICE_ASR_COMPUTE_TYPE=int8` (smaller memory footprint)
- `HF_TOKEN` secret for rate-limit-free downloads

## Diagnostics Guide

The **Voice diagnostics** expander provides live telemetry. Key fields:

| Field | Meaning |
|-------|---------|
| `WebRTC playing` | Green when the microphone is actively sending frames. |
| `audio_frames_received` | Number of audio frames delivered by WebRTC. > 0 means audio is flowing. |
| `chunks_created` | Number of speech chunks emitted by VAD/noise gate. > 0 means speech is detected. |
| `ASR events enqueued` | Number of transcription requests sent to the ASR backend. > 0 means chunks are reaching the transcriber. |
| `dropped_chunks` | Chunks dropped due to backpressure (queue full). |
| `last chunk RMS` | Energy of the last chunk. Useful for tuning `VOICE_NOISE_THRESHOLD`. |
| `stale events ignored` | Events dropped because they arrived too late or from an old session. |
| `processor status` | Internal processor state. |
| `last rejected command reason` | Why the last command was rejected. |

## WebRTC START/STOP Behavior

Continuous listening uses `streamlit-webrtc`'s `webrtc_streamer` component with a built-in **START/STOP** button.

- **Before START**: The page shows a yellow **Ready** badge. No audio is captured.
- **After START**: The page shows a green **Continuous microphone active** badge. Audio frames flow to the processor.
- **After STOP**: The page returns to yellow **Ready**. The component is still mounted but `playing=False`.

The WebRTC component key (`voice_scorekeeper_continuous_webrtc`) is stable across reruns so Streamlit does not reset the component state.

## Status Badge Legend

| Badge | Meaning |
|-------|---------|
| ⚪ **Disabled** | Voice scoring toggle is off. |
| 🔴 **WebRTC unavailable** | `streamlit-webrtc` is not installed or import failed. Use push-to-talk. |
| 🟡 **Ready** | Voice is enabled but the microphone is not started. Click START or use push-to-talk. |
| 🟢 **Continuous microphone active** | WebRTC is playing and the microphone is active. |

## Microphone Recommendations

- Use a directional/close microphone for noisy tournament halls.
- The **Audio Rally Assistant** toggle detects table-tennis impacts for commentary enrichment only. It does NOT update scores.
- On Streamlit Cloud, microphone permissions are granted by the browser. Ensure the site is served over HTTPS (Cloud handles this automatically).

## Match Format

Use the **Match Setup** expander on the scoreboard to configure:
- **Points to win**: 11 (standard), 15, or 21
- **Best of**: 1 (single game), 3, or 5
- **First server**: Player A or Player B

Changing the format resets the match. The engine enforces win-by-two and best-of majority rules automatically.

## Round and Match Winner Screens

- **Game won**: A banner appears showing the game score and games won count. Click **Next Game** to continue.
- **Match won**: A champion banner appears with the final games score. Options include **Rematch** (swap first server), **New Match**, and **Submit Result** (pre-fills the game-by-game submission form).

## Known Limitations

1. **Noisy environments**: Table tennis halls can be loud. The VAD uses amplitude + webrtcvad (if available) which may trigger on crowd noise. Use noise gating and directional microphones.
2. **Accent and pronunciation**: The `tiny.en`/`base.en` models are trained on general English. Strong accents or very fast speech may cause transcription errors.
3. **Latency**: Continuous listening has ~1-3 second latency due to chunking and transcription time.
4. **Concurrent speech**: If multiple people speak at once, the ASR may produce garbled transcripts.
5. **Browser compatibility**: WebRTC works best in Chrome, Firefox, and Edge. Safari has limited support for `sendonly` audio tracks.
6. **Streamlit Cloud**: The filesystem is ephemeral, PortAudio/pyaudio are unavailable, and microphone permissions must be granted by the user. Use `VOICE_ASR_MODEL_SIZE=tiny.en` on Cloud for fast startup.

## Debug Voice Pipeline

The **Debug Voice Pipeline** expander lets operators test transcription without speaking:

1. Type a transcript (e.g., `point red`, `undo`, `set score five four`)
2. Click **Process debug command**
3. The result shows parsed intent, confidence, and whether a rerun was requested.

Examples: `point red`, `point blue`, `undo`, `mėlynas`, `raudonas`

## Voice Observability & Operations

The **Voice Observability & Operations** expander provides a unified audit log for voice scoring events. All sources (debug, push-to-talk, continuous) append here. Events are retained in memory (up to 1000). Export JSON per match for audit trails.

- **Export Audit Log (JSON)**: Downloads all retained events as a timestamped `.json` file.
- **Clear Audit Log**: Removes all in-memory events.

## Privacy Note

The voice/text match entry system is designed with a local-first, minimal-retention privacy model.

- **Local transcription**: When using the default `faster-whisper` backend, audio is transcribed entirely on the local machine. No audio data is sent to external services.
- **Temporary files**: Audio is written to a temporary file (`.wav`) only for the duration of transcription.
- **Default deletion**: Temporary audio files are **deleted immediately after transcription** by default.
- **Debug retention**: Set `KEEP_AUDIO_FILES=true` to retain temp audio files for debugging.
- **No raw audio in database**: Raw audio bytes or file paths are never stored in the database.
- **Transcripts**: Transcripts are held in Streamlit session state only. They are not persisted unless an operator explicitly submits a match result.
- **Defensive logging**: API endpoints log only metadata — not full transcripts, player emails, or raw audio paths.

## Disabling Voice Scoring

- Toggle **Enable Voice Scoring** off in the UI.
- The existing push-to-talk (`st.audio_input`) and manual scoring buttons continue to work regardless of the WebRTC toggle.

## Troubleshooting

### WebRTC Issues

| Problem | Likely Cause | Fix / Action | Fallback |
|---------|-------------|--------------|----------|
| WebRTC START button not visible | `streamlit-webrtc` missing | `pip install streamlit-webrtc` | Push-to-talk |
| WebRTC mounted but `playing=False` | Browser permission denied or not clicked | Click START in component; check browser permissions | Push-to-talk |
| `playing=True` but `audio_frames_received = 0` | Mic muted, no audio, or format mismatch | Unmute tab, check mic, refresh page | Push-to-talk |

### Audio / Transcription Issues

| Problem | Likely Cause | Fix / Action | Fallback |
|---------|-------------|--------------|----------|
| Audio frames > 0 but `chunks_created = 0` | Silence threshold not met | Lower noise threshold, speak louder | Push-to-talk |
| Chunks > 0 but ASR transcript empty | Model not loaded or confidence too low | Load model via diagnostics; check `VOICE_ASR_MODEL_SIZE` | Manual scoring |
| Faster Whisper model not loaded | Network error, disk full, wrong device | Check logs, try `VOICE_ASR_DEVICE=cpu`, `VOICE_ASR_COMPUTE_TYPE=int8` | Manual scoring |

### Command Issues

| Problem | Likely Cause | Fix / Action | Fallback |
|---------|-------------|--------------|----------|
| ASR transcript exists but command rejected | Low confidence, unknown intent | Verify match selection, speak clearly | Manual scoring |
| Command accepted but scoreboard not updated | Event stale or duplicate suppressed | Check session ID, ensure WebRTC still playing | Manual buttons |
| Debug command works but continuous does not | WebRTC stopped while debug uses main thread | Restart continuous via START button | Debug or push-to-talk |
| Push-to-talk works but continuous does not | Different ASR path; continuous may use queued events | Check chunk queue, VAD settings | Push-to-talk |
| Commands update wrong player | Color word ambiguous | Use explicit "player one"/"player two" | Manual buttons |
| Duplicate command suppressed | Cooldown active (1.2s) | Wait for cooldown | Manual buttons |
| No active match selected | Match selector empty | Select tournament + match | Manual scoring |

### Streamlit Cloud Issues

| Problem | Likely Cause | Fix / Action | Fallback |
|---------|-------------|--------------|----------|
| Streamlit Cloud microphone issue | Browser blocked permission, ephemeral container | Re-allow mic, redeploy, check Cloud secrets | Push-to-talk |
| Browser permission blocked | Browser settings or HTTPS requirement | Enable mic in browser settings; ensure HTTPS or localhost | Manual scoring |
| `pyaudio` / PortAudio error on Cloud | `[live]` extra not available on Cloud | Ignore; Cloud uses WebRTC only. Use `[live]` locally if needed. | WebRTC push-to-talk |

### ASR Backend Issues

| Problem | Likely Cause | Fix / Action | Fallback |
|---------|-------------|--------------|----------|
| ASR error shows `not_configured` | `VOICE_ASR_MODEL_SIZE` unset or package missing | Set env var or Streamlit secret; `pip install faster-whisper` | Manual scoring |
| ASR error shows `model_download_failed` | Network error or `HF_TOKEN` missing | Set `HF_TOKEN` secret on Cloud | Manual scoring |
| ASR error shows `model_init_failed` | Wrong device/compute type | Try `VOICE_ASR_DEVICE=cpu`, `VOICE_ASR_COMPUTE_TYPE=int8` | Manual scoring |
| Vosk not working | Model path wrong or package missing | Install `[live]`, place model at `VOICE_ASR_VOSK_MODEL_PATH` | Manual scoring |

## Development

### Running Tests
```bash
pytest tests/test_score_engine.py tests/test_voice_parser.py -v
```

### Developer Debugging Workflow

1. **Diagnostics panel**: Read `audio_frames_received`, `chunks_created`, `ASR events enqueued` to verify the audio pipeline is delivering data.
2. **ASR Diagnostics**: Check the ASR provider state and import probe.
3. **Voice Debug expander**: Inspect `last parsed intent`, `last accepted command`, `last rejected reason`.
4. **Debug Voice Pipeline**: Type raw transcripts and observe parsed results.
5. **Audit export**: Export JSON for offline analysis.

### Project Structure

```
tournament_platform/
├── app/
│   ├── pages/
│   │   └── voice_scorekeeper.py    # Main page with WebRTC + scoreboard
│   └── services/
│       ├── score_engine.py         # Pure scoring rules
│       ├── voice_parser.py         # Transcript → VoiceScoreEvent
│       ├── voice_audio.py          # Audio frame buffering + VAD
│       ├── voice_asr.py            # LocalASR with module-level cache
│       └── voice/
│           ├── commands.py         # VoiceCommandGrammar + 40 intents
│           ├── quick_voice.py      # Quick Voice Scoring engine
│           ├── command_router.py   # RouteContext, RouteDecision
│           ├── runtime_state.py    # VoiceRuntimeState dataclass
│           └── asr_diagnostics.py  # get_voice_setting(), diagnostics
├── services/
│   └── match_manager.py            # Match state + apply_voice_event()
└── tests/
    ├── test_score_engine.py        # Engine unit tests
    └── test_voice_parser.py        # Parser unit tests
```
