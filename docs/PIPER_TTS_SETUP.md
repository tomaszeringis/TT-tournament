# Piper TTS Setup

Piper is an optional local neural text-to-speech engine for voice commentary. The app falls back to browser SpeechSynthesis if Piper is not installed or no voice models are available.

## 1. Install Piper

```bash
python -m pip install "piper-tts>=1.4,<2"
```

Or install with the optional extra:

```bash
python -m pip install ".[tts]"
```

**License note:** The `piper-tts` package is licensed under GPL-3.0-or-later. Review the license before distributing voice models or bundling Piper with your application.

## 2. Voice model location

Place Piper voice models in:

```
tournament_platform/assets/tts/piper/voices/
```

Each voice requires two files:

```text
<voice-id>.onnx
<voice-id>.onnx.json
```

### Recommended folder layout

```text
tournament_platform/assets/tts/piper/voices/en_US-lessac-medium/en_US-lessac-medium.onnx
tournament_platform/assets/tts/piper/voices/en_US-lessac-medium/en_US-lessac-medium.onnx.json
```

Flat layout is also supported:

```text
tournament_platform/assets/tts/piper/voices/en_US-lessac-medium.onnx
tournament_platform/assets/tts/piper/voices/en_US-lessac-medium.onnx.json
```

## 3. Download voice models

Piper voice models are not included in this repository. Download them from the official Piper voice repository and place them in the folder above.

Check model licenses before use. Some voices may have restrictions.

## 4. Generated audio cache

Generated WAV files are cached under:

```
tournament_platform/data/tts_cache/piper/
```

This directory is ignored by git. Do not commit generated audio files.

## 5. Smoke test

After installing Piper and adding at least one voice model, run:

```bash
python scripts/smoke_test_piper.py
```

Expected output when a voice exists:

```text
Piper smoke test succeeded: tournament_platform/data/tts_cache/piper/piper_smoke_test.wav
```

Expected output when no voices are installed:

```text
Piper is installed, but no local voice models were found.
Add .onnx and .onnx.json files to tournament_platform/assets/tts/piper/voices/.
```

## 6. Behavior without Piper

If Piper is not installed or no voice models are present:

- The app starts normally.
- Browser SpeechSynthesis remains the default spoken commentary engine.
- Manual scoring, voice scoring, and live scoreboard updates are unaffected.
- No errors are shown to users.

## 7. Using Piper in the app

1. Open the Voice Scorekeeper page.
2. Expand **Spoken Commentary** settings.
3. Expand **Advanced spoken commentary**.
4. Set **TTS engine** to **Piper local voices**.
5. Select a Piper voice from the dropdown.
6. Click **Test Piper voice** to verify playback.

If Piper is selected but fails, the app shows a warning and falls back to browser speech automatically.

## 8. Troubleshooting

- **"Piper local TTS is not available in this environment."** — Informational only. The app falls back to browser speech. To enable local Piper, install it with `python -m pip install "piper-tts>=1.4,<2"` and add voice models (see below). This message is shown once per session, not on every score update.
- **"No Piper voices found."** — Add `.onnx` and `.onnx.json` files to `tournament_platform/assets/tts/piper/voices/`.
- **"Piper synthesis failed."** — Check that the voice model is valid and not corrupted. Try the smoke test.
- **CLI not found:** The app uses `python -m piper` internally. No PATH configuration is needed.
