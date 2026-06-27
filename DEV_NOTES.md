# Developer Notes

## Baseline status

**Date:** 2026-06-27  
**Python version:** 3.13.9  
**Branch:** quick-wins-ai-operator-console

### Commands run

- `python -m compileall .` — passed (exit 0)
- `python tournament_platform/test_models.py` — passed after fix
- `python tournament_platform/check_schema.py` — passed
- `python tournament_platform/check_tables.py` — passed after fix
- `python verify_setup.py` — passed after fix

### Failures found

1. **UnicodeEncodeError on Windows console (cp1252)**  
   `test_models.py`, `check_tables.py`, and `verify_setup.py` used Unicode checkmark/cross marks (✓/✗) and emoji characters in `print()` statements. The default Windows console codec (cp1252) cannot encode these characters, causing `UnicodeEncodeError` at runtime.

2. **No broken imports or missing `__init__.py` files**  
   All package imports resolved correctly. No syntax errors or path issues were found.

### Fixes made

- **`tournament_platform/test_models.py`** — Replaced `✓` with `[OK]` and `✗` with `[ERR]` in print statements.
- **`tournament_platform/check_tables.py`** — Replaced `✓` with `[OK]` in print statements.
- **`verify_setup.py`** — Replaced all Unicode emoji and checkmark characters with ASCII equivalents (e.g., `[OK]`, `[FAIL]`, `[PKG]`, `[DB]`, `[AI]`, etc.) to ensure Windows console compatibility.

### Remaining known issues

- **Other CLI scripts may still hit the same Windows console encoding issue:**  
  `initialize_rag.py`, `test_api.py`, and `tournament_platform/services/rules_ingestion.py` contain Unicode emoji in `print()` statements. These are not part of the required baseline check scripts, but may fail on Windows consoles without UTF-8 encoding.
- **Streamlit UI files intentionally retain emojis:**  
  Files under `tournament_platform/app/` (pages, components) use emojis in `st.title()`, `st.button()`, etc. These render correctly in the browser and do not need modification.
- **`ffmpeg` not found:**  
  `verify_setup.py` emits a `RuntimeWarning` from `pydub` about missing `ffmpeg`. This does not block setup but may affect audio processing features.

### How to start the app

```bash
# API server
python tournament_platform/api/server.py

# Streamlit frontend
streamlit run tournament_platform/app/main.py
```

## Local feature flags

Feature flags are defined in [`tournament_platform/services/settings.py`](tournament_platform/services/settings.py) and can be overridden via environment variables or a `.env` file. A template is provided at [`tournament_platform/.env.example`](tournament_platform/.env.example).

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:8000` | Base URL for the FastAPI backend used by the Streamlit frontend. |
| `OLLAMA_MODEL` | `llama3:latest` | Ollama model identifier for AI features. |
| `ENABLE_VOICE_ENTRY` | `True` | Enable voice-based match entry (faster-whisper / SpeechRecognition). |
| `ENABLE_RULES_ASSISTANT` | `True` | Enable the AI rules assistant (RAG over tournament rule documents). |
| `ENABLE_RANKING_INTELLIGENCE` | `True` | Enable ranking intelligence features (AI-enhanced ranking insights). |
| `ENABLE_SPOKEN_CONFIRMATION` | `False` | Enable spoken confirmation prompts after voice actions. |
| `KEEP_AUDIO_FILES` | `False` | Keep temporary audio files after transcription (useful for debugging). |
| `SPEECH_MODEL_SIZE` | `base` | Whisper model size for speech-to-text transcription (`tiny`, `base`, `small`, `medium`, `large-v3`). |

### Usage

1. Copy `.env.example` to `.env` in the `tournament_platform/` directory.
2. Adjust values as needed.
3. The settings module loads `.env` automatically via `python-dotenv`.

### Notes

- Feature flags are read at runtime; restart the app after changing `.env`.
- The `API_BASE_URL` flag replaces the previous hardcoded `http://localhost:8000` in the frontend.
- The `SPEECH_MODEL_SIZE` flag controls the Whisper model used by the speech service.

## Page consolidation

The Rules Assistant page has been merged into the AI Assistant page. Users now access rules Q&A through the **Rules Q&A** tab inside the AI Assistant page. The old `rules_assistant.py` page file has been removed from the UI navigation.

## RAG Knowledge Base Initialization

The AI Assistant (Rules Q&A tab) uses a ChromaDB-backed RAG (Retrieval-Augmented Generation) knowledge base built from the tournament rule PDFs.

### Prerequisites

1. **Ollama must be running** with the required models:
   ```powershell
   ollama serve
   ollama pull llama3:latest
   ollama pull nomic-embed-text
   ```

2. **Rule documents** should be placed in `tournament_platform/data/docs/`. The platform ships with the ITTF rules PDF.

### Initialize / Re-initialize the Knowledge Base

```powershell
python initialize_rag.py
```

This script:
- Connects to Ollama for embeddings (`nomic-embed-text`)
- Reads all PDFs from `tournament_platform/data/docs/`
- Splits them into chunks and stores them in ChromaDB at `data/chroma_db/`

### Verify the Knowledge Base

```powershell
python verify_setup.py
```

Look for `[RAG]` checks passing. If the knowledge base is empty or missing, re-run `initialize_rag.py`.

### Troubleshooting RAG

- **"No relevant rules found"**: The knowledge base may be empty. Re-run `initialize_rag.py`.
- **Ollama connection errors**: Ensure `ollama serve` is running and the model is pulled.
- **ChromaDB path**: Set `CHROMA_DB_PATH` in `.env` if you want to store the vector DB elsewhere.

## Voice privacy behavior

The voice/text match entry system is designed with a local-first, minimal-retention privacy model.

### Audio processing

- **Local transcription**: When using the default `faster-whisper` backend, audio is transcribed entirely on the local machine. No audio data is sent to external services.
- **Temporary files**: Audio is written to a temporary file (`.wav`) only for the duration of transcription.
- **Default deletion**: Temporary audio files are **deleted immediately after transcription** by default.
- **Debug retention**: Set `KEEP_AUDIO_FILES=true` in `.env` to retain temp audio files for debugging. When enabled, the UI shows the file path where audio was saved.

### Data retention

- **No raw audio in database**: Raw audio bytes or file paths are never stored in the database.
- **Transcripts**: Transcripts are held in Streamlit session state only (`st.session_state`). They are not persisted to the database unless an operator explicitly submits a match result through the confirm-and-submit flow.
- **Match results**: Only the structured result (player names, score, winner, tournament) is stored when the operator confirms and submits.

### Logging

- **Defensive logging**: API endpoints log only metadata (match IDs, status, previews) — not full transcripts, player emails, or raw audio paths.
- **Debug mode**: Sensitive path information is only surfaced in the UI when `KEEP_AUDIO_FILES=true`.

### User-facing notices

- A privacy notice is displayed near the voice entry UI in both:
  - `tournament_platform/app/pages/voice_scorekeeper.py`
  - `tournament_platform/app/pages/tournament_setup.py`
- The notice informs users that audio is processed locally, temp files are deleted by default, and confirmation is required before submission.
