# 🆘 Troubleshooting Guide

## Common Issues and Solutions

---

## 🎙️ Voice Scoring Issues

### WebRTC Issues

| Problem | Likely Cause | Diagnostic Field | Fix / Action | Fallback mode |
|---------|-------------|------------------|--------------|---------------|
| WebRTC START button not visible | `streamlit-webrtc` missing | `webrtc_diag_available` | `pip install streamlit-webrtc` | Push-to-talk |
| WebRTC mounted but `playing=False` | Browser permission denied or not clicked | `voice_webrtc_streamer_state.playing` | Click START in component; check browser permissions | Push-to-talk |
| `playing=True` but `audio_frames_received = 0` | Mic muted, no audio, or format mismatch | `last audio frame timestamp` | Unmute tab, check mic, refresh page | Push-to-talk |
| Audio frames > 0 but `chunks_created = 0` | Silence threshold not met; noise gate too high | `last chunk RMS`, `noise threshold` | Lower noise threshold, speak louder | Push-to-talk |
| Chunks > 0 but ASR transcript empty | Model not loaded or confidence too low | `ASR state`, `last ASR error` | Load model via diagnostics; check `VOICE_ASR_MODEL_SIZE` | Manual scoring |
| ASR transcript exists but command rejected | Low confidence, unknown intent, no match selected | `last rejected reason`, `last action taken` | Verify match selection, speak clearly | Manual scoring |
| Command accepted but scoreboard not updated | Event stale or duplicate suppressed | `stale events ignored`, `last accepted command` | Check session ID, ensure WebRTC still playing | Wait for heartbeat or manual refresh |
| Debug command works but continuous does not | WebRTC stopped while debug uses main thread | `webrtc playing` badge | Restart continuous via START button | Debug or push-to-talk |
| Push-to-talk works but continuous does not | Different ASR path; continuous may use queued events | Compare `last push-to-talk transcript` vs `last continuous transcript` | Check chunk queue, VAD settings | Push-to-talk |

### ASR Backend Issues

| Problem | Likely Cause | Diagnostic Field | Fix / Action | Fallback mode |
|---------|-------------|------------------|--------------|---------------|
| Faster Whisper model not loaded | Network error, disk full, wrong `VOICE_ASR_DEVICE` | ASR diagnostics `State` field | Check logs, try `VOICE_ASR_DEVICE=cpu`, `VOICE_ASR_COMPUTE_TYPE=int8` | Manual scoring |
| ASR error shows `not_configured` | `VOICE_ASR_MODEL_SIZE` unset or package missing | ASR provider, imports | Set env var or Streamlit secret; `pip install faster-whisper` | Manual scoring |
| ASR error shows `model_download_failed` | Network error or `HF_TOKEN` missing | ASR diagnostics `reason` | Set `HF_TOKEN` secret on Cloud | Manual scoring |
| ASR error shows `model_init_failed` | Wrong device/compute type | ASR diagnostics `reason` | Try `VOICE_ASR_DEVICE=cpu`, `VOICE_ASR_COMPUTE_TYPE=int8` | Manual scoring |
| Vosk not working | Model path wrong or package missing | ASR diagnostics `imports` | Install `[live]` extra, place model at `VOICE_ASR_VOSK_MODEL_PATH` | Manual scoring |
| SpeechBrain not working | Missing optional deps | ASR diagnostics `imports` | `pip install ".[speech]"` | Manual scoring |

### Command Issues

| Problem | Likely Cause | Fix / Action | Fallback mode |
|---------|-------------|--------------|---------------|
| Commands update wrong player | Color word ambiguous or mispronounced | Use explicit "player one" / "player two" | Manual buttons |
| Duplicate command suppressed | Cooldown active (1.2s) | Wait for cooldown; game boundary auto-resets | Manual buttons |
| No active match selected | Match selector empty | Select tournament + match | Manual scoring |

### Streamlit Cloud Issues

| Problem | Likely Cause | Fix / Action | Fallback mode |
|---------|-------------|--------------|---------------|
| Streamlit Cloud microphone issue | Browser blocked permission, ephemeral container | Re-allow mic, redeploy, check Cloud secrets | Push-to-talk |
| Browser permission blocked | Browser settings or HTTPS requirement | Enable mic in browser settings; ensure HTTPS or localhost | Manual scoring |
| `pyaudio` / PortAudio error on Cloud | `[live]` extra not available on Cloud | Ignore; Cloud uses WebRTC only. Use `[live]` locally if needed. | WebRTC push-to-talk |

---

## 🔴 Installation Issues

### Issue: `ModuleNotFoundError: No module named 'ollama'`

**Solution:**
```bash
# Reinstall all requirements
python -m pip install -r requirements.txt

# Or install specifically
python -m pip install ollama chromadb streamlit-aggrid
```

