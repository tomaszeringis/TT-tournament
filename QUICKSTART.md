# 🏓 Tournament Platform - Quick Start Guide

## ⚡ 5-Minute Setup

Run all commands from the **repository root** (`C:\Users\TomasZeringis\PycharmProjects\tournament_platform`).

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

### 3. Configure environment
```powershell
cd tournament_platform
copy .env.example .env
```
Edit `.env` and set at least `OLLAMA_HOST` and `OLLAMA_MODEL` if you plan to use AI features.

### 4. Initialize Database
```bash
cd ..
python -m alembic -c tournament_platform/alembic.ini upgrade head
```

### 5. Start the API Server (Terminal 1)
```bash
python -m tournament_platform.api.server
```
✅ API running at `http://localhost:8000`

### 6. Start the Streamlit App (Terminal 2)
```powershell
$env:PYTHONPATH = "C:\Users\TomasZeringis\PycharmProjects\tournament_platform"
streamlit run tournament_platform/app/main.py
```
✅ Streamlit running at `http://localhost:8501`

**Notes:**
- `PYTHONPATH` must include the repository root so absolute imports like `tournament_platform.config` resolve correctly.
- If you get `ImportError: Failed to load GTTSEngine`, install the missing TTS dependency:
  ```bash
  .\.venv\Scripts\pip install gtts
  ```

---

## 🎯 Next Steps

### Create Your First Tournament

1. **Open the app** at `http://localhost:8501`
2. **Login** with your credentials (from `app/config.yaml`)
3. **Go to "Tournament Setup"** tab
4. **Register Players** on the right side
5. **Create Tournament** in the left sidebar
6. **Report Match Results** in the center panel

### Monitor the Dashboard

1. **Go to "Dashboard"** tab
2. **View Player Standings** with AG-Grid table
3. **Click a player** to see their radar chart stats

### Admin Panel

1. **Go to "Admin"** tab
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
├── pyproject.toml                      # Package config & dependencies
├── README.md                           # This file
├── QUICKSTART.md                       # This quick start guide
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

## 🔗 Useful Commands

```bash
# Database migrations (run from repo root)
python -m alembic -c tournament_platform/alembic.ini current
python -m alembic -c tournament_platform/alembic.ini upgrade head
python -m alembic -c tournament_platform/alembic.ini downgrade -1

# Testing
pytest tournament_platform/ -q

# Running
python -m tournament_platform.api.server          # API server
streamlit run tournament_platform/app/main.py     # Frontend
python initialize_rag.py                          # One-time RAG init
```

---

## 🆘 Common Issues

### "ModuleNotFoundError: No module named 'tournament_platform'"
Run from the **repository root** and ensure the root is on `PYTHONPATH`:
```powershell
$env:PYTHONPATH = "C:\Users\TomasZeringis\PycharmProjects\tournament_platform"
streamlit run tournament_platform/app/main.py
```

### "No 'script_location' key found in configuration" (Alembic)
Use the root `alembic.ini` explicitly:
```powershell
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
- Ensure files are in `app/pages/` directory
- Restart the server with `Ctrl+C` then run again

---

## 📊 Features Overview

| Feature | Technology | Location |
|---------|-----------|----------|
| **Database** | SQLAlchemy + Alembic | `models.py`, `alembic/` |
| **ORM Models** | Pydantic | `models.py` + `services/` |
| **AI Engine** | Ollama + ChromaDB | `services/ai_engine.py` |
| **Frontend** | Streamlit + AG-Grid | `app/pages/` |
| **API** | FastAPI (Async) | `api/server.py` |
| **Logging** | Python logging | `logs/app.log` |

---

## 🚀 Production Checklist

- [ ] Update `app/config.yaml` with real credentials
- [ ] Configure `TEAMS_WEBHOOK_URL` in `api/server.py`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Set up proper error monitoring
- [ ] Configure HTTPS/SSL
- [ ] Add authentication tokens for API
- [ ] Set up automated backups

---

**Questions?** Check the [full documentation](SETUP_GUIDE.md)

**Last Updated:** July 8, 2026

