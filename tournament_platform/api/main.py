"""FastAPI backend entrypoint.

This module is the **separate** backend process. It must NOT be imported or run
by the Streamlit Cloud app. Run it locally (optionally behind ngrok) with:

    uvicorn tournament_platform.api.main:app --host 127.0.0.1 --port 8000 --reload

or:

    python -m tournament_platform.api.main

The Streamlit Cloud app runs only ``streamlit run streamlit_app.py`` and never
starts this server.
"""

from tournament_platform.api.server import app


def main() -> None:
    """Run the FastAPI backend via Uvicorn (local development only)."""
    import uvicorn
    from tournament_platform.config import settings

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)


if __name__ == "__main__":
    main()
