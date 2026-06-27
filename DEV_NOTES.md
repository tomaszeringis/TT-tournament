# Developer Notes

## Baseline status

**Date:** 2026-06-27  
**Python version:** 3.13.9  
**Branch:** quick-wins-ai-operator-console

### Commands run

- `python -m compileall .` — passed (exit 0)
- `python tournament_platform/test_models.py` — passed after fix
- `python tournament_platform/check_schema.py` — passed
- `python tournament_platform/check_tables.py` — passed after fix
- `python verify_setup.py` — passed after fix

### Failures found

1. **UnicodeEncodeError on Windows console (cp1252)**  
   `test_models.py`, `check_tables.py`, and `verify_setup.py` used Unicode checkmark/cross marks (✓/✗) and emoji characters in `print()` statements. The default Windows console codec (cp1252) cannot encode these characters, causing `UnicodeEncodeError` at runtime.

2. **No broken imports or missing `__init__.py` files**  
   All package imports resolved correctly. No syntax errors or path issues were found.

### Fixes made

- **`tournament_platform/test_models.py`** — Replaced `✓` with `[OK]` and `✗` with `[ERR]` in print statements.
- **`tournament_platform/check_tables.py`** — Replaced `✓` with `[OK]` in print statements.
- **`verify_setup.py`** — Replaced all Unicode emoji and checkmark characters with ASCII equivalents (e.g., `[OK]`, `[FAIL]`, `[PKG]`, `[DB]`, `[AI]`, etc.) to ensure Windows console compatibility.

### Remaining known issues

- **Other CLI scripts may still hit the same Windows console encoding issue:**  
  `initialize_rag.py`, `test_api.py`, and `tournament_platform/services/rules_ingestion.py` contain Unicode emoji in `print()` statements. These are not part of the required baseline check scripts, but may fail on Windows consoles without UTF-8 encoding.
- **Streamlit UI files intentionally retain emojis:**  
  Files under `tournament_platform/app/` (pages, components) use emojis in `st.title()`, `st.button()`, etc. These render correctly in the browser and do not need modification.
- **`ffmpeg` not found:**  
  `verify_setup.py` emits a `RuntimeWarning` from `pydub` about missing `ffmpeg`. This does not block setup but may affect audio processing features.

### How to start the app

```bash
# API server
python tournament_platform/api/server.py

# Streamlit frontend
streamlit run tournament_platform/app/main.py
```
