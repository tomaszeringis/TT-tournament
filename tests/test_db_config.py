"""
Smoke tests for database configuration resolution.

Verifies that DATABASE_URL is resolved correctly and that models.py
maintains backward compatibility after the db_config refactor.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


def test_db_config_returns_local_sqlite_by_default():
    """Without any overrides, db_config should resolve to local SQLite."""
    with patch.dict(os.environ, {}, clear=False):
        if "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        
        import importlib
        from tournament_platform.core import db_config
        importlib.reload(db_config)
        
        assert db_config.DATABASE_URL.startswith("sqlite")
        assert db_config.get_database_type() == "SQLite (local)"
        assert db_config.is_cloud_database() is False


def test_get_database_type_classification():
    """get_database_type should classify the current DATABASE_URL correctly."""
    from tournament_platform.core.db_config import get_database_type, DATABASE_URL
    
    db_type = get_database_type()
    if DATABASE_URL.startswith("sqlite"):
        assert db_type == "SQLite (local)"
    elif DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres"):
        assert db_type == "PostgreSQL (cloud)"
    elif DATABASE_URL.startswith("libsql"):
        assert db_type == "Turso/libSQL (cloud)"


def test_is_cloud_database_classification():
    """is_cloud_database should return False for local SQLite."""
    from tournament_platform.core.db_config import is_cloud_database, DATABASE_URL
    
    assert is_cloud_database() is DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres") or DATABASE_URL.startswith("libsql")


def test_models_backward_compatibility():
    """models.py should still export DATABASE_PATH, engine, SessionLocal."""
    from tournament_platform.models import DATABASE_PATH, engine, SessionLocal, Tournament
    
    assert DATABASE_PATH is not None
    assert engine is not None
    assert SessionLocal is not None
    
    columns = [c.name for c in Tournament.__table__.columns]
    assert "is_archived" in columns


def test_list_tournaments_filters_archived_by_default():
    """list_tournaments should exclude archived tournaments by default."""
    from tournament_platform.services.tournament_read_models import list_tournaments
    from tournament_platform.models import SessionLocal, Tournament, MatchStatus, Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    
    try:
        t1 = Tournament(name="active_tourney", tournament_type="knockout")
        t2 = Tournament(name="archived_tourney", tournament_type="knockout", is_archived=True)
        db.add(t1)
        db.add(t2)
        db.commit()
        
        result = list_tournaments(db)
        names = [t["name"] for t in result]
        assert "active_tourney" in names
        assert "archived_tourney" not in names
        
        result_all = list_tournaments(db, include_archived=True)
        names_all = [t["name"] for t in result_all]
        assert "active_tourney" in names_all
        assert "archived_tourney" in names_all
    finally:
        db.close()
        engine.dispose()
