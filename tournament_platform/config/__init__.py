"""
Centralized configuration for the Tournament Platform.

Uses pydantic-settings to load values from environment variables,
with sensible local defaults for non-secret values.
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    APP_NAME: str = "Tournament Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    DEBUG_UI_ENABLED: bool = False

    # -------------------------------------------------------------------------
    # FastAPI Server
    # -------------------------------------------------------------------------
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_BASE_URL: str = "http://localhost:8000"

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    DATABASE_URL: str = "sqlite:///data/tournament.db"

    # -------------------------------------------------------------------------
    # Ollama LLM
    # -------------------------------------------------------------------------
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3:latest"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_EMBEDDING_URL: str = "http://localhost:11434/api/embeddings"

    # -------------------------------------------------------------------------
    # ChromaDB / RAG
    # -------------------------------------------------------------------------
    CHROMA_DB_PATH: str = "data/chroma_db"

    # -------------------------------------------------------------------------
    # Whisper (Speech-to-Text)
    # -------------------------------------------------------------------------
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # -------------------------------------------------------------------------
    # TTS (Text-to-Speech)
    # -------------------------------------------------------------------------
    TTS_SAMPLE_RATE: int = 24000
    TTS_CHUNK_SIZE: int = 1024

    # -------------------------------------------------------------------------
    # Audio Capture
    # -------------------------------------------------------------------------
    AUDIO_FORMAT: int = 8  # pyaudio.paInt16
    AUDIO_CHANNELS: int = 1
    AUDIO_RATE: int = 16000
    AUDIO_CHUNK: int = 1024
    AUDIO_SILENCE_THRESHOLD: int = 500
    AUDIO_MIN_SILENCE_DURATION: float = 1.0

    # -------------------------------------------------------------------------
    # Microsoft Teams Webhook (notifications)
    # -------------------------------------------------------------------------
    TEAMS_WEBHOOK_URL: str = ""

    # -------------------------------------------------------------------------
    # Azure AD / Microsoft Graph (Calendar integration)
    # -------------------------------------------------------------------------
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    AZURE_TENANT_ID: str = "common"

    # -------------------------------------------------------------------------
    # Streamlit Authenticator
    # -------------------------------------------------------------------------
    AUTH_COOKIE_NAME: str = "tt_auth_cookie"
    AUTH_COOKIE_KEY: str = "random_signature_key"
    AUTH_COOKIE_EXPIRY_DAYS: int = 30

    # -------------------------------------------------------------------------
    # Tournament defaults
    # -------------------------------------------------------------------------
    DEFAULT_PLAYER_RATING: int = 1200

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    LOG_DIR: str = "logs"
    LOG_LEVEL: str = "INFO"

    # -------------------------------------------------------------------------
    # Semantic Kernel (AI Assistant)
    # -------------------------------------------------------------------------
    SEMANTIC_KERNEL_OLLAMA_HOST: str = "http://localhost:11434"
    SEMANTIC_KERNEL_MODEL_ID: str = "llama3.1:latest"

    @model_validator(mode='after')
    def resolve_absolute_paths(self):
        """Resolve relative paths to absolute paths at runtime."""
        if not os.path.isabs(self.CHROMA_DB_PATH):
            self.CHROMA_DB_PATH = os.path.abspath(self.CHROMA_DB_PATH)
        return self


# Singleton instance
settings = Settings()
