# 🏓 Tournament Platform

A modern tournament management platform with AI-powered match analysis, real-time standings, and a multi-page Streamlit interface.

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
Edit `.env` and set at least `OLLAMA_HOST` and `OLLAMA_MODEL` if you plan to use AI features.

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
streamlit run tournament_platform/app/main.py
```

Open `http://localhost:8501` in your browser.

For a guided walkthrough of the AI quick-win features, see [QUICK_WINS.md](QUICK_WINS.md).

---

## ☁️ Streamlit Cloud deployment

**Use Python 3.11 in the Streamlit Cloud "Advanced settings" when deploying.**

This app requires **Python >=3.11** (see `requires-python` in `pyproject.toml`) because
recent Streamlit releases (`streamlit>=1.58.0`) require Python 3.10+, and we pin the
supported range to `>=3.11,<3.13` to avoid accidental breakage on future Python versions.

Recommended deployment Python version: **3.11**.

- Dependencies are installed from the repo-root `pyproject.toml` (`[project]` table).
  That file is the source of truth; `tournament_platform/requirements.txt` is only a
  legacy local snapshot and is not used by Streamlit Cloud.
- `pyaudio` (real-time microphone capture, needs the system PortAudio library) is an
  **optional** dependency (`[live]` extra) and is intentionally NOT installed on
  Streamlit Cloud, where microphone input and PortAudio are unavailable. These live
   voice features are therefore not available in the cloud deployment.
- The database schema is created automatically at app startup via `alembic upgrade head`
  (`ensure_schema()` in `tournament_platform/models.py`), so no manual `alembic upgrade head`
  step is required on Streamlit Cloud. This applies the full migration history, which is the
  canonical schema source. Note: Streamlit Cloud's filesystem is ephemeral, so the SQLite
  database (`tournament_platform/data/tournament.db`) is recreated on each deploy/restart and
  data is not persisted — use persistent storage or an external database for production data.
- Entry point: `tournament_platform/app/main.py`
  (run `streamlit run tournament_platform/app/main.py`).
- The FastAPI backend is started automatically in a background thread at app
  startup (`ensure_api_server()` in `tournament_platform/app/api_client.py`) so the
  frontend's `http://localhost:8000` calls work on a single Streamlit Cloud app,
  where only the Streamlit process is launched. Set `API_BASE_URL` to an external
  service if you deploy the API separately.
- If the app was previously deployed with Python 3.9, **delete the app and redeploy it
  with Python 3.11 selected in Advanced settings** — Streamlit Cloud keeps the Python
  version from the original deploy and won't pick up the new requirement otherwise.

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
| Frontend | Streamlit |
| API | FastAPI + Uvicorn |
| Database | SQLite / SQLAlchemy + Alembic |
| AI | Ollama + ChromaDB (RAG) |
| Auth | Streamlit Authenticator |
