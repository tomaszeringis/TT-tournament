"""
Centralized database configuration.

Resolves the database URL from:
    1. DATABASE_URL environment variable
    2. Streamlit secrets (st.secrets["DATABASE_URL"])
    3. pydantic-settings (settings.DATABASE_URL)
    4. Fallback local SQLite

Creates and caches the SQLAlchemy engine + SessionLocal.
Never initialize destructive seed/demo data here.
"""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.config import settings


def _mask_database_url(url: str) -> str:
    """Return a UI-safe version of the database URL with credentials masked."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(f":{parsed.password}@", ":****@")
        return url
    except Exception:
        return url


def _get_database_url() -> str:
    """Resolve DATABASE_URL with priority: env > Streamlit secret > settings > local fallback."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    try:
        import streamlit as st
        if hasattr(st, "secrets") and st.secrets:
            secret_url = st.secrets.get("DATABASE_URL")
            if secret_url and isinstance(secret_url, str):
                return secret_url
    except Exception:
        pass

    settings_url = settings.DATABASE_URL
    if settings_url and settings_url != "sqlite:///data/tournament.db":
        return settings_url

    base_dir = Path(__file__).resolve().parent.parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "tournament.db"
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL: str = _get_database_url()

if DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)


def _get_connect_args(url: str) -> dict:
    """Return SQLAlchemy connect_args appropriate for the database URL."""
    if url.startswith("sqlite"):
        return {"check_same_thread": False, "timeout": 30}
    return {}


connect_args = _get_connect_args(DATABASE_URL)
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_engine():
    """Return the configured SQLAlchemy engine."""
    return engine


def get_session_local():
    """Return the configured sessionmaker."""
    return SessionLocal


def is_cloud_database() -> bool:
    """Return True if using an external (non-SQLite) database."""
    return not DATABASE_URL.startswith("sqlite")


def get_database_type() -> str:
    """Return a human-readable database type for UI display."""
    if DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres"):
        return "PostgreSQL (cloud)"
    if DATABASE_URL.startswith("libsql"):
        return "Turso/libSQL (cloud)"
    if DATABASE_URL.startswith("sqlite"):
        return "SQLite (local)"
    return "Unknown"


def get_database_url_masked() -> str:
    """Return a UI-safe database URL with credentials masked."""
    return _mask_database_url(DATABASE_URL)


def get_database_host() -> str:
    """Return only the host portion of the database URL for diagnostics."""
    try:
        parsed = urlparse(DATABASE_URL)
        if parsed.hostname:
            return parsed.hostname
        if DATABASE_URL.startswith("sqlite"):
            return "local filesystem"
        return "unknown"
    except Exception:
        return "unknown"
