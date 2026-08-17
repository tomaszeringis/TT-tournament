# 🏓 Tournament Platform - Quick Start Guide

## ⚡ 5-Minute Setup

Run all commands from the **repository root** (`tournament_platform/`).

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -e .
```

For real-time voice / microphone features (needs `pyaudio` and PortAudio system library),
install the optional `[live]` extra:

```bash
pip install -e ".[live]"
```

### 3. Configure environment

```powershell
cd tournament_platform
copy .env.example .env
```

Edit `.env` and set at least `OLLAMA_HOST`, `OLLAMA_MODEL`, and voice ASR variables
(`VOICE_ASR_MODEL_SIZE`, `VOICE_ASR_DEVICE`, `VOICE_ASR_COMPUTE_TYPE`) if you plan
to use voice scoring. Ollama must be running for AI features.

### 4. Initialize Database

```bash
cd ..
python -m alembic -c tournament_platform/alembic.ini upgrade head
```

> The schema is also created automatically at app startup via `ensure_schema()` in
> `tournament_platform/models.py`, so this manual step is optional when running the
> Streamlit app directly. It is required only if you run the FastAPI backend separately.

### 5. Start the API Server (Terminal 1)

```bash
uvicorn tournament_platform.api.main:app --host 0.0.0.0 --port 8000 --reload
```

or equivalently:

```bash
python -m tournament_platform.api.main
```

API running at `http://localhost:8000`

### 6. Start the Streamlit App (Terminal 2)

```bash
streamlit run streamlit_app.py
```

The root `streamlit_app.py` is the canonical entrypoint — it imports and calls
`main()` from `tournament_platform/app/main.py`. No `PYTHONPATH` is needed.

Streamlit running at `http://localhost:8501`

### 7. (Optional) Initialize the RAG Service

The RAG (Retrieval-Augmented Generation) service powers the AI rules assistant by
storing tournament rules in a local ChromaDB vector store and retrieving the most
relevant ones at query time.

**Prerequisites:** Ollama must be running and the embedding model pulled:

```bash
ollama serve
ollama pull nomic-embed-text
```

**Initialize with built-in sample rules** (one-time, run from repo root):

```bash
python initialize_rag.py
```

This loads sample table-tennis rules into the `tournament_rules` ChromaDB collection
and runs a quick retrieval test.

**Or ingest your own rulebook PDF:**

```bash
python -m tournament_platform.services.rules_ingestion data/rules.pdf
```

This chunks the PDF (1000 chars / 200 overlap), generates embeddings with
`nomic-embed-text`, and stores them in `data/chroma_db`. The script is idempotent.

The knowledge base is enabled via `ENABLE_RULES_ASSISTANT=True` in `.env`
(default on) and used by `tournament_platform/services/ai_engine.py`
(`retrieve_rules_context`, `batch_initialize_rules`).

---

## ☁️ Streamlit Cloud Deployment

- **Entry point:** `streamlit_app.py` (at the repository root)
- **Python:** 3.13 (3.12 also works). The app requires `>=3.11,<3.14`.
- **Dependencies:** installed from `pyproject.toml` (not `requirements.txt`).
- **Secrets:** set `DATABASE_URL` (PostgreSQL) for persistence; configure auth
  credentials, `HF_TOKEN`, and `API_BASE_URL` (optional ngrok bridge for Ollama).
- **Database:** schema is created automatically at startup via `ensure_schema()`.
  No manual `alembic upgrade head` step needed on Cloud.
- **The Streamlit app does NOT start a FastAPI server in-process.** For optional
  API features, run the FastAPI backend as a **separate process** and expose it
  via ngrok. See [README.md](README.md) for the full ngrok bridge instructions.

---

## 🐳 Docker Deployment

```bash
docker compose up --build
```

This starts two services:
- **API** — FastAPI backend on port `8000` (`http://localhost:8000/docs`)
- **Web** — Streamlit frontend on port `8501` (`http://localhost:8501`)

Data is persisted in a local `data/` volume.

---

## 🎯 Next Steps

### Create Your First Tournament

