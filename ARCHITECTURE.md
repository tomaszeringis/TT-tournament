# 🏗️ Tournament Platform - Technical Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tournament Platform v2.0                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┼─────────────┐
                │             │             │
         ┌──────▼─────┐   ┌──▼────────┐  ┌▼──────────────┐
         │  Frontend   │   │   API     │  │  AI Engine   │
         │ (Streamlit) │   │ (FastAPI) │  │ (Ollama)     │
         └─────┬──────┘   └──┬────────┘  └┬──────────────┘
               │            │             │
         HTTP │            │ Async I/O   │
            ┌─┴──────────────┴─────────────┴─┐
            │   Database Layer               │
            │   • SQLAlchemy ORM             │
            │   • Alembic Migrations         │
            │   • SQLite / PostgreSQL        │
            └─────────────────────────────────┘
```

---

## 1. Frontend Layer (Streamlit)

### Architecture: Multi-Page Modular Design

```
app/
├── main.py                  ← Entry point with auth & navigation
├── pages/
│   ├── dashboard.py         ← Analytics & visualization
│   ├── tournament_setup.py   ← Configuration & reporting
│   └── admin.py             ← System administration
└── config.yaml              ← Authentication config
```

### Key Technologies:
- **Streamlit 1.35+**: Web framework
- **st.navigation**: Multi-page routing
- **AG-Grid**: Advanced data tables
- **Plotly**: Interactive charts
- **streamlit-authenticator**: Authentication

### Data Flow:
```
User Input → Streamlit UI → HTTP Request → FastAPI → Database
```

---

## 2. API Layer (FastAPI)

### Architecture: RESTful Async API

```python
FastAPI Server
├── Endpoints
│   ├── POST /api/report     ← Async match reporting
│   └── GET /health          ← Health check
├── Middleware
│   ├── Exception Handler    ← Global error handling
│   ├── Logging              ← Request/response logging
│   └── CORS                 ← Cross-origin support
└── Dependencies
    └── Database Session     ← Dependency injection
```

### Key Features:
- **Async/Await**: Non-blocking I/O
- **Dependency Injection**: Clean database session management
- **Exception Handling**: Global error handler with logging
- **Async HTTP Client**: httpx for external API calls
- **Structured Logging**: File and console logging

### Request Flow:
```
Request → Validation → DB Dependency → Processing → Response → Logging
```

---

## 3. Database Layer

### Architecture: SQLAlchemy ORM + Alembic Migrations

```
Data Models
├── Player
│   ├── id (PK)
│   ├── name
│   ├── email
│   └── rating
├── Tournament
│   ├── id (PK)
│   ├── name
│   ├── description
│   ├── created_at
│   └── matches (1→N)
└── Match
    ├── id (PK)
    ├── player1
    ├── player2
    ├── winner
    ├── score
    ├── status (Enum)
    ├── tournament_id (FK)
    └── scheduled_time
```

### Migration System:
```
Model Change
    ↓
alembic revision --autogenerate
    ↓
Review migration file
    ↓
alembic upgrade head
    ↓
Database Updated
```

### Current Migration:
- **001_initial.py**: Creates Player, Tournament, Match tables

---

## 4. AI Engine Layer

### Architecture: RAG + Structured Output

```
Match Data
    ↓
┌─────────────────────┐
│  RAG System         │
│ ┌──────────────┐    │
│ │ ChromaDB     │    │
│ │ (Knowledge   │    │
│ │  Base)       │    │
│ └──────────────┘    │
└─────────────────────┘
    ↓ (Top 3 Rules)
┌─────────────────────┐
│ Ollama LLM          │
│ (JSON Mode)         │
└─────────────────────┘
    ↓
Pydantic MatchReport
├── summary
├── key_play
└── predicted_winner
```

### Components:

**1. MatchReport (Pydantic Model)**
```python
class MatchReport(BaseModel):
    summary: str
    key_play: str
    predicted_winner: str
