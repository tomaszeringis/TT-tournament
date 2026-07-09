# Voice Scorekeeper Documentation

## Overview

The Voice Scorekeeper enables hands-free score updates for table tennis matches using local speech recognition. All processing happens on your machine — no audio data leaves your device.

The scoreboard now includes PingScore-derived features: configurable formats (first-to-11/15/21, best-of-1/3/5), automatic serve switching, deuce/advantage tracking, round/match winner screens, voice color aliases, duplicate-command cooldown, and optional sound cues.

## Architecture

```
Browser Microphone
    ↓
streamlit-webrtc (WebRTC audio frames)
    ↓
VoiceAudioBuffer (chunking + VAD)
    ↓
LocalASR (faster-whisper, lazy-loaded)
    ↓
VoiceParser (score phrase → structured event)
    ↓
ScoreEngine (pure rules: serve, deuce, win-by-2, best-of)
    ↓
MatchManager (legacy UI mirror + API persistence)
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

5. **Click "Start Listening"** and allow microphone access when prompted.

6. **Speak score commands** clearly:
   - "Five four" → sets score to 5-4
   - "Six all" → sets score to 6-6
   - "Point player one" → adds point to Player A
   - "Undo" → removes last point

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
| "point player one" | Add point to Player A |
| "point to player two" | Add point to Player B |
| "player one scores" | Add point to Player A |
| "last point player two" | Add point to Player B |

### PingScore-style Color Aliases (Phase 4)
| Phrase | Action |
|--------|--------|
| "blue" / "teal" / "green" | Add point to Player A |
| "red" / "orange" / "read" | Add point to Player B |

### Commands
| Phrase | Action |
|--------|--------|
| "undo" | Undo last score change |
| "take back" | Undo last score change |
| "remove point" | Undo last score change |

## Duplicate-Command Cooldown

To prevent double-scoring from repeated or echoed voice commands, the scorekeeper suppresses identical `(event_type, player, score_a, score_b)` events that occur within **1.2 seconds** of the last successfully applied event. Suppressed duplicates are logged to the voice event audit log with the note `duplicate_suppressed`.

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
| `VOICE_ASR_MODEL_SIZE` | `base.en` | faster-whisper model size |
| `VOICE_ASR_DEVICE` | `cpu` | Device: `cpu`, `cuda`, `auto` |
| `VOICE_ASR_COMPUTE_TYPE` | `int8` | Compute type: `int8`, `float16`, `float32` |
| `SCORE_ENABLE_SOUNDS` | `false` | Enable optional browser-side sound cues |

### Model Recommendations

**CPU (default)**:
- `base.en` — fastest, ~140MB download, good for quiet environments
- `small.en` — better accuracy, ~460MB download

**GPU (CUDA)**:
- `medium.en` — good balance, ~1.5GB download
- `large-v3` — best accuracy, ~3GB download

Example for GPU:
```bash
export VOICE_ASR_MODEL_SIZE=medium.en
export VOICE_ASR_DEVICE=cuda
export VOICE_ASR_COMPUTE_TYPE=float16
```

### Sound Cues

When `SCORE_ENABLE_SOUNDS=true`, the scoreboard plays short synthesized sounds for:
- Point added
- Undo
- Deuce
- Game won
- Match won
- Rejected voice command

Sounds are generated in the browser via Web Audio (no audio files needed). The toggle is available in the scoreboard center column.

## Match Format

Use the **Match Setup** expander on the scoreboard to configure:
- **Points to win**: 11 (standard), 15, or 21
- **Best of**: 1 (single game), 3, or 5
- **First server**: Player A or Player B

Changing the format resets the match. The engine enforces win-by-two and best-of majority rules automatically.

## Round and Match Winner Screens

- **Game won**: A banner appears showing the game score and games won count. Click **Next Game** to continue.
- **Match won**: A champion banner appears with the final games score. Options include **Rematch** (swap first server), **New Match**, and **Submit Result** (pre-fills the game-by-game submission form).

## Microphone Permissions

- **Browser**: Allow microphone access when prompted by the browser.
- **Local**: No special system permissions needed beyond normal microphone access.
- **Network**: WebRTC uses STUN for NAT traversal; no TURN server is configured by default.

## Known Limitations

1. **Noisy environments**: Table tennis halls can be loud. The VAD uses simple amplitude thresholding which may trigger on crowd noise. Speak clearly and close to the microphone.

2. **Accent and pronunciation**: The `base.en` model is trained on general English. Strong accents or very fast speech may cause transcription errors.

3. **Latency**: Continuous listening has ~1-3 second latency due to chunking and transcription time. This is intentional to avoid blocking the WebRTC callback.

4. **Concurrent speech**: If multiple people speak at once, the ASR may produce garbled transcripts.

5. **Browser compatibility**: WebRTC works best in Chrome, Firefox, and Edge. Safari has limited support for `sendonly` audio tracks.

## Disabling Voice Scoring

- Toggle "Enable Voice Scoring" off in the UI.
- The existing push-to-talk (`st.audio_input`) and manual scoring buttons continue to work regardless of the WebRTC toggle.

## Troubleshooting

### "streamlit-webrtc is not installed"
```bash
pip install streamlit-webrtc
```

### "faster-whisper not installed"
```bash
pip install faster-whisper
```

### "Failed to load faster-whisper model"
- Check your internet connection (model downloads on first use).
- Try a smaller model: `VOICE_ASR_MODEL_SIZE=base.en`.
- On CPU, use `VOICE_ASR_COMPUTE_TYPE=int8` (default).

### Microphone not working
- Ensure the browser has microphone permissions.
- Try refreshing the page.
- Check that no other app is using the microphone.

### High CPU usage
- Use a smaller model (`base.en` instead of `small.en` or `medium.en`).
- Increase the silence duration in `VoiceAudioBuffer` to reduce transcription frequency.

## ASR Backends

The voice scorekeeper supports multiple speech recognition backends through a pluggable architecture. By default, it uses **faster-whisper** (local, lightweight). You can optionally enable **SpeechBrain** for experimentation and research.

### Available Backends

| Backend | Default | Notes |
|---------|---------|-------|
| `faster_whisper` | Yes | Fast, local, CPU-friendly. Default model: `base.en`. |
| `speechbrain` | No | Requires optional `[speech]` dependencies. CPU-first. |

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

### Why SpeechBrain is Optional

- **Heavier dependencies**: SpeechBrain requires `torch` and `torchaudio`, which add significant install size.
- **Default path is faster-whisper**: faster-whisper is faster on CPU and requires fewer dependencies.
- **Research and experimentation**: SpeechBrain is useful for testing alternative ASR models, fine-tuning, or comparing transcription quality.

### Backend Architecture

```
AudioChunk (PCM bytes)
    ↓