1. **Open the app** at `http://localhost:8501`
2. **Login** with credentials from `tournament_platform/app/config.yaml`
3. **Go to "Tournament"** page
4. **Register Players** via the participants section
5. **Create Tournament** and generate the bracket
6. **Report Match Results** from the match view

### Monitor the Dashboard

1. **Go to "Dashboard"** page
2. **View Player Standings** with AG-Grid table
3. **Click a player** to see their radar chart stats

### Admin Panel

1. **Go to "Admin / Operator"** page (admin role required)
2. **View database statistics**
3. **Filter and manage matches**
4. **Check system health**

---

## 📚 Full Documentation

For detailed information, see: [SETUP_GUIDE.md](SETUP_GUIDE.md)

### Key topics:
- Alembic database migrations
- Pydantic model usage
- RAG system with ChromaDB
- Streamlit AG-Grid & Plotly
- FastAPI async endpoints
- Error logging

---

## 🧪 API Testing

```bash
python test_api.py
```

This script tests:
- Health check endpoint
- Match reporting
- Error handling

---

## 📁 Project Structure

```
tournament_platform/                    # Repository root
├── streamlit_app.py                    # Streamlit Cloud / local root entrypoint
├── pyproject.toml                      # Package config & dependencies (canonical)
├── Dockerfile                          # Docker image build
├── docker-compose.yml                  # Docker Compose (api + web services)
├── README.md                           # Main documentation
├── QUICKSTART.md                       # This quick start guide
├── initialize_rag.py                   # One-time RAG knowledge base seeding
├── test_api.py                         # API integration tests
├── .streamlit/                         # Streamlit Cloud config
│   └── config.toml                     # Theme configuration
├── tournament_platform/                # Main Python package
│   ├── __init__.py
│   ├── models.py                       # SQLAlchemy database models
│   ├── config/
│   │   ├── __init__.py                 # Settings (pydantic-settings)
│   │   └── runtime.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── db_config.py                # Database URL resolution & engine setup
│   ├── .env.example                    # Environment variable template
│   ├── alembic.ini                     # Alembic migration config
│   ├── alembic/                        # Database migrations
│   │   ├── env.py
│   │   ├── script.py.moto
│   │   └── versions/                   # 001_initial through 019+
│   ├── api/
│   │   ├── server.py                   # FastAPI app (defines `app`)
│   │   ├── main.py                     # API entrypoint (defines `main()`, __main__)
│   │   ├── schemas.py                  # Pydantic response schemas
│   │   ├── routers/
│   │   │   └── ollama.py               # Ollama bridge router (bearer-token protected)
│   │   └── __pycache__/
│   ├── app/
│   │   ├── main.py                     # Streamlit UI entrypoint (calls `main()`)
│   │   ├── config.yaml                 # Streamlit auth config
│   │   ├── utils.py                    # Shared UI utilities
│   │   ├── design_system.py            # Global styles & brand
│   │   ├── api_client.py               # API client with runtime mode detection
│   │   ├── api_status.py               # App status / mode indicator
│   │   ├── settings.py                 # Streamlit-specific settings
│   │   ├── components/                 # Reusable UI components
│   │   └── pages/                      # Streamlit pages
│   │       ├── home.py
│   │       ├── events_draws.py
│   │       ├── dashboard.py
│   │       ├── rankings.py
│   │       ├── admin.py
│   │       ├── ai_assistant.py
│   │       ├── voice_scorekeeper.py
│   │       ├── video_scorekeeper.py
│   │       ├── video_scorekeeper_live.py
│   │       ├── schedule_board.py
│   │       ├── public_board.py
│   │       ├── public_registration.py
│   │       └── ...
│   ├── services/                       # Business logic
│   │   ├── ai_engine.py
│   │   ├── ai_facade.py
│   │   ├── match_manager.py
│   │   ├── match_reporting.py
│   │   ├── ranking_service.py
│   │   ├── rules_ingestion.py
│   │   ├── rules_retrieval.py
│   │   ├── tournament_engine.py
│   │   ├── umpire_engine.py
│   │   ├── calendar_service.py
│   │   ├── health_check_service.py
│   │   ├── audit_service.py
│   │   └── ...
│   ├── app/services/                   # Streamlit-specific services
│   │   ├── ollama_bridge.py
│   │   ├── voice_asr.py
│   │   ├── voice_tts.py
│   │   ├── voice_parser.py
│   │   ├── commentary_service/...
│   │   ├── match_analytics/...
│   │   └── ...
│   ├── middleware/
│   │   └── audit_middleware.py
│   ├── multimodal_ai/
│   │   ├── intent_classifier/
│   │   ├── adapters/
│   │   ├── coaching/...
│   │   └── feature_extractors/...
│   ├── data/                           # Runtime data (auto-created)
│   │   ├── tournament.db               # SQLite database
│   │   ├── bracket.json
│   │   ├── chroma_db/                  # ChromaDB storage (RAG)
│   │   └── docs/                       # Reference PDFs
│   ├── logs/
│   │   └── app.log                     # Application logs
│   └── services/requirements.txt       # Legacy local snapshot (not for Cloud)
├── teams/
│   ├── manifest.json                   # Team data
│   └── TEAMS_SETUP.md
├── scripts/                            # Utility scripts
│   ├── index_rag.py
│   ├── migrate_sqlite_to_postgres.py
│   └── ...
├── tests/                              # Test suite (pytest)
│   ├── test_*.py
│   ├── test_multimodal/
│   └── voice/
└── plans/                              # Implementation plans & summaries
```