```

**2. RAG System (ChromaDB)**
- Stores tournament rules
- Retrieves relevant context
- Embeds rules and queries

**3. Ollama Integration**
- JSON mode enforcement
- Local LLM processing
- Structured responses

### Data Flow:
```
Match Data + Query → Retrieve Rules → Prompt Engineering →
Ollama JSON Mode → Parse Response → Return MatchReport
```

---

## 5. Complete Request Flow

### Scenario: Report a Match Result

```
1. FRONTEND (Streamlit)
   └─ User fills form and submits
   
2. HTTP REQUEST
   └─ POST /api/report
   └─ JSON: {player1, player2, score, winner, tournament_id}

3. API (FastAPI)
   ├─ Validate request
   ├─ Get DB session (Dependency Injection)
   └─ Create Match record

4. DATABASE (SQLAlchemy)
   ├─ Insert into matches table
   ├─ Set status to "completed"
   └─ Commit transaction

5. NOTIFICATION
   ├─ Format Teams message
   ├─ Async HTTP call to webhook
   └─ Fire and forget

6. RESPONSE
   └─ Return success JSON to Streamlit

7. LOGGING
   └─ Write request/response to logs/app.log

8. FRONTEND
   └─ Display success message
```

---

## 6. Data Relationships

### Entity-Relationship Diagram

```
┌──────────────┐
│   Player     │
├──────────────┤
│ id (PK)      │
│ name         │
│ email        │
│ rating       │
└──────────────┘
       ▲
       │
    (1:N)
       │
       └─── belongs to ───┐
                           │
                      ┌────▼──────────┐
                      │    Match       │
                      ├────────────────┤
                      │ id (PK)        │
                      │ player1        │
                      │ player2        │
                      │ winner         │
                      │ score          │
                      │ status (Enum)  │
                      │ tournament_id  │
                      │ (FK) ──┐       │
                      │        │       │
                      └────────┼───────┘
                               │
                          (1:N)│
                               │
                      ┌────────▼────────┐
                      │  Tournament     │
                      ├─────────────────┤
                      │ id (PK)         │
                      │ name            │
                      │ description     │
                      │ created_at      │
                      └─────────────────┘
```

---

## 7. Deployment Architecture

### Development Setup
```
localhost:8501 ← Streamlit
localhost:8000 ← FastAPI

Both connect to local SQLite
```

### Production Setup
```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    └────────┬────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
          ┌─────▼──┐   ┌─────▼────┐  ┌──▼──────┐
          │Streamlit│   │ FastAPI  │  │ FastAPI │
          │Instance │   │ Instance │  │Instance │
          └─────┬──┘   └─────┬────┘  └──┬──────┘
                │            │          │
                └────────────┬──────────┘
                             │
                      ┌──────▼──────┐
                      │ PostgreSQL  │
                      │ (Production)│
                      └─────────────┘
```

---

## 8. Error Handling Flow

```
Exception Occurs
    ↓
Global Exception Handler (@app.exception_handler)
    ↓
├─ Log Error (logs/app.log)
├─ Format Error Response
└─ Return JSON with Details
    ↓
Frontend Displays Error Message
```

### Exception Types Handled:
- **HTTPException**: 400/500 errors
- **JSONDecodeError**: Invalid JSON
- **DatabaseError**: SQL issues
- **ValueError**: Business logic errors
- **Generic Exception**: Catch-all

---

## 9. Logging Architecture

### Three-Level Logging:

```
1. FILE (/logs/app.log)
   └─ Production logs for analysis

2. CONSOLE
   └─ Real-time development feedback

3. STRUCTURED LOGGING
   └─ Format: timestamp | level | module | message
```

### Log Levels:
- **DEBUG**: Detailed development info
- **INFO**: General information flows
- **WARNING**: Warning messages
- **ERROR**: Error conditions
- **CRITICAL**: Critical failures

---

## 10. Dependency Graph

```
Streamlit Frontend
    ↓
