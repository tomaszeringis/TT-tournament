# Tournament Platform - Setup & Usage Guide

## 📋 Overview

This document provides step-by-step instructions for setting up and using the refactored Tournament Platform with:
- **Alembic Database Migrations**
- **Pydantic Models for AI responses**
- **RAG (Retrieval-Augmented Generation) with ChromaDB**
- **Streamlit Multi-page Navigation**
- **Async FastAPI with Proper Dependency Injection**

---

## 🚀 Installation & Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Initialize Database with Alembic

If you're starting fresh, initialize the database:

```bash
# Navigate to the project directory
cd tournament_platform

# Create the database and apply initial migration
alembic upgrade head
```

**What this does:**
- Creates SQLite database with `players`, `tournaments`, and `matches` tables
- Applies the `001_initial.py` migration which includes:
  - Player table with name, email, rating
  - Tournament table with name and description
  - Match table with foreign key to Tournament and status enum (pending/active/completed)

### 3. Initialize Alembic (First Time Only)

If you need to reinitialize Alembic:

```bash
alembic init alembic
```

Then configure `alembic.ini` and `alembic/env.py` with the provided files.

---

## 📊 Database Migrations

### Understanding Alembic

Alembic is a lightweight database migration tool. All migrations live in `alembic/versions/`.

### Creating a New Migration

After modifying `models.py`, create a new migration:

```bash
alembic revision --autogenerate -m "Description of your change"
```

This creates a new file in `alembic/versions/` with up/down functions.

### Applying Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Downgrade one migration
alembic downgrade -1

# View current migration status
alembic current
```

### Current Models

#### Player Model
```python
- id (Integer, Primary Key)
- name (String, Unique)
- email (String)
- rating (Integer, default=1200)
```

#### Tournament Model (NEW)
```python
- id (Integer, Primary Key)
- name (String, Unique)
- description (String, nullable)
- created_at (DateTime)
- relationships: matches (Match[])
```

#### Match Model (UPDATED)
```python
- id (Integer, Primary Key)
- player1 (String)
- player2 (String)
- winner (String, nullable)
- score (String, nullable)
- status (Enum: pending/active/completed)  # NEW!
- tournament_id (Integer, ForeignKey → Tournament)  # NEW!
- scheduled_time (DateTime)
- relationships: tournament (Tournament)
```

---

## 🤖 AI Engine Refactoring

### MatchReport Pydantic Model

The AI engine now returns structured data:

```python
from services.ai_engine import MatchReport

report = MatchReport(
    summary="Exciting match summary",
    key_play="Amazing rallies between both players",
    predicted_winner="Player Name"
)
```

### JSON Mode Enforcement

The AIEngine uses Ollama's JSON mode to ensure structured responses:

```python
from services.ai_engine import AIEngine

ai = AIEngine(model="llama3.3:8b")

match_data = {
    "player1": "Alice",
    "player2": "Bob",
    "score": "3-1"
}

report = ai.generate_report(match_data)
print(report.summary)          # Safe to access
print(report.key_play)
print(report.predicted_winner)
```

---

## 🧠 RAG System (Retrieval-Augmented Generation)

### What is RAG?

RAG allows the AI to retrieve relevant tournament rules as context before generating responses. This ensures answers are grounded in your tournament rules.

### Setup RAG

```python
from services.ai_engine import AIEngine

ai = AIEngine()

# Add tournament rules to the knowledge base
rules = [
    "Players must arrive 5 minutes before their match.",
    "Best of 5 games wins the match.",
    "Each player gets one 60-second timeout per game.",
    "Umpire decisions are final.",
]

ai.batch_initialize_rules(rules)
```

### How It Works

1. User query (match data) is sent to ai_engine
2. ChromaDB retrieves top 3 relevant rules
3. Rules are added to the Ollama prompt as context
4. AI generates response based on both match data and rules
5. Response is returned as MatchReport Pydantic model

### Retrieving Rules Manually

```python
context = ai.retrieve_rules_context(
    query="timeout policy",
    top_k=3
)
print(context)  # Relevant rules printed
```

---

## 🎨 Streamlit Multi-Page Structure

### Architecture

The app now uses `st.navigation` (Streamlit 1.35+) for clean multi-page support:

```
app/
├── main.py           # Entry point with auth & navigation
└── pages/
    ├── dashboard.py          # 📊 View standings & player stats
    ├── tournament_setup.py    # ⚙️ Create tournaments & report matches
    └── admin.py              # 👨‍💼 System administration
```

### Running the App

```bash
cd app
streamlit run main.py
```

### Pages Overview

#### 1. Dashboard (📊)
- **Players Grid**: Sortable, selectable player table with AG-Grid
- **Recent Matches**: Match history
- **Radar Chart**: Visual player performance metrics (win rate, consistency, aggression)

#### 2. Tournament Setup (⚙️)
- **Create Tournaments**: Add new tournament
- **Report Matches**: Submit match results
- **Player Registration**: Register new players

#### 3. Admin (👨‍💼)
- **Database Overview**: System statistics
- **Match Management**: Filter and view all matches
- **System Health**: Health checks and system info

### AG-Grid Features

AG-Grid tables include:
- ✅ **Sorting**: Click column headers
- ✅ **Pagination**: Navigate large datasets
- ✅ **Row Selection**: Select individual rows
- ✅ **Filtering**: Sidebar filters
- ✅ **Resizing**: Adjust column widths

### Plotly Radar Chart

When you select a player in the Dashboard:

```python
# Shows metrics on a radar chart:
- Win Rate (%)
- Consistency (%)
- Aggression (%)
```

---

## ⚡ FastAPI Async Refactoring

### What's New

1. **Async Endpoint**: `report_match` is fully async
2. **Dependency Injection**: Uses `Depends(get_db)` for database session
3. **Global Exception Handler**: Logs all errors to `logs/app.log`
4. **Health Check**: `/health` endpoint for monitoring
5. **Structured Logging**: Detailed request/response logging

### Running the API

```bash
python api/server.py
```

Server starts at `http://localhost:8000`