ASRBackend.transcribe_pcm()
    ↓
Backend-specific model (faster-whisper or SpeechBrain)
    ↓
Transcript (text)
    ↓
VoiceParser (deterministic score phrase parsing)
    ↓
ScoreEngine → MatchManager → UI
```

**Important**: ASR backends only produce text. They never change match scores directly. All score changes go through `VoiceParser` → `ScoreEngine` → `MatchManager`.

## Graceful Fallback

If faster-whisper or streamlit-webrtc is unavailable:
- The app displays a clear warning in the UI.
- Manual scoring buttons (+/−) continue to work.
- The existing push-to-talk voice input (`st.audio_input`) continues to work.

## Development

### Running Tests
```bash
pytest tests/test_score_engine.py tests/test_voice_parser.py -v
```

### Project Structure
```
tournament_platform/
├── app/
│   ├── pages/
│   │   └── voice_scorekeeper.py    # Main page with WebRTC + scoreboard
│   └── services/
│       ├── score_engine.py         # Pure scoring rules (PingScore-derived)
│       ├── voice_parser.py         # Transcript → VoiceScoreEvent
│       ├── voice_audio.py          # Audio frame buffering + VAD
│       ├── voice_asr.py            # faster-whisper wrapper
│       └── ui_feedback.py          # Optional sound cues (feature-flagged)
├── services/
│   └── match_manager.py            # Match state + apply_voice_event()
└── tests/
    ├── test_score_engine.py        # Engine unit tests
    └── test_voice_parser.py        # Parser unit tests
```
