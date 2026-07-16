"""Streamlit Cloud entrypoint.

Streamlit Cloud runs this module as the app's main file. The real UI lives in
``tournament_platform/app/main.py`` (a standard Streamlit script using ``st.*``
and ``st.navigation``). Importing it executes that script, which is exactly how
``streamlit run`` would run it directly.

Note: this entrypoint must NOT start a Uvicorn/FastAPI server. The API backend
is a separate service (deploy ``tournament_platform/api/server.py`` separately
or set ``API_BASE_URL`` to an external service).
"""

import tournament_platform.app.main  # noqa: F401  (executes the Streamlit app)
