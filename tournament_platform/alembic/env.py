"""Alembic environment configuration.

This module is executed *inside* Alembic's migration runtime. It must never be
imported directly by application code.

Important Alembic detail: the module-level ``context`` proxy
(``alembic.context``) only exposes ``config`` / ``script`` while an
``EnvironmentContext`` is active. Accessing ``context.config`` outside of that
window raises ``AttributeError: module 'alembic.context' has no attribute
'config'``. Therefore all ``context.*`` access happens inside the migration
run functions (and the bottom-of-module dispatch), which Alembic calls after
the environment is configured.

We also guard against re-entrancy: importing ``tournament_platform.models`` runs
``ensure_schema()`` at import time, which itself invokes ``alembic``. To avoid a
nested Alembic run (and the resulting proxy teardown that breaks the outer run),
``ensure_schema()`` skips when ``ALEMBIC_ENV_ACTIVE`` is set here.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path
from sqlalchemy import engine_from_config, pool

from alembic import context

# Tell downstream ``ensure_schema()`` (triggered by importing models below) that
# Alembic is already managing the schema, so it must not start a nested run.
os.environ["ALEMBIC_ENV_ACTIVE"] = "1"

# Add the repository root to sys.path so ``tournament_platform`` imports work
# regardless of the current working directory (CLI, Streamlit Cloud, cron, etc.).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the canonical SQLAlchemy metadata. This is the single source of truth
# for the schema; the Alembic migrations are derived from it.
from tournament_platform.models import Base, DATABASE_URL  # noqa: E402

target_metadata = Base.metadata


def _get_database_url() -> str:
    """Resolve the database URL.

    Priority:
    1. ``DATABASE_URL`` environment variable (Streamlit Cloud / containers).
    2. ``sqlalchemy.url`` from the Alembic ini (defaults to a local file).
    3. The project's central ``DATABASE_URL`` from ``models.py``.
    4. A repo-local SQLite database under ``data/`` (created if missing).
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    ini_url = context.config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    if DATABASE_URL:
        return DATABASE_URL

    db_path = PROJECT_ROOT / "data" / "tournament.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def _configure_logging() -> None:
    cfg = context.config
    if cfg.config_file_name is not None:
        try:
            fileConfig(cfg.config_file_name, disable_existing_loggers=False)
        except Exception:
            pass


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    _configure_logging()
    url = _get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    _configure_logging()
    configuration = context.config.get_section(context.config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