### API Endpoints

#### POST /api/report
Reports a match result.

**Request:**
```json
{
  "player1": "Alice",
  "player2": "Bob",
  "score": "3-1",
  "winner": "Alice",
  "tournament_id": 1
}
```

**Response:**
```json
{
  "status": "success",
  "match_id": 42,
  "message": "Match result recorded and notification sent"
}
```

#### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-06-17T12:34:56"
}
```

### Dependency Injection Pattern

```python
from fastapi import Depends
from models import SessionLocal, Session

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/api/endpoint")
async def endpoint(db: Session = Depends(get_db)):
    # db is automatically injected
    pass
```

### Error Logging

All errors are logged to `logs/app.log`:

```
2026-06-17 12:34:56 - api.server - ERROR - Unhandled exception: ...
```

---

## 📁 Project Structure

```
tournament_platform/
├── main.py                        # Entry point
├── models.py                      # SQLAlchemy ORM models
├── requirements.txt               # Python dependencies
├── alembic.ini                    # Alembic configuration
├── alembic/
│   ├── env.py                     # Migration environment
│   ├── script.py.mako             # Migration template
│   └── versions/
│       ├── __init__.py
│       └── 001_initial.py         # Initial migration
├── api/
│   └── server.py                  # FastAPI async server
├── app/
│   ├── main.py                    # Streamlit entry point with auth
│   ├── config.yaml                # Auth configuration
│   └── pages/
│       ├── __init__.py
│       ├── dashboard.py           # Standing & stats view
│       ├── tournament_setup.py     # Tournament & match management
│       └── admin.py               # Admin panel
├── services/
│   ├── __init__.py
│   └── ai_engine.py               # AI + RAG engine
├── data/
│   ├── tournament.db              # SQLite database
│   └── chroma_db/                 # ChromaDB storage (RAG)
└── logs/
    └── app.log                    # Application logs
```

---

## 🔧 Configuration

### Environment Variables

Create a `.env` file (optional):

```env
DATABASE_URL=sqlite:///./data/tournament.db
OLLAMA_MODEL=llama3.3:8b
TEAMS_WEBHOOK_URL=https://your-webhook-url
LOG_LEVEL=INFO
```

### Ollama Setup

Ensure Ollama is running locally:

```bash
ollama serve
```

Then pull the model:

```bash
ollama pull llama3.3:8b
```

---

## 🧪 Usage Examples

### Create a Match with Tournament

```python
from models import SessionLocal, Match, Tournament

db = SessionLocal()

# Create tournament
tournament = Tournament(name="Q2 Tournament", description="Second quarter")
db.add(tournament)
db.commit()

# Create match
match = Match(
    player1="Alice",
    player2="Bob",
    score="3-1",
    winner="Alice",
    status="completed",
    tournament_id=tournament.id
)
db.add(match)
db.commit()
```

### Generate AI Report with RAG

```python
from services.ai_engine import AIEngine

ai = AIEngine()

# Initialize rules
ai.batch_initialize_rules([
    "Best of 5 games",
    "Each player gets 1 timeout per game",
])

# Generate report
match_data = {"player1": "Alice", "player2": "Bob", "score": "3-1"}
report = ai.generate_report(match_data)

print(f"Summary: {report.summary}")
print(f"Winner: {report.predicted_winner}")
```

### Query API

```bash
# Report a match
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{
    "player1": "Alice",
    "player2": "Bob",
    "score": "3-1",
    "winner": "Alice"
  }'

# Health check
curl http://localhost:8000/health
```

---

## 📝 Next Steps

1. **Configure Auth**: Update `app/config.yaml` with your credentials
2. **Add Tournament Rules**: Initialize RAG with your rules
3. **Run Migrations**: `alembic upgrade head`
4. **Start API**: `python api/server.py`
5. **Start Frontend**: `streamlit run app/main.py`
6. **Create Tournaments**: Use the Tournament Setup page

---

## 🆘 Troubleshooting

### Ollama Connection Error
- Ensure Ollama is running: `ollama serve`
- Check model is installed: `ollama list`

### Database Lock Error
- SQLite limitation with concurrent access
- Use PostgreSQL for production

### ChromaDB Not Found
- Database created automatically on first access
- Check `data/chroma_db/` directory permissions

### Streamlit Page Not Found
- Ensure pages are in `app/pages/` directory
- Files must end with `.py`

---

## 📚 Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Ollama Documentation](https://github.com/ollama/ollama)

---

**Last Updated**: June 17, 2026
**Version**: 2.0