requests → FastAPI Server
            ↓
        SQLAlchemy ORM
           ↓
        SQLite / PostgreSQL
        
AI Engine
    ↓
Ollama (Local LLM)
Chromadb (Knowledge Base)
    ↓
Pydantic Models (Structured Output)
```

---

## 11. Technology Stack Summary

| Layer | Component | Technology | Version |
|-------|-----------|-----------|---------|
| Frontend | UI Framework | Streamlit | 1.35.0 |
| | Tables | streamlit-aggrid | 0.3.5 |
| | Charts | Plotly | 5.18.0 |
| | Auth | streamlit-authenticator | 0.3.2 |
| API | Server | FastAPI | 0.110.0 |
| | ASGI | Uvicorn | 0.29.0 |
| | HTTP Client | httpx | Latest |
| Database | ORM | SQLAlchemy | 2.0.30 |
| | Migrations | Alembic | 1.13.0 |
| | Database | SQLite / PostgreSQL | - |
| AI | LLM | Ollama | Local |
| | Knowledge Base | ChromaDB | 0.4.24 |
| | Validation | Pydantic | 2.7.0 |

---

## 12. Performance Considerations

### Database Optimization:
- Indexes on frequently queried columns
- Connection pooling
- Pagination for large datasets
- Query optimization

### Frontend Optimization:
- Lazy loading of data
- Caching strategies
- Pagination in AG-Grid
- Minimal re-renders

### API Optimization:
- Async processing
- Write operations go to database
- Read operations use caching
- Connection pooling

### AI Optimization:
- Local Ollama (no network latency)
- ChromaDB for cached embeddings
- Batch rule loading
- JSON mode prevents parsing overhead

---

## 13. Security Considerations

### Frontend:
- ✅ Authentication with config.yaml
- ✅ Session management
- ✅ Input validation

### API:
- ✅ Request validation (Pydantic)
- ✅ Error messages don't leak internals
- ✅ Logging for audit trail
- ✅ CORS configuration

### Database:
- ✅ SQL injection prevention (ORM)
- ✅ Connection pooling
- ✅ Transaction safety

### Production:
- ⚠️ Use HTTPS/SSL
- ⚠️ Add authentication tokens
- ⚠️ Use environment variables
- ⚠️ Rate limiting

---

## 14. Scalability Path

### Phase 1: Current (SQLite)
- Single server
- Development/testing
- ~100 concurrent users

### Phase 2: PostgreSQL + Multiple API Instances
- Replace SQLite with PostgreSQL
- Multiple FastAPI instances
- Load balancer
- ~1000 concurrent users

### Phase 3: Distributed System
- Separate Streamlit, API, Database servers
- Redis for caching
- Kubernetes orchestration
- ~10,000 concurrent users

---

## 15. Key Design Patterns

### 1. Dependency Injection
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/api/report")
async def endpoint(db: Session = Depends(get_db)):
    pass
```

### 2. Async/Await
```python
@app.post("/api/report")
async def report_match(request: Request):
    data = await request.json()
    async with httpx.AsyncClient() as client:
        await client.post(url, json=data)
```

### 3. Pydantic Validation
```python
class MatchReport(BaseModel):
    summary: str
    key_play: str
    predicted_winner: str
```

### 4. Repository Pattern (ORM)
```python
db.query(Match).filter(Match.status == "completed")
db.add(new_match)
db.commit()
```

---

## 📚 References

- [FastAPI Architecture](https://fastapi.tiangolo.com/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/)
- [Alembic Migrations](https://alembic.sqlalchemy.org/)
- [Streamlit Architecture](https://docs.streamlit.io/)
- [RAG Pattern](https://docs.trychroma.com/)

---

**Last Updated:** June 17, 2026  
**Architecture Version:** 2.0

