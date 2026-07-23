# 🏓 Tournament Platform

A modern tournament management platform with AI-powered match analysis, real-time standings, and a multi-page Streamlit interface. Supports **local voice scoring** (push-to-talk and experimental continuous listening) using faster-whisper and streamlit-webrtc.

## 🚀 Quick Start

### 1. Install dependencies
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

For real-time voice / microphone features (which need `pyaudio` and PortAudio),
install the optional `[live]` extra:

```powershell
pip install -e ".[live]"
```

### 2. Configure environment
```powershell
cd tournament_platform
copy .env.example .env
```
Edit `.env` and set at least `OLLAMA_HOST`, `OLLAMA_MODEL`, and voice ASR
variables (`VOICE_ASR_MODEL_SIZE`, `VOICE_ASR_DEVICE`, `VOICE_ASR_COMPUTE_TYPE`)
if you plan to use voice scoring.

### 3. Initialize the database (from repo root)
```powershell
cd ..
python -m alembic -c tournament_platform/alembic.ini upgrade head
```

### 4. Start the API server (Terminal 1)
```powershell
python -m tournament_platform.api.server
```

### 5. Start the frontend (Terminal 2)
```powershell
$env:PYTHONPATH = "C:\Users\TomasZeringis\PycharmProjects\tournament_platform"
streamlit run streamlit_app.py
```

Open `http://localhost:8501` in your browser.

For a guided walkthrough of the AI quick-win features, see [QUICK_WINS.md](QUICK_WINS.md).

---

## ☁️ Streamlit Cloud deployment

**Use Python 3.13 (or 3.12) in the Streamlit Cloud "Advanced settings" when deploying.**

This app supports **Python >=3.11,<3.14** (see `requires-python` in `pyproject.toml`).
Recent Streamlit releases (`streamlit>=1.58.0`) require Python 3.10+, and all runtime
dependencies (including `streamlit-webrtc` and `av`) install and import successfully on
Python 3.13. The supported range is pinned to `<3.14` to avoid accidental breakage on
future Python versions.

Recommended deployment Python version: **3.13** (3.12 also works).

- Dependencies are installed from the repo-root `pyproject.toml` (`[project]` table).
  That file is the source of truth; `tournament_platform/requirements.txt` is only a
  legacy local snapshot and is not used by Streamlit Cloud.
- `streamlit-webrtc` (and its `av`/`numpy` runtime deps) are declared in the default
  **[project] dependencies** (not just the `[live]` extra), so Streamlit Cloud installs
  them automatically. The WebRTC-based "Continuous Listening" and "Live Camera" features
  therefore render and work on Streamlit Cloud when the browser grants microphone/camera
  permissions. `pyaudio` (real-time microphone capture, needs the system PortAudio
  library) remains an **optional** dependency (`[live]` extra) and is intentionally NOT
  installed on Streamlit Cloud, where PortAudio is unavailable.
- If Streamlit Cloud reports `streamlit-webrtc is not installed`, confirm Cloud is using
  the repo-root `pyproject.toml`, confirm `streamlit-webrtc` is present in the `[project]`
  `dependencies` list (not only `[live]`), and redeploy. Both affected pages
  (`voice_scorekeeper.py`, `video_scorekeeper_live.py`) already guard the import with a
  friendly warning fallback, so a missing package never crashes the app.
- The database schema is created automatically at app startup via `alembic upgrade head`
  (`ensure_schema()` in `tournament_platform/models.py`), so no manual `alembic upgrade head`
  step is required on Streamlit Cloud. This applies the full migration history, which is the
  canonical schema source. Note: Streamlit Cloud's filesystem is ephemeral, so the SQLite
  database (`tournament_platform/data/tournament.db`) is recreated on each deploy/restart and
  data is not persisted — use persistent storage or an external database for production data.
