"""Streamlit Cloud entrypoint.

Streamlit Cloud runs this module as the app's main file. The real UI lives in
``tournament_platform/app/main.py`` (a standard Streamlit script using ``st.*``
and ``st.navigation``).

This entrypoint must NOT start a Uvicorn/FastAPI server. The API backend is a
separate service (deploy ``tournament_platform/api/server.py`` separately or set
``API_BASE_URL`` to an external service). The Streamlit app provides its own
server and ``/healthz`` endpoint, so Streamlit Cloud's healthcheck passes.
"""

from tournament_platform.app.main import main

main()