---

### Issue: `No module named 'alembic'`

**Solution:**
```bash
python -m pip install alembic
```

---

### Issue: `No module named 'streamlit_aggrid'`

**Solution:**
```bash
python -m pip install streamlit-aggrid
```

---

## 🔴 Database Issues

### Issue: `sqlite3.OperationalError: database is locked`

**Cause:** SQLite doesn't handle concurrent connections well

**Solutions:**
1. **Short term**: Stop all running instances and restart
    ```bash
    # Kill all Python processes and restart
    ```

2. **Long term**: Use PostgreSQL for production
    ```python
    # Change in models.py
    DATABASE_URL = "postgresql://user:password@localhost/tournament"
    ```

---

### Issue: `No such table: players` after migration

**Solution:**
```bash
cd tournament_platform
python -m alembic upgrade head
```

Make sure you see output like:
```
INFO [alembic.runtime.migration] Running upgrade 001_initial
```

---

### Issue: Migration fails with "duplicate table"

**Cause:** Database already exists from old create_all() method

**Solution:**
```bash
# Backup and delete old database
mv data/tournament.db data/tournament.db.backup

# Run migration fresh
python -m alembic upgrade head
```

---

## 🔴 API Issues

### Issue: `ConnectionRefusedError: [Errno 111] Connection refused`

**Cause:** API server not running

**Solution:**
```bash
# In one terminal, start the API
cd tournament_platform
python api/server.py

# You should see: "Uvicorn running on http://0.0.0.0:8000"
```

---

### Issue: API returns `422 Unprocessable Entity`

**Cause:** Invalid JSON in request

**Solution:**
- Check your request matches the schema:
  ```json
  {
    "player1": "string",
    "player2": "string",
    "score": "string",
    "winner": "string (optional)",
    "tournament_id": "integer (optional)"
  }
  ```

---

### Issue: Teams webhook not receiving notifications

**Cause:** Invalid webhook URL or Teams service down

**Solution:**
```python
# In api/server.py, verify webhook URL
TEAMS_WEBHOOK_URL = "https://outlook.webhook.office.com/webhookb2/..."

# Test with curl
curl -X POST https://outlook.webhook.office.com/webhookb2/... \
  -H "Content-Type: application/json" \
  -d '{"text": "Test message"}'
```

---

## 🔴 Streamlit Issues

### Issue: `ModuleNotFoundError` in Streamlit pages

**Cause:** sys.path not set correctly

**Solution:**
```python
# Ensure this is at top of pages
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

---

### Issue: Pages not showing in navigation

**Cause:** Files not in correct location or naming

**Solution:**
- Ensure files are in `app/pages/`
- File names: `dashboard.py`, `tournament_setup.py`, `admin.py`
- Check `app/main.py` paths match exactly

---

### Issue: AG-Grid not displaying

**Cause:** Missing streamlit-aggrid package

**Solution:**
```bash
python -m pip install streamlit-aggrid
```

---

### Issue: Plotly radar chart not showing

**Cause:** No player selected or missing data

**Solution:**
- First register players in "Tournament Setup" page
- Report some matches for players
- Then select a player in "Dashboard" page

---

### Issue: Authentication fails

**Cause:** Invalid credentials in `config.yaml`

**Solution:**
```yaml
# app/config.yaml
credentials:
  usernames:
    your_username:
      name: Your Name
      password: "$2b$12$..."  # Hashed password
      email: your@email.com
```

Use this to generate hashed password:
```python
import streamlit_authenticator as stauth
print(stauth.Hasher.hash("your_password"))
```

---

## 🔴 AI/Ollama Issues

### Issue: `ConnectionError: Connection refused` when calling Ollama

**Cause:** Ollama service not running

**Solution:**
```bash
# Start Ollama
ollama serve

# In another terminal, pull the model
ollama pull llama3:latest
```

---

### Issue: AI returns invalid JSON

**Cause:** Model not supporting JSON mode or timeout

**Solution:**
```python
# In services/ai_engine.py, verify:
response = ollama.chat(
    model=self.model,
    messages=[...],
    format="json"  # This enforces JSON
)

# If still fails, increase timeout
response = ollama.chat(
    model=self.model,
    messages=[...],
    format="json",
    stream=False
)
```

---

### Issue: RAG not retrieving relevant rules

**Cause:** Rules not initialized or query mismatch

**Solution:**
```python
# Initialize rules first
python initialize_rag.py

# Or manually in Python
from services.ai_engine import AIEngine
ai = AIEngine()
ai.add_rule_to_rag("Your tournament rule here")