- Entry point: `streamlit_app.py` at the repository root
  (run `streamlit run streamlit_app.py`). This module calls
  `main()` from `tournament_platform/app/main.py`, which is the real Streamlit UI
  script. The `main()` function is the Streamlit entrypoint; importing the module
  does not start the UI or any external server, so it is safe to import.
  Both files are valid Streamlit entrypoints; the root `streamlit_app.py` is
  the recommended **Main module** for Streamlit Cloud.
- **The Streamlit app does NOT start a Uvicorn/FastAPI server in-process.**
  `ensure_api_server()` is disabled inside the Streamlit app (including Streamlit
  Cloud) so it never steals the app's port or fails the healthcheck. For optional
  API features, run the FastAPI backend as a **separate** process (see the
  "Optional local API + ngrok" section below) and set `API_BASE_URL` to that
  external service. Manual scoring, live scoreboard, and match analytics work
  without the API via the local database.
- **Seeing `Uvicorn server started on ...:8501` in the build log is expected and
  NOT an error.** Streamlit itself runs on a Uvicorn/Starlette server and prints
  that banner when its own server starts on port 8501 (the Streamlit app port).
  This is the Streamlit app starting up, not the FastAPI backend. The FastAPI
  backend binds port `8000` and must never run as the Streamlit Cloud main module.
  A real problem is a `connection refused` on `/healthz` *before* that banner
   appears, which means the entrypoint crashed at import — in that case confirm the
   Main module is `streamlit_app.py` and that the build used `pyproject.toml`.

## 🔌 Optional local API + ngrok (Streamlit Cloud)

The Streamlit Cloud app runs in **local Streamlit mode** by default and needs no
external API. All core features (manual scoring, tournament management, live
scoreboard, match analytics, voice scorekeeper, admin tools) work against the
local SQLite database directly. An external FastAPI backend is **optional**.

Runtime modes (resolved from env vars and Streamlit secrets, in that order):

| Mode | When |
| --- | --- |
| `local_streamlit` | `API_BASE_URL` not set — app uses local services. |
| `external_api` | `API_BASE_URL` set and reachable (`${API_BASE_URL}/health`, 1.5 s timeout). |
| `optional_api_unavailable` | `API_BASE_URL` set but unreachable and `API_REQUIRED=false` — app falls back to local services. |
| `required_unavailable` | `API_BASE_URL` set, unreachable, and `API_REQUIRED=true` — a clear red error is shown (the app still does not crash). |

The dashboard shows **App Status ✅ Ready / Mode: Local Streamlit** by default.
When an API is configured and reachable it shows **API Status ✅ Connected /
Mode: External API**. An unreachable optional API shows **API Status ⚠️ Optional
API unavailable / Mode: Local fallback** (a warning, never a fatal error).

### Run the FastAPI backend locally

The backend is a **separate process** and must never be started by the Streamlit
Cloud app:

```bash
uvicorn tournament_platform.api.main:app --host 127.0.0.1 --port 8000 --reload
```

or:

```bash
python -m tournament_platform.api.main
```

### Expose it through ngrok

```bash
ngrok http 8000
```

Then set Streamlit Cloud **secrets** (Settings → Secrets) to the ngrok URL:

```toml
API_BASE_URL = "https://your-ngrok-url.ngrok-free.app"
API_REQUIRED = "false"
API_TOKEN = "your-long-random-token"
```

`API_TOKEN` (if set) is sent as `Authorization: Bearer <token>` on every request
and is never logged or shown in the UI. Set `API_REQUIRED = "true"` only if the
app must hard-fail when the backend is down.

### Local Ollama + FastAPI bridge (no Ollama on Cloud)

Streamlit Cloud **never** talks to Ollama directly and Ollama is **not** exposed
through ngrok. The FastAPI backend on your laptop is the single bridge:

```text
Streamlit Cloud  ->  API_BASE_URL (ngrok -> FastAPI:8000)  ->  local Ollama (127.0.0.1:11434)
```

