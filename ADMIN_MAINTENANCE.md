# Admin Maintenance Actions

This document lists the preserved admin maintenance actions in the Tournament Platform.

## Overview

The Admin Panel provides maintenance and monitoring capabilities for tournament administrators. All actions are preserved and tested to ensure they continue to work during and after refactoring.

## Preserved Actions

### 1. Database Overview

**Location:** Admin Panel → Database Overview tab

**Description:** Displays summary counts of all database entities.

**Data shown:**
- Total Players count
- Total Matches count
- Total Tournaments count
- Completed Matches count

**Helper function:** `get_admin_counts(db)` in `tournament_platform/services/admin_maintenance.py`

**Tests:** `tests/test_admin_maintenance.py::TestGetAdminCounts`

---

### 2. Player Statistics

**Location:** Admin Panel → Database Overview tab

**Description:** Shows detailed player statistics including matches played, wins, losses, and win rate.

**Data shown:**
- Player name
- Email
- Rating
- Total matches
- Wins
- Losses
- Win rate percentage

**Helper function:** `get_player_statistics(db)` in `tournament_platform/services/player_stats.py`

---

### 3. Match Filtering

**Location:** Admin Panel → Match Management tab

**Description:** Filter and view matches by status and/or tournament.

**Filters available:**
- Status filter: All, pending, active, completed
- Tournament filter: All tournaments or specific tournament

**Helper function:** `get_filtered_matches(db, status_filter, tournament_filter)` in `tournament_platform/services/admin_maintenance.py`

**Tests:** `tests/test_admin_maintenance.py::TestGetFilteredMatches`

---

### 4. Refresh Data

**Location:** Admin Panel → Match Management tab

**Description:** Clears all cached data and refreshes the page.

**Action:** Triggers `st.rerun()` to reload all data from the database.

**Helper function:** `clear_streamlit_cache()` in `tournament_platform/services/admin_maintenance.py`

---

### 5. Clear All Cache

**Location:** Admin Panel → Match Management tab

**Description:** Clears all Streamlit cached data without page reload.

**Action:** Calls `st.cache_data.clear()` to invalidate all cached data.

**Helper function:** `clear_streamlit_cache()` in `tournament_platform/services/admin_maintenance.py`

---

### 6. System Health / Status Display

**Location:** Admin Panel → System Health tab

**Description:** Displays the current status of system components.

**Components checked:**
- Database connection status
- FastAPI API status (via `ApiClient.health()`)
- Ollama AI status
- Rules retrieval status

**Integrations displayed:**
- Teams webhook configuration
- Azure Calendar configuration

**Helper functions:**
- `get_safe_database_status()` in `tournament_platform/services/admin_maintenance.py`
- `get_safe_api_status()` in `tournament_platform/services/admin_maintenance.py`
- `get_safe_teams_status()` in `tournament_platform/services/admin_maintenance.py`
- `get_safe_azure_status()` in `tournament_platform/services/admin_maintenance.py`
- `get_runtime_versions()` in `tournament_platform/services/admin_maintenance.py`

**Tests:** `tests/test_admin_maintenance.py::TestGetSafeDatabaseStatus`

---

### 7. Environment Warnings

**Location:** Admin Panel → System Health tab

**Description:** Displays warnings for potentially problematic configuration settings.

**Warnings checked:**
- `API_BASE_URL` using default value (http://localhost:8000)
- Teams webhook not configured or using placeholder URL
- `SHOW_DEBUG_DETAILS` enabled in production
- SQLite database in use (not recommended for multi-user production)

**Helper function:** `get_environment_warnings()` in `tournament_platform/services/admin_maintenance.py`

**Tests:** `tests/test_admin_maintenance.py::TestGetEnvironmentWarnings`

---

## Security Notes

- All error messages shown to users are sanitized and do not expose:
  - Database connection strings
  - File system paths
  - Cookie secrets
  - Credentials
  - Internal exception details

- Detailed error information is logged but not displayed in the UI.

- The `safe_error_message()` helper in `tournament_platform/services/admin_maintenance.py` ensures user-safe error handling.

## Testing

All admin maintenance helpers are tested with isolated in-memory SQLite databases:

```bash
# Run admin maintenance tests
python -m pytest tests/test_admin_maintenance.py -v

# Run all regression tests
python -m pytest tests/test_regression.py -v
```

## File Structure

```
tournament_platform/
├── services/
│   └── admin_maintenance.py    # Extracted admin helpers
│   └── player_stats.py         # Player statistics service
└── app/
    └── pages/
        └── admin.py            # Admin UI (uses extracted helpers)

tests/
├── test_admin_maintenance.py   # Tests for admin helpers
└── test_regression.py          # Regression tests for critical flows