# Test retrieval
context = ai.retrieve_rules_context("your query", top_k=3)
print(context)
```

---

## 🔴 Alembic Migration Issues

### Issue: `No such revision!`

**Cause:** Migration file doesn't exist

**Solution:**
```bash
# Check what migrations exist
python -m alembic history

# Reset to initial migration
python -m alembic downgrade -1
python -m alembic upgrade 001_initial
```

---

### Issue: `Target database is not up to date`

**Cause:** Model changes but no migration created

**Solution:**
```bash
# Create new migration
python -m alembic revision --autogenerate -m "Add new column"

# Review the migration file
cat alembic/versions/002_add_new_column.py

# Apply
python -m alembic upgrade head
```

---

### Issue: `Can't locate revision identified by 'abc123'`

**Cause:** Migration file deleted or corrupted

**Solution:**
```bash
# Backup database
mv data/tournament.db data/tournament.db.backup

# Reset migrations
rm alembic/versions/*.py  # Keep __init__.py
rm data/tournament.db

# Reinitialize
python -m alembic upgrade head
```

---

## 🔴 Port Conflicts

### Issue: `Address already in use` on port 8000 or 8501

**Solution:**
```bash
# Find process using port (Windows)
netstat -ano | findstr :8000
netstat -ano | findstr :8501

# Kill the process
taskkill /PID <PID> /F

# Or use different ports
python api/server.py --port 8001
streamlit run app/main.py --server.port 8502
```

---

## 🔴 File Permission Issues

### Issue: `Permission denied` to write logs

**Cause:** logs directory doesn't exist or no write access

**Solution:**
```bash
# Create logs directory
mkdir logs

# Windows: no special commands needed
```

---

## 🔴 Memory/Performance Issues

### Issue: Application crashes with `MemoryError`

**Cause:** Too much data in memory

**Solutions:**
1. **Reduce sample size in queries**
    ```python
    db.query(Match).limit(1000)  # Don't load everything
    ```

2. **Use pagination in UI**
    ```python
    GridOptionsBuilder.configure_pagination(paginationAutoPageSize=True)
    ```

3. **Switch to PostgreSQL** for better performance

---

### Issue: Slick lag in data tables

**Cause:** Too many rows in AG-Grid

**Solution**:
```python
# Limit rows displayed
df = df.head(500)

# Enable pagination
gb.configure_pagination(paginationPageSize=50)
```

---

## 🔴 Logging Issues

### Issue: `logs/app.log` not being created

**Cause:** logs directory doesn't exist

**Solution:**
```bash
# Create directory
mkdir logs
```

---

### Issue: Logs being truncated or not showing

**Cause:** Log level too high or handler issues

**Solution:**
```python
# Verify in api/server.py
logging.basicConfig(
    level=logging.INFO,  # Or DEBUG for more detail
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
```

---

## 🔴 Integration Issues

### Issue: Streamlit can't connect to API

**Cause:** URL or network issue

**Solution:**
```python
# In Streamlit app, verify:
response = requests.post(
    "http://localhost:8000/api/report",
    json=payload,
    timeout=10
)

# Test basic connectivity
requests.get("http://localhost:8000/health")
```

---

## ✅ Verification Checklist

Run through this checklist to verify everything works:

```bash
# 1. Check Python version
python --version  # Should be 3.11 - 3.13

# 2. Verify dependencies
python -m pip list | grep -E "streamlit|fastapi|faster-whisper|streamlit-webrtc"

# 3. Check database
ls -la data/tournament.db

# 4. Check migrations
python -m alembic current

# 5. Test API
curl http://localhost:8000/health

# 6. Test Streamlit imports
python -c "import streamlit; import streamlit_webrtc; print('Streamlit imports OK')"

# 7. Verify ASR imports
python -c "from faster_whisper import WhisperModel; print('ASR imports OK')"

# 8. Verify log directory
ls -la logs/
```

---

## 📞 Getting Help

If you encounter an issue not listed here:

1. **Check the full logs**
    ```bash
    tail -f logs/app.log
    ```

2. **Enable debug logging**
    ```python
    logging.getLogger().setLevel(logging.DEBUG)
    ```

3. **Test individual components**
    ```bash
    python test_api.py
    python initialize_rag.py
    ```

4. **Check documentation**
    - [FastAPI Docs](https://fastapi.tiangolo.com/)
    - [SQLAlchemy ORM](https://docs.sqlalchemy.org/)
    - [Streamlit Docs](https://docs.streamlit.io/)
    - [ChromaDB Docs](https://docs.trychroma.com/)
    - [faster-whisper Docs](https://github.com/SYSTRAN/faster-whisper)
    - [streamlit-webrtc Docs](https://github.com/whitphx/streamlit-webrtc)

---

**Last Updated:** July 22, 2026