1. Start and prepare local Ollama:

   ```bash
   ollama serve
   ollama pull llama3.1:8b
   curl http://127.0.0.1:11434/api/tags
   ```

2. Run the FastAPI backend locally (it calls `OLLAMA_BASE_URL`, default
   `http://127.0.0.1:11434`):

   ```bash
   poetry run uvicorn tournament_platform.api.main:app --host 127.0.0.1 --port 8000 --reload
   ```

3. Expose only the FastAPI server through ngrok (never Ollama):

   ```bash
   ngrok http 127.0.0.1:8000
   ```

4. Streamlit Cloud **secrets** (`API_BASE_URL` is the ngrok URL):

   ```toml
   API_BASE_URL = "https://your-fastapi-ngrok-url.ngrok-free.app"
   API_REQUIRED = "false"
   API_TOKEN = "your-long-random-token"
   OLLAMA_MODEL = "llama3.1:8b"
   HF_TOKEN = "optional-hugging-face-token"
   TTS_DEFAULT_MODE = "Browser speech"
   VOICE_INPUT_MODE = "manual"
   ```

   > **Do NOT set `OLLAMA_BASE_URL` on Streamlit Cloud.** That points to the
   > Cloud container, not your laptop. Only the local FastAPI process should set
   > `$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"`. The Cloud app reaches
   > Ollama only through the FastAPI ngrok bridge.

5. Local FastAPI environment (PowerShell), before starting the server above:

   ```powershell
   $env:API_TOKEN="your-long-random-token"
   $env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
   $env:OLLAMA_MODEL="llama3.1:8b"
   poetry run uvicorn tournament_platform.api.main:app --host 127.0.0.1 --port 8000 --reload
   ```

The bridge exposes `GET /health`, `GET /ollama/status`, `POST /ollama/generate`,
and `POST /ollama/chat`. In local Streamlit mode (no `API_BASE_URL`) the app uses
the local `ollama` client directly. The FastAPI bridge adds the bearer token and
falls back to template commentary if Ollama is down.

### ngrok caveats

- **The ngrok URL changes every time the tunnel restarts** — update the
  `API_BASE_URL` secret after each restart, or use a paid fixed domain.
- **Your laptop must stay awake** (no sleep/hibernate) or the server dies.
- **The API server process must keep running** (the `uvicorn` command above).
- **The ngrok tunnel must keep running** (the `ngrok http 8000` command above).
- When the tunnel or server stops, the app automatically returns to **local
  fallback mode** (if `API_REQUIRED=false`), so scoring and analytics keep
  working.
- Do **not** set `API_BASE_URL` to `localhost`/`127.0.0.1` on Streamlit Cloud —
  those addresses refer to the Cloud container, not your laptop. They are only
  valid for local development on the same machine as the API.

- If the app was previously deployed with an incompatible Python (e.g. a version
  outside `>=3.11,<3.14`), **delete the app and redeploy it with Python 3.13 selected
  in Advanced settings** — Streamlit Cloud keeps the Python version from the original
  deploy and won't pick up the new requirement otherwise.

## Database migrations

Run migrations from the repository root:

```bash
python -m alembic -c tournament_platform/alembic.ini upgrade head
```

Useful commands:

```bash
python -m alembic -c tournament_platform/alembic.ini current
python -m alembic -c tournament_platform/alembic.ini heads
python -m alembic -c tournament_platform/alembic.ini history
```

Notes:
- The app uses `DATABASE_URL` when provided. If it is not provided, it falls back to a
  local SQLite database under `data/` (path resolved from `pyproject.toml` / `models.py`).
- The schema is also created automatically at app startup via `alembic upgrade head`
  (`ensure_schema()` in `tournament_platform/models.py`), so no manual step is required on
  Streamlit Cloud. On Streamlit Cloud the `data/` directory is ephemeral, so data is not
  persisted between restarts.
