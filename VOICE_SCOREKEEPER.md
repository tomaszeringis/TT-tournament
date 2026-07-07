# Voice Scorekeeper Documentation

## Overview

The Voice Scorekeeper enables hands-free score updates for table tennis matches using local speech recognition. All processing happens on your machine — no audio data leaves your device.

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
MatchManager.apply_voice_event() (score update)
    ↓
Streamlit UI (session state + rerun)
```

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

### Commands
| Phrase | Action |
|--------|--------|
| "undo" | Undo last score change |
| "take back" | Undo last score change |
| "remove point" | Undo last score change |

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

## Graceful Fallback

If faster-whisper or streamlit-webrtc is unavailable:
- The app displays a clear warning in the UI.
- Manual scoring buttons (+/−) continue to work.
- The existing push-to-talk voice input (`st.audio_input`) continues to work.

## Development

### Running Tests
```bash
pytest tests/test_voice_parser.py -v
```

### Project Structure
```
tournament_platform/
├── app/
│   ├── pages/
│   │   └── voice_scorekeeper.py    # Main page with WebRTC integration
│   └── services/
│       ├── voice_parser.py         # Transcript → VoiceScoreEvent
│       ├── voice_audio.py          # Audio frame buffering + VAD
│       └── voice_asr.py            # faster-whisper wrapper
├── services/
│   └── match_manager.py            # Match state + apply_voice_event()
└── tests/
    └── test_voice_parser.py        # Parser unit tests
```
