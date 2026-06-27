# Configuration Guide

This document explains how configuration is managed in the tournament platform and which values belong in environment variables versus Streamlit secrets.

## Overview

The platform uses a centralized configuration system based on **pydantic-settings**. All configuration values are defined in [`tournament_platform/config/__init__.py`](tournament_platform/config/__init__.py) and can be overridden via environment variables or a `.env` file.

## Configuration Sources

### 1. Environment Variables (`.env` file)

**Use for:**
- Non-secret configuration values
- Service URLs and ports
- Feature flags
- Default numeric/string values
- Local development settings

**Example `.env` file:**
```bash
# Copy from .env.example and fill in your values
cp tournament_platform/.env.example tournament_platform/.env

# Then edit tournament_platform/.env with your actual values
```

**Key environment variables:**
| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama LLM service URL |
| `OLLAMA_MODEL` | `llama3:latest` | Default LLM model name |
| `API_HOST` | `0.0.0.0` | FastAPI server bind address |
| `API_PORT` | `8000` | FastAPI server port |
| `TEAMS_WEBHOOK_URL` | *(empty)* | Microsoft Teams webhook for notifications |
| `AZURE_CLIENT_ID` | *(empty)* | Azure AD application client ID |
| `AZURE_CLIENT_SECRET` | *(empty)* | Azure AD application client secret |
| `AZURE_TENANT_ID` | *(empty)* | Azure AD tenant ID |
| `DEFAULT_PLAYER_RATING` | `1200` | Default ELO rating for new players |
| `APP_VERSION` | `1.0.0` | Application version string |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `CHROMA_DB_PATH` | `./chroma_db` | ChromaDB persistent storage path |
| `WHISPER_MODEL_SIZE` | `base` | Whisper model size (tiny, base, small, medium, large) |
| `WHISPER_DEVICE` | `cpu` | Device for Whisper inference (cpu, cuda) |
| `WHISPER_COMPUTE_TYPE` | `int8` | Compute type for Whisper (int8, float16, float32) |
| `TTS_ENGINE` | `pyttsx3` | Text-to-speech engine (pyttsx3, gtts, edge-tts) |
| `TTS_LANGUAGE` | `en` | TTS language code |
| `TTS_VOICE_GENDER` | `female` | TTS voice gender (male, female) |
| `AUDIO_SAMPLE_RATE` | `16000` | Audio sample rate in Hz |
| `AUDIO_CHANNELS` | `1` | Number of audio channels |

### 2. Streamlit Secrets (`st.secrets`)

**Use for:**
- Production credentials (passwords, API keys)
- Sensitive authentication data
- Values that should never be committed to version control

**How to configure Streamlit secrets:**

Create a `secrets.toml` file in your `.streamlit` directory:

```toml
# .streamlit/secrets.toml

[credentials]
usernames = [
    { username = "admin", email = "admin@corp.com", name = "Admin User", password = "your_secure_password_here" }
]

[cookie]
name = "tt_auth_cookie"
key = "your_random_cookie_key_here"
expiry_days = 30
```

**Important:** The `.streamlit/secrets.toml` file should be added to `.gitignore` and never committed to version control.

## How It Works

### Priority Order

1. **Streamlit secrets** (highest priority) - Used for production credentials
2. **Environment variables** - Used for service configuration
3. **Default values** in `config/__init__.py` - Fallback for local development

### Example: Authentication Configuration

In [`app/main.py`](tournament_platform/app/main.py):
```python
# Load base config from config.yaml
with open(config_path) as file:
    config = yaml.load(file, Loader=yaml.SafeLoader)

# Override with environment-backed settings
config['cookie']['name'] = settings.AUTH_COOKIE_NAME
config['cookie']['key'] = settings.AUTH_COOKIE_KEY
config['cookie']['expiry_days'] = settings.AUTH_COOKIE_EXPIRY_DAYS

# Allow Streamlit secrets to override credentials (production)
if hasattr(st, 'secrets') and 'credentials' in st.secrets:
    config['credentials'] = dict(st.secrets['credentials'])
```

## Security Best Practices

### DO:
- ✅ Use `.env` for non-secret configuration
- ✅ Use Streamlit secrets for passwords, API keys, and tokens
- ✅ Add `.env` and `.streamlit/secrets.toml` to `.gitignore`
- ✅ Use different values for development and production
- ✅ Rotate secrets regularly

### DON'T:
- ❌ Commit real secrets to version control
- ❌ Hardcode credentials in source files
- ❌ Use the same secrets across environments
- ❌ Share `.env` files via email or chat
- ❌ Use weak or default passwords in production

## Migration from Hardcoded Values

### Before (hardcoded):
```python
# In api/server.py
TEAMS_WEBHOOK_URL = "YOUR_TEAMS_WEBHOOK_URL_HERE"
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### After (environment-backed):
```python
# In api/server.py
from config.settings import settings

# Use settings.TEAMS_WEBHOOK_URL
uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
```

## Quick Start

1. **Copy the example environment file:**
   ```bash
   cp tournament_platform/.env.example tournament_platform/.env
   ```

2. **Edit `.env` with your local values:**
   ```bash
   # tournament_platform/.env
   OLLAMA_HOST=http://localhost:11434
   API_PORT=8000
   # ... other values
   ```

3. **For production, configure Streamlit secrets:**
   ```bash
   # Create .streamlit/secrets.toml
   mkdir -p .streamlit
   # Add your production credentials
   ```

4. **Verify configuration loads correctly:**
   ```bash
   python -c "from config.settings import settings; print(settings.dict())"
   ```

## Troubleshooting

### "Settings not loading"
- Ensure `pydantic-settings` is installed: `pip install pydantic-settings`
- Check that `.env` file is in the correct location (`tournament_platform/.env`)
- Verify environment variable names match exactly (case-sensitive)

### "Streamlit secrets not working"
- Ensure `secrets.toml` is in `.streamlit/` directory
- Check TOML syntax is valid
- Verify section names match expected format

### "Configuration values not updating"
- Restart the application after changing `.env` or secrets
- Clear Streamlit cache if using `@st.cache_data`