- Do **not** import `tournament_platform.alembic.env` directly. Use the Alembic CLI or
  `alembic.command.upgrade()` together with `alembic.config.Config`.

## TTS on Streamlit Cloud

Browser speech is the recommended TTS mode on Streamlit Cloud.

Piper is optional and intended for local desktop use (install via the `[tts]` extra:
`pip install -e ".[tts]"`). If Piper is not installed, the app automatically falls back
to browser speech or silent mode depending on the selected TTS setting, and never shows
a blocking error. Selecting "Piper local" when Piper is unavailable shows one friendly
info message and disables the option rather than crashing the page or spamming warnings.

PIPER_TTS_SETUP.md has the local setup steps.

---

## 🆘 Common Issues

**"ModuleNotFoundError: No module named 'tournament_platform'"**
Run from the **repository root** and set `PYTHONPATH` to the project root:
```powershell
$env:PYTHONPATH = "C:\Users\TomasZeringis\PycharmProjects\tournament_platform"
streamlit run tournament_platform/app/main.py
```

**"No 'script_location' key found in configuration" (Alembic)**
Use the root `alembic.ini` explicitly:
```powershell
python -m alembic -c tournament_platform/alembic.ini upgrade head
```

**Missing `gtts` / RealtimeTTS backend**
```powershell
.\.venv\Scripts\pip install gtts
```

**Ollama not responding?**
```powershell
ollama serve
ollama pull llama3:latest
```

**Database locked?** Stop all running Python processes and delete `tournament_platform/data/tournament.db` to start fresh.

---

## 📁 Project Structure

```
tournament_platform/                    # Repository root
├── pyproject.toml                      # Package config & dependencies
├── README.md                           # This file
├── tournament_platform/                # Main Python package
│   ├── __init__.py
│   ├── models.py                       # SQLAlchemy database models
│   ├── config/__init__.py              # Settings (pydantic-settings)
│   ├── .env.example                    # Environment variable template
│   ├── requirements.txt                # Python dependencies
│   ├── alembic.ini                     # Alembic migration config
│   ├── alembic/                        # Database migrations
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   ├── api/server.py                   # FastAPI backend
│   ├── app/
│   │   ├── main.py                     # Streamlit entry point
│   │   ├── config.yaml                 # Streamlit auth config
│   │   ├── utils.py                    # Shared UI utilities
│   │   ├── components/                 # Reusable UI components
│   │   │   ├── bracket_renderer.py
│   │   │   └── interactive_bracket/
│   │   └── pages/                      # Streamlit pages
│   │       ├── dashboard.py
│   │       ├── rankings.py
│   │       ├── tournament_setup.py
│   │       ├── admin.py
│   │       ├── voice_rules_chat.py
│   │       └── voice_scorekeeper.py
│   ├── services/                       # Business logic
│   │   ├── ai_engine.py
│   │   ├── ai_assistant.py
│   │   ├── bracket_manager.py
│   │   ├── calendar_service.py
│   │   ├── match_manager.py
│   │   ├── match_reporting.py
│   │   ├── ranking_service.py
│   │   ├── rules_ingestion.py
│   │   ├── rules_retrieval.py
│   │   ├── speech_service.py
│   │   ├── tournament_engine.py
│   │   └── umpire_engine.py
│   ├── data/                           # Runtime data (auto-created)
│   │   ├── tournament.db               # SQLite database
│   │   ├── bracket.json
│   │   └── docs/                       # Reference PDFs
│   └── test_*.py                       # Test suite
└── teams/manifest.json                 # Team data
```

---

## ⚙️ Environment Variables

