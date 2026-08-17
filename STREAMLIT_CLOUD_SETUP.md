# Streamlit Cloud Setup Guide

This guide explains how to deploy the Tournament Platform to Streamlit Cloud with persistent data storage.

## Prerequisites

- A Streamlit Cloud account (https://streamlit.io/cloud)
- A PostgreSQL database (Neon, Supabase, Railway, or any compatible provider)

## 1. Database Setup

### Option A: Neon Postgres (Recommended)

1. Sign up at https://neon.tech
2. Create a new project
3. Copy the connection string (it looks like `postgresql://user:pass@host/dbname`)

### Option B: Supabase

1. Sign up at https://supabase.com
2. Create a new project
3. Go to Settings > Database > Connection string
4. Copy the URI mode connection string

### Option C: Railway

1. Sign up at https://railway.app
2. Create a new PostgreSQL plugin
3. Copy the connection string from the plugin settings

## 2. Deploy to Streamlit Cloud

1. Push your code to GitHub
2. Go to https://streamlit.io/cloud and click "New app"
3. Select your repository and branch
4. **Set the Main module to `streamlit_app.py`** (at the repository root).
   This is the canonical Streamlit entrypoint — it imports and calls
   `main()` from `tournament_platform/app/main.py`.
5. **Set the Python version to 3.13** (3.12 also works; the app requires
   `>=3.11,<3.14`). Select this in "Advanced settings" before the first deploy.
   If you previously deployed with a different Python version, delete the app
   and redeploy — Streamlit Cloud keeps the Python version from the original
   deploy.

## 3. Configure Secrets

In Streamlit Cloud, go to your app settings > Secrets and add:

```toml
# Database (required for persistence)
DATABASE_URL = "postgresql://user:pass@host:5432/dbname"

# Auth credentials
[credentials]
usernames = [
    { username = "admin", password = "argon2idhash...", role = "admin" },
    { username = "operator", password = "argon2idhash...", role = "operator" },
]

[cookie]
name = "tt_auth_cookie"
key = "change-me-to-random-32b-key-production"
expiry_days = 30

# Optional: External FastAPI backend (local Ollama bridge via ngrok)
# The Streamlit app does NOT start a FastAPI server in-process. See
# the "Optional local API + ngrok" section below and README.md.
API_BASE_URL = "https://your-ngrok-url.ngrok-free.app"
API_REQUIRED = "false"
API_TOKEN = "your-long-random-token"

# Optional: AI features (when API_BASE_URL is set)
OLLAMA_MODEL = "llama3.1:8b"

# Optional: higher Hugging Face download rate limits. NOT required — the app
# still works (and degrades gracefully) without it.
HF_TOKEN = "hf_..."

# Voice scoring ASR (Streamlit Cloud defaults shown)
# Faster-whisper runs locally in the app. Use tiny.en on Cloud for fast, safe
# startup; switch to base.en/small.en once the pipeline is confirmed working.
VOICE_ASR_MODEL_SIZE = "tiny.en"
VOICE_ASR_DEVICE = "cpu"
VOICE_ASR_COMPUTE_TYPE = "int8"
```

### Voice Scoring on Streamlit Cloud

- **faster-whisper** and **streamlit-webrtc** are installed by default from `pyproject.toml` dependencies.
- **pyaudio** is NOT available on Streamlit Cloud (PortAudio is unavailable). Push-to-talk uses browser audio via `st.audio_input` (WebRTC) instead.
- **Model size recommendation**: Use `VOICE_ASR_MODEL_SIZE=tiny.en` on Cloud for fast startup and low memory. Switch to `base.en` once the pipeline is confirmed working.
- **Browser microphone permissions** must be granted by the user. The app shows a clear prompt if the browser denies access.
- **`HF_TOKEN` secret** removes Hugging Face rate-limit warnings and download failures for `faster-whisper` model downloads.
- **Ephemeral filesystem**: Audio files and model caches are stored in ephemeral storage and do not persist between restarts. `faster-whisper` re-downloads the model cache on each restart if not on persistent storage.
- **Continuous listening**: WebRTC works on Streamlit Cloud when the browser grants microphone/camera permissions. The built-in START/STOP button functions normally.

### Voice Scoring Environment Variables

In Streamlit Cloud **Secrets** (Settings → Secrets):

```toml
# Voice scoring ASR
VOICE_ASR_MODEL_SIZE = "tiny.en"
VOICE_ASR_DEVICE = "cpu"
VOICE_ASR_COMPUTE_TYPE = "int8"

# Optional: Hugging Face token for faster-whisper model downloads
HF_TOKEN = "hf_..."

# Optional: ASR backend selection
VOICE_ASR_BACKEND = "faster_whisper"
VOICE_ASR_FALLBACK_BACKEND = "faster_whisper"
```

> **Important:** Streamlit Cloud secrets do **not** automatically become environment variables. The `get_voice_setting()` helper reads from `os.environ` first, then from `st.secrets`, so voice configuration works without explicit env var setup.

### Important: Set DATABASE_URL Before First Deploy

**The `DATABASE_URL` secret must be configured before the first deploy.** If the app starts without `DATABASE_URL`, it will create a local SQLite file on the ephemeral container filesystem. Data in that SQLite file will be lost on the next restart.

If you already deployed without `DATABASE_URL`:
1. Delete the app from Streamlit Cloud
2. Re-create it with `DATABASE_URL` already configured in secrets

## 4. Run Migrations

After the first deploy with `DATABASE_URL` configured:

1. Go to your app's terminal in Streamlit Cloud (or use the "Restart" button)
2. The app runs `alembic upgrade head` automatically on startup via `ensure_schema()` in `models.py`
3. All tables will be created in the cloud database

## 5. Verify Persistence

1. Create a tournament in the app
2. Restart the app (Streamlit Cloud > Settings > Restart)
3. Verify the tournament still appears in the Database Overview tab

## Local Development with Cloud DB

To test with a cloud database locally:

```bash
# Set DATABASE_URL in your environment
export DATABASE_URL="postgresql://user:pass@localhost:5432/tournament_platform"

# Or use a .env file
echo 'DATABASE_URL="postgresql://user:pass@localhost:5432/tournament_platform"' >> .env

# Run Streamlit (use the root entrypoint — no PYTHONPATH needed)
streamlit run streamlit_app.py
```

### Optional: Local API + ngrok for AI features

Streamlit Cloud **never** talks to Ollama directly. To use AI features (rules
assistant, commentary, etc.) on Cloud, run the FastAPI backend on your laptop and
expose it via ngrok. See the "☁️ Streamlit Cloud deployment" → "🔌 Optional local
API + ngrok" section in [README.md](README.md) for full instructions.

## Troubleshooting

### Data not persisting across restarts

- Verify `DATABASE_URL` is set in Streamlit Cloud secrets (not just `.env` locally)
- Check the System Health tab in the Admin Console - it shows the current database type
- If running on Streamlit Cloud but seeing "SQLite (local)" in System Health, `DATABASE_URL` is not configured

### Connection errors

- Verify the PostgreSQL connection string is correct
- Check that the database allows connections from Streamlit Cloud IPs (some providers restrict this)
- Neon/Supabase typically allow all connections by default

### Migration failures

- The app uses `alembic upgrade head` on startup
- If migrations fail, check the app logs in Streamlit Cloud
- Alembic migrations are additive and safe to re-run

## Architecture

The database resolution priority is:

1. `DATABASE_URL` environment variable (Streamlit Cloud secrets)
2. Streamlit secrets (`st.secrets["DATABASE_URL"]`)
3. `settings.DATABASE_URL` from pydantic-settings (falls back to local SQLite)
4. Local SQLite at `data/tournament.db`

All pages use `SessionLocal` from `models.py`, which now points to the resolved database automatically. No page-level changes are needed.
