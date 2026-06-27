# AI Operator Console — Quick Wins

This document describes the AI-powered quick-win features added to the Tournament Platform and how to verify them.

## Features Added

| # | Feature | Page / Endpoint | Description |
|---|---------|-----------------|-------------|
| 1 | **Safe Match Result Parsing** | `POST /api/match/parse` | Parse natural language like "Alice beat Bob 3-1" into structured JSON. No database writes. |
| 2 | **Match Reporting UI** | Voice Scorekeeper → "Report Match Result" | 3-step flow: parse → review → confirm & submit. |
| 3 | **Ranking Intelligence** | Dashboard + `GET /api/ratings/leaderboard` | Live standings with wins/losses derived from completed matches. |
| 4 | **Rating Preview** | `POST /api/ratings/preview-match` | Preview rating impact and upset potential before a match. |
| 5 | **Tournament Rules Assistant** | AI Assistant → Rules Q&A tab + `POST /api/rules/ask` | Ask questions about tournament rules using RAG. |
| 6 | **Public Tournament Board** | Public Board page | Read-only TV/projector display with current matches, standings, and recent results. |
| 7 | **Voice Privacy Safeguards** | Voice Scorekeeper + Tournament Setup | Local-first audio processing, temp file deletion by default, privacy notices. |
| 8 | **Active Match Selection** | Voice Scorekeeper → "Active Tournament Matches" | Select a match from an active tournament to prefill players and score the result. Completed matches are hidden by default. Manual entry remains available as fallback. |

## Feature Flags

Feature flags are defined in [`tournament_platform/services/settings.py`](tournament_platform/services/settings.py) and can be overridden via environment variables or a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_VOICE_ENTRY` | `True` | Enable voice-based match entry (faster-whisper / SpeechRecognition). |
| `ENABLE_RULES_ASSISTANT` | `True` | Enable the AI rules assistant (RAG over tournament rule documents). |
| `ENABLE_RANKING_INTELLIGENCE` | `True` | Enable ranking intelligence features (AI-enhanced ranking insights). |
| `ENABLE_SPOKEN_CONFIRMATION` | `False` | Enable spoken confirmation prompts after voice actions. |
| `KEEP_AUDIO_FILES` | `False` | Keep temporary audio files after transcription (useful for debugging). |
| `SPEECH_MODEL_SIZE` | `base` | Whisper model size for speech-to-text transcription (`tiny`, `base`, `small`, `medium`, `large-v3`). |

To disable a feature, set the variable to `false` or `0` in your `.env` file and restart the app.

## How to Start

### 1. Install dependencies
```powershell
pip install -e .
```

### 2. Configure environment
```powershell
cd tournament_platform
copy .env.example .env
```

### 3. Start the API server (Terminal 1)
```powershell
python tournament_platform/api/server.py
```

### 4. Start the frontend (Terminal 2)
```powershell
streamlit run tournament_platform/app/main.py
```

Open `http://localhost:8501` in your browser.

## Sample Voice / Text Phrases to Test

The match parser accepts these patterns:

| Phrase | Expected Parse |
|--------|---------------|
| `Alice beat Bob 3-1` | player1=Alice, player2=Bob, score=3-1, winner=Alice |
| `Alice defeated Bob three-one` | player1=Alice, player2=Bob, score=3-1, winner=Alice |
| `Alice wins over Bob 3 to 2` | player1=Alice, player2=Bob, score=3-2, winner=Alice |
| `Bob lost to Alice 1-3` | player1=Alice, player2=Bob, score=1-3, winner=Alice |
| `Table 3 Alice beat Bob three one` | player1=Table 3 Alice (or Alice), player2=Bob, score=3-1 |

## Manual Test Checklist

Follow these steps to verify all features end-to-end:

- [ ] **Create / register players**
  - Go to Tournament Setup → Player Registration
  - Register at least 2 players (e.g., Alice, Bob)

- [ ] **Create tournament**
  - Go to Tournament Setup → Create New Tournament
  - Name it and select a type (knockout or round-robin)

- [ ] **Parse a match result**
  - Go to Voice Scorekeeper → Report Match Result
  - Type `Alice beat Bob 3-1` in the text area
  - Click "Parse Result"
  - Verify the parsed result shows correct players, score, and winner

- [ ] **Edit parsed result before submit**
  - In the confirmation form, change the score or winner
  - Verify the edited values are what gets submitted

- [ ] **Submit confirmed result**
  - Click "Submit Result"
  - Verify success message appears

- [ ] **Verify leaderboard changed**
  - Go to Dashboard
  - Check that standings/leaderboard reflects the new match result

- [ ] **Ask a rules question**
  - Go to AI Assistant → Rules Q&A tab
  - Type a question like "What is the scoring system?"
  - Verify an answer is returned

- [ ] **View operator board** (if implemented)
  - Navigate to the Operator Board page
  - Verify current/next matches and standings are displayed

- [ ] **View public board**
  - Navigate to the Public Board page
  - Verify tournament selector, match cards, standings, and recent results load

- [ ] **Test voice privacy**
  - Go to Voice Scorekeeper
  - Verify the privacy notice is visible
  - Record a result and verify temp audio is deleted (check system temp folder)

## Running Tests

```powershell
# Run all quick-win tests
pytest tournament_platform/test_match_parser.py tournament_platform/test_rating_intelligence.py tests/test_settings.py -v

# Run compile check
python -m compileall .
```

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/match/parse` | Parse match result from text (read-only, no DB writes) |
| `POST` | `/api/report` | Submit a confirmed match result (writes to DB) |
| `GET` | `/api/ratings/leaderboard` | Get current ratings leaderboard |
| `GET` | `/api/ratings/player/{id}/history` | Get rating history for a player |
| `POST` | `/api/ratings/preview-match` | Preview rating impact for a potential match |
| `POST` | `/api/rules/ask` | Ask a question about tournament rules |
