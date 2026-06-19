# 🏓 Tournament Platform - Quick Start Guide

## ⚡ 5-Minute Setup

### 1. Install Dependencies
```bash
python -m pip install -r tournament_platform/requirements.txt
```

### 2. Initialize Database
```bash
cd tournament_platform
python -m alembic upgrade head
```

### 3. Initialize RAG (Optional)
```bash
cd ..
python initialize_rag.py
```

### 4. Start the API Server
```bash
cd tournament_platform
python api/server.py
```
✅ API running at `http://localhost:8000`

### 5. Start the Streamlit App (in a new terminal)
```bash
cd tournament_platform/app
python -m streamlit run main.py
```
✅ Streamlit running at `http://localhost:8501`

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
tournament_platform/
├── main.py                    # Entry point
├── models.py                  # SQLAlchemy models
├── alembic/                   # Database migrations
├── api/server.py              # FastAPI async server
├── app/main.py                # Streamlit entry
├── app/pages/                 # Multi-page structure
│   ├── dashboard.py
│   ├── tournament_setup.py
│   └── admin.py
├── services/ai_engine.py      # AI + RAG
└── data/                      # Database & RAG storage
```

---

## 🔗 Useful Commands

```bash
# Database migrations
python -m alembic current              # Check current migration
python -m alembic upgrade head         # Apply all migrations
python -m alembic downgrade -1         # Undo last migration

# Testing
python test_api.py          # Test API endpoints
python initialize_rag.py    # Initialize RAG system

# Running
python api/server.py        # Start API
python -m streamlit run app/main.py   # Start frontend
```

---

## 🆘 Common Issues

### "Module not found" error
```bash
# Make sure you're in the right directory
cd tournament_platform
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

**Last Updated:** June 17, 2026