---

## 🔧 Useful Commands

```bash
# Database migrations (run from repo root)
python -m alembic -c tournament_platform/alembic.ini current
python -m alembic -c tournament_platform/alembic.ini upgrade head
python -m alembic -c tournament_platform/alembic.ini downgrade -1

# Run the API backend
uvicorn tournament_platform.api.main:app --host 0.0.0.0 --port 8000 --reload

# Run the Streamlit frontend
streamlit run streamlit_app.py

# Initialize the RAG knowledge base (one-time)
python initialize_rag.py

# Testing
pytest tests/ -q
```

---

## 🆘 Common Issues

### "ModuleNotFoundError: No module named 'tournament_platform'"
Run from the **repository root** and use the root entrypoint:
```bash
streamlit run streamlit_app.py
```
If you need to use `tournament_platform/app/main.py` directly, set `PYTHONPATH`
to the repository root first:
```powershell
$env:PYTHONPATH = "."
```

### "No 'script_location' key found in configuration" (Alembic)
Use the config file explicitly:
```bash
python -m alembic -c tournament_platform/alembic.ini upgrade head
```

### Missing `gtts` / RealtimeTTS backend
```powershell
.\.venv\Scripts\pip install gtts
```

### Ollama connection error
```bash
# Start Ollama in another terminal
ollama serve

# Pull the model
ollama pull llama3:latest
```

### Streamlit pages not loading
- Ensure files are in `tournament_platform/app/pages/` directory
- Restart the server with `Ctrl+C` then run again

### Port already in use?
```bash
# Change Streamlit port
streamlit run streamlit_app.py --server.port 8502
```

---

## 📊 Features Overview

| Feature | Technology | Location |
|---------|-----------|----------|
| **Database** | SQLAlchemy + Alembic | `models.py`, `alembic/` |
| **ORM Models** | Pydantic | `models.py` + `services/` |
| **AI Engine** | Ollama + ChromaDB | `services/ai_engine.py` |
| **RAG Service** | ChromaDB + Ollama embeddings | `services/rules_ingestion.py` |
| **Frontend** | Streamlit + AG-Grid | `app/pages/` |
| **API** | FastAPI (Async) | `api/server.py` |
| **Logging** | Python logging | `logs/app.log` |

---

## 🚀 Production Checklist

- [ ] Update `app/config.yaml` with real credentials
- [ ] Configure `TEAMS_WEBHOOK_URL` in `config/__init__.py`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Set up proper error monitoring
- [ ] Configure HTTPS/SSL
- [ ] Add authentication tokens for API
- [ ] Set up automated backups

---

**Questions?** Check the [full documentation](SETUP_GUIDE.md)

**Last Updated:** August 1, 2026
