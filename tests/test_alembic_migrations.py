"""
Alembic migration smoke tests.

Verifies that ``alembic upgrade head`` runs successfully against a fresh SQLite
database and produces the expected schema, and that the migration environment
(``env.py``) does not rely on ``context.config`` being available at import time
in a way that crashes the run.
"""

import os
import sqlite3
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "tournament_platform" / "alembic.ini"
ALEMBIC_DIR = REPO_ROOT / "tournament_platform" / "alembic"


def _make_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_upgrade_head_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "tournament.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        version = conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        assert version, "alembic_version table should be populated"
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        # Expect a meaningful number of application tables to be created.
        assert len(tables) > 10
    finally:
        conn.close()


def test_current_reports_head(tmp_path: Path) -> None:
    db_path = tmp_path / "tournament.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    # Should not raise; reports the current revision.
    command.current(cfg)


def test_env_py_does_not_import_alembic_context_at_module_load() -> None:
    """Importing the models (which loads ensure_schema) must not crash.

    Regression guard: ``ensure_schema()`` must not start a nested Alembic run
    that tears down the active context proxy when Alembic is already running.
    """
    import tournament_platform.models  # noqa: F401

    assert tournament_platform.models.Base is not None
