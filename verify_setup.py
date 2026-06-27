#!/usr/bin/env python3
"""
Setup Verification Script - Tests all key components of the tournament platform.
Run this to ensure everything is properly configured and ready for use.

Usage:
    python verify_setup.py
"""

import sys
import os

def test_imports():
    """Test all main package imports."""
    print("\n📦 Testing Package Imports...")
    try:
        import streamlit
        print("  ✓ streamlit")
        import fastapi
        print("  ✓ fastapi")
        import sqlalchemy
        print("  ✓ sqlalchemy")
        import alembic
        print("  ✓ alembic")
        import chromadb
        print("  ✓ chromadb")
        import pydantic
        print("  ✓ pydantic")
        import plotly
        print("  ✓ plotly")
        import ollama
        print("  ✓ ollama")
        print("  ✓ All packages imported successfully!")
        return True
    except ImportError as e:
        print(f"  ✗ Import error: {e}")
        return False

def test_models():
    """Test database models."""
    print("\n🗄️  Testing Database Models...")
    try:
        from tournament_platform.models import Player, Match, Tournament, MatchStatus, SessionLocal

        print("  ✓ Player model")
        print("  ✓ Match model")
        print("  ✓ Tournament model")
        print("  ✓ MatchStatus enum")
        print("  ✓ Database session factory")

        # Test database connectivity
        try:
            db = SessionLocal()
            player_count = db.query(Player).count()
            match_count = db.query(Match).count()
            tournament_count = db.query(Tournament).count()
            db.close()

            print(f"  ✓ Database connection successful")
            print(f"    - Players in database: {player_count}")
            print(f"    - Matches in database: {match_count}")
            print(f"    - Tournaments in database: {tournament_count}")
            return True
        except Exception as e:
            print(f"  ⚠️  Database tables not accessible: {e}")
            return False

    except Exception as e:
        print(f"  ✗ Database error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ai_engine():
    """Test AI engine."""
    print("\n🤖 Testing AI Engine...")
    try:
        from tournament_platform.services.ai_engine import AIEngine, MatchReport
        print("  ✓ AIEngine class")
        print("  ✓ MatchReport Pydantic model")

        ai = AIEngine()
        print("  ✓ AIEngine instance created")
        print("  ✓ ChromaDB initialized")
        return True
    except Exception as e:
        print(f"  ✗ AI Engine error: {e}")
        return False

def test_migrations():
    """Test Alembic migrations."""
    print("\n📜 Testing Alembic Migrations...")
    try:
        from alembic.config import Config
        from alembic import command
        import tempfile

        # Check if alembic.ini exists
        config_path = os.path.join(os.path.dirname(__file__), 'tournament_platform', 'alembic.ini')
        if os.path.exists(config_path):
            print("  ✓ alembic.ini found")
        else:
            print("  ✗ alembic.ini not found")
            return False

        # Check if migration files exist
        versions_path = os.path.join(os.path.dirname(__file__), 'tournament_platform', 'alembic', 'versions')
        if os.path.exists(versions_path):
            migration_files = [f for f in os.listdir(versions_path) if f.endswith('.py') and f != '__init__.py']
            print(f"  ✓ Migration directory found ({len(migration_files)} migrations)")
        else:
            print("  ✗ Migration directory not found")
            return False

        return True
    except Exception as e:
        print(f"  ✗ Migration error: {e}")
        return False

def test_directories():
    """Test required directories."""
    print("\n📁 Testing Directories...")
    base_path = os.path.dirname(__file__)

    required_dirs = {
        'tournament_platform': 'Main package',
        'tournament_platform/app': 'Streamlit app',
        'tournament_platform/api': 'FastAPI server',
        'tournament_platform/services': 'Services module',
        'tournament_platform/alembic': 'Alembic migrations',
        'tournament_platform/data': 'Data directory',
        'tournament_platform/logs': 'Logs directory',
    }

    all_exist = True
    for dir_path, description in required_dirs.items():
        full_path = os.path.join(base_path, dir_path)
        if os.path.isdir(full_path):
            print(f"  ✓ {dir_path} ({description})")
        else:
            print(f"  ✗ {dir_path} ({description}) - NOT FOUND")
            all_exist = False

    return all_exist

def test_files():
    """Test required files."""
    print("\n📄 Testing Required Files...")
    base_path = os.path.dirname(__file__)

    required_files = {
        'tournament_platform/models.py': 'Database models',
        'tournament_platform/alembic.ini': 'Alembic config',
        'tournament_platform/alembic/env.py': 'Alembic environment',
        'tournament_platform/api/server.py': 'FastAPI server',
        'tournament_platform/app/main.py': 'Streamlit main',
        'tournament_platform/services/ai_engine.py': 'AI engine',
        'tournament_platform/data/tournament.db': 'SQLite database',
    }

    all_exist = True
    for file_path, description in required_files.items():
        full_path = os.path.join(base_path, file_path)
        if os.path.isfile(full_path):
            size = os.path.getsize(full_path)
            print(f"  ✓ {file_path} ({description}) - {size} bytes")
        else:
            print(f"  ✗ {file_path} ({description}) - NOT FOUND")
            all_exist = False

    return all_exist

def test_rag():
    """Test RAG system."""
    print("\n🧠 Testing RAG System...")
    try:
        from tournament_platform.services.rules_retrieval import _get_chroma_client
        chroma_path = os.path.join(os.path.dirname(__file__), 'tournament_platform', 'data', 'chroma_db')
        if os.path.exists(chroma_path):
            client = _get_chroma_client(chroma_path)
            try:
                collection = client.get_collection(name="tournament_rules")
                count = collection.count()
                print(f"  ✓ ChromaDB collection found")
                print(f"  ✓ {count} rules stored in RAG system")
                return True
            except:
                print("  ⚠️  RAG not initialized yet (this is OK - run initialize_rag.py)")
                return True
        else:
            print("  ⚠️  ChromaDB directory not found (this is OK - will be created on first use)")
            return True
    except Exception as e:
        print(f"  ✗ RAG error: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 70)
    print("🎉 Tournament Platform - Setup Verification")
    print("=" * 70)

    results = {
        'Imports': test_imports(),
        'Directories': test_directories(),
        'Files': test_files(),
        'Models': test_models(),
        'Migrations': test_migrations(),
        'AI Engine': test_ai_engine(),
        'RAG System': test_rag(),
    }

    print("\n" + "=" * 70)
    print("📊 Verification Summary")
    print("=" * 70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print("\n" + "-" * 70)
    print(f"Result: {passed}/{total} checks passed")

    if passed == total:
        print("\n✅ Setup Complete! Ready to run:")
        print("\n   API Server:")
        print("     python tournament_platform/api/server.py")
        print("\n   Streamlit Frontend:")
        print("     streamlit run tournament_platform/app/main.py")
        return 0
    else:
        print(f"\n⚠️  Setup incomplete. {total - passed} check(s) failed.")
        print("Please review the errors above and fix any issues.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