Copy `tournament_platform/.env.example` to `tournament_platform/.env`. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8000` | FastAPI port |
| `DATABASE_URL` | `sqlite:///data/tournament.db` | Database connection string |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3:latest` | Chat model name |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model for RAG |
| `CHROMA_DB_PATH` | `data/chroma_db` | ChromaDB storage path |
| `TEAMS_WEBHOOK_URL` | *(empty)* | Teams notification webhook |
| `AUTH_COOKIE_KEY` | *(change me)* | Secret key for Streamlit auth |
| `VOICE_ASR_MODEL_SIZE` | `tiny.en` | faster-whisper model size for voice scoring |
| `VOICE_ASR_DEVICE` | `cpu` | Device: `cpu`, `cuda`, `auto` |
| `VOICE_ASR_COMPUTE_TYPE` | `int8` | Compute type: `int8`, `float16`, `float32` |
| `VOICE_ASR_BACKEND` | `faster_whisper` | ASR backend: `faster_whisper`, `speechbrain`, `vosk` |
| `VOICE_ENABLE_CONFIRMATION` | `true` | Require confirmation for score-setting commands |
| `VOICE_ENABLE_NOISE_FILTERING` | `false` | Enable noise gate |
| `VOICE_NOISE_THRESHOLD` | `0.0` | RMS noise threshold |
| `HF_TOKEN` | *(empty)* | Hugging Face token for model downloads |
| `SCORE_ENABLE_SOUNDS` | `false` | Enable browser sound cues |
| `KEEP_AUDIO_FILES` | `false` | Keep temp audio files for debugging |

For local development, the defaults work out of the box if you have Ollama running.

---

## 🗄️ Local Database Setup

The SQLite database is created automatically at `tournament_platform/data/tournament.db` on first run. Tables are created via SQLAlchemy's `init_db()`.

To manage schema with Alembic (run from repo root):

```powershell
# Check current migration version
python -m alembic -c tournament_platform/alembic.ini current

# Apply all pending migrations
python -m alembic -c tournament_platform/alembic.ini upgrade head

# Create a new migration after model changes
python -m alembic -c tournament_platform/alembic.ini revision --autogenerate -m "description"
```

---

## 🧪 Running Tests

Tests live inside `tournament_platform/` and use `pytest`. Run from the repo root:

```powershell
# Run all tests
pytest tournament_platform/

# Run a specific test file
pytest tournament_platform/test_models.py

# Run with verbose output
pytest -v tournament_platform/
```

Install dev dependencies first if needed:
```powershell
pip install -e ".[dev]"
```

---

## 🛠️ Common Commands

```powershell
# Verify the full setup
python verify_setup.py

# Quick status check
python status.py

# Initialize the RAG knowledge base
python initialize_rag.py

# Check database tables
python tournament_platform/check_tables.py

# Check schema
python tournament_platform/check_schema.py
```

---

## 🐛 Troubleshooting

**Port already in use?**
```powershell
# Change API port
python -m tournament_platform.api.server  # edit API_PORT in .env

# Change Streamlit port
streamlit run tournament_platform/app/main.py --server.port 8502
```

**"ModuleNotFoundError: No module named 'tournament_platform'"**
Run from the **repository root** and set `PYTHONPATH` to the project root:
```powershell
$env:PYTHONPATH = "C:\Users\TomasZeringis\PycharmProjects\tournament_platform"
streamlit run tournament_platform/app/main.py
```

**Missing `gtts` / RealtimeTTS backend**
```powershell
.\.venv\Scripts\pip install gtts
```

**Ollama not responding?**
```powershell
ollama serve
ollama pull llama3:latest
```

**Database locked?** Stop all running Python processes and delete `tournament_platform/data/tournament.db` to start fresh.

---

## 📦 Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Streamlit >=1.58.0 |
| API | FastAPI >=0.137.1 + Uvicorn |
| Database | SQLite / SQLAlchemy >=2.0.51 + Alembic >=1.18.4 |
| AI | Ollama >=0.6.2 + ChromaDB >=1.5.9 (RAG) |
| Auth | Streamlit Authenticator ==0.3.2 |
| Voice ASR | faster-whisper >=1.0.0 (local) |
| Voice Capture | streamlit-webrtc >=0.75,<0.76 + av >=12.0.0 |
