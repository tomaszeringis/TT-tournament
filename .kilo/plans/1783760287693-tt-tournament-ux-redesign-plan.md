# TT Tournament Platform — Merge Operator Console & Schedule Board into Admin

**Branch:** `ux-redesign-safe-pages`
**Mode:** Plan only (no code changes)
**Date:** 2026-07-11
**Scope:** Merge `operator_console.py` and `schedule_board.py` into the existing Admin page as tabs (no new nav pages). Widen Admin visibility to the `operator` role.

---

## Context (verified from code)

- `main.py:84-88` gates the Admin page to `user_role == "admin"` only.
- `main.py:60-111` uses `st.navigation` with sectioned `st.Page` lists. Experimental pages are gated behind `DEBUG_UI_ENABLED`/admin.
- `admin.py` currently has tabs: `["Database Overview", "Match Management", "System Health", "Danger Zone"]` and title "Admin / Operator Console" (`admin.py:67,76`).
- `operator_console.py` exposes embeddable renderers (no `set_page_config` at top level):
  - `render_match_queue_tab(selected_id: int)` (`operator_console.py:163`)
  - `render_table_status_tab(selected_id: int)` (`operator_console.py:450`)
  - `render_operator_console()` (`operator_console.py:501`) — **calls `st.set_page_config` at `:503`**, so it must NOT be called from within Admin.
- `schedule_board.py` only exposes `render_schedule_board()` (`schedule_board.py:40`), which **calls `st.set_page_config` at `:42`** plus its own title/selector/date-range. It must be refactored to expose a `set_page_config`-free tab renderer before embedding.
- Both page modules import safely at top level (no `set_page_config` at import; no `streamlit-webrtc`). Importing them into Admin is safe.
- Both modules define a `load_tournaments()` helper; import them as modules (not star imports) to avoid name collisions: `import tournament_platform.app.pages.operator_console as op` and `...schedule_board as sched`.
- **Other orphaned pages** (from earlier consolidation `f561a1f`): `public_board.py` and `player_profile.py` are also not in nav. Out of scope here; keep as a separate restore-nav task. `participants.py`/`rankings.py` are already redirect stubs.
- **Test discovery gap (separate):** `pyproject.toml` sets `testpaths=["tournament_platform"]`, so the large root `tests/` directory is not collected by default `pytest`. Address in a separate baseline task.

---

## Decision

- Do **not** add new `st.Page` nav entries for Operator Console or Schedule Board.
- Merge both into the **Admin page** as new tabs.
- Make the Admin page visible to roles `"admin"` **and** `"operator"` (per user choice).

---

## Implementation Steps (ordered)

### 1. Widen Admin visibility (`main.py`)
- `main.py:84-88`: change the admin gate from `if user_role == "admin":` to `if user_role in ("admin", "operator"):`.
- Recommend renaming the nav title from `"Admin"` to `"Admin / Operator"` (`main.py:87`) for clarity, since operators now land here.
- Ensure operator-role accounts exist in `config.yaml` credentials (or Streamlit secrets) — add a note/validation; default role fallback is `"user"` (`main.py:45`), which must stay excluded.

### 2. Refactor `schedule_board.py` to expose an embeddable tab renderer
- Extract `render_schedule_tab(tournament_id: int, start_date, days_ahead: int) -> None` containing the body currently after the selector (`schedule_board.py:72-206`), with **no** `st.set_page_config`/title.
- Keep `render_schedule_board()` as a thin wrapper: `st.set_page_config(...)` + tournament selector + `render_schedule_tab(selected_id, start_date, days_ahead)` (preserves legacy/deep-link behavior; harmless since the page is no longer in nav).
- Do **not** change `load_schedule` / `get_public_schedule` calls.

### 3. Add tabs to `admin.py`
- Add imports at top (module imports to avoid collisions):
  ```python
  import tournament_platform.app.pages.operator_console as op
  import tournament_platform.app.pages.schedule_board as sched
  from tournament_platform.services.tournament_read_models import list_tournaments
  ```
- Extend the tab list (`admin.py:76`):
  ```python
  admin_tabs = st.tabs([
      "Database Overview", "Match Management",
      "Operator Console", "Schedule Board",
      "System Health", "Danger Zone",
  ])
  ```
- **Operator Console tab** (`with admin_tabs[2]:`):
  - Render one shared tournament selector with a unique key (e.g. `admin_op_tournament_select`); resolve `selected_id`.
  - Inside, create sub-tabs `["Match Queue", "Table Status"]` and call `op.render_match_queue_tab(selected_id)` and `op.render_table_status_tab(selected_id)`.
  - These renderers already handle their own actions/`st.rerun()`; no further wiring needed.
- **Schedule Board tab** (`with admin_tabs[3]:`):
  - Render tournament selector (unique key `admin_sched_tournament_select`) + `st.date_input` (`admin_sched_start_date`) + `st.number_input` days (`admin_sched_days_ahead`).
  - Call `sched.render_schedule_tab(selected_id, start_date, days_ahead)`.
- Use distinct widget keys across both new tabs to avoid Streamlit key collisions with existing Admin widgets.

### 4. Keep the standalone page files (no deletion)
- `operator_console.py` and `schedule_board.py` remain on disk as importable modules but are **not** registered in `main.py` navigation. This satisfies "do not add more pages" and avoids deletion/relocation risk.
- Optional later cleanup (separate task, not now): convert both to redirect stubs (mirroring `participants.py`/`rankings.py`) and move render functions into `app/components/` once the merge is proven stable.

### 5. Tests
- Extend `tests/test_voice/test_navigation.py` (or add `tests/test_admin_tabs.py`): assert Admin registers for `operator` and `admin` roles and is absent for `user`.
- Add an import/smoke test: `render_match_queue_tab` and `render_schedule_tab` are importable and callable without raising `StreamlitSetPageConfigMustBeFirstCommand` (i.e., they don't call `set_page_config`).
- Run both suites: `pytest tournament_platform -q` and `pytest tests/ -q` (note the discovery gap; track separately).

---

## Affected files
- `tournament_platform/app/main.py` (role gate + optional title)
- `tournament_platform/app/pages/admin.py` (imports + 2 new tabs)
- `tournament_platform/app/pages/schedule_board.py` (extract `render_schedule_tab`)
- `tournament_platform/config.yaml` (ensure operator-role accounts exist — documentation/validation)
- tests (navigation + import smoke)

## Not changed
- `operator_console.py` render functions (reused as-is)
- `main.py` navigation structure / other pages
- `/api/report` and other API contracts (preserved)
- Public Board / Player Profile nav (separate task)

## Risks
- **Widget key collisions:** Admin's existing widgets vs new tabs' selectors. Mitigation: unique `admin_*` keys; verify no `DuplicateWidgetID` errors.
- **`st.set_page_config` conflict:** must never call `op.render_operator_console()` or `sched.render_schedule_board()` from Admin. Mitigation: use only `render_match_queue_tab`/`render_table_status_tab`/`render_schedule_tab`.
- **Operator role missing:** if no operator accounts exist, widening the gate has no effect. Mitigation: document required credentials; verify config.
- **Import side effects:** importing page modules is safe (verified), but if either later adds top-level `st.*` calls, Admin import breaks. Mitigation: import as modules; keep page modules free of top-level Streamlit commands.

## Validation checklist
- [ ] `streamlit run tournament_platform/app/main.py`: log in as **operator** → "Admin / Operator" page visible with "Operator Console" and "Schedule Board" tabs.
- [ ] Log in as **admin** → same, plus all existing admin tabs.
- [ ] Log in as regular **user** → Admin page NOT visible.
- [ ] Operator Console tab: select a tournament → Match Queue + Table Status render; call/start/complete/delay actions work and audit log updates.
- [ ] Schedule Board tab: select tournament + date range → schedule renders.
- [ ] No `DuplicateWidgetID` or `set_page_config` errors in logs.
- [ ] Both test suites collect and pass (or failures documented).

## Rollback
- Revert `main.py` role-gate change and `admin.py` tab additions (single commit). No database or model changes. Standalone page files were not modified structurally, so no data impact.

## Acceptance criteria
- Operator Console + Schedule Board are reachable via the Admin page for `admin` and `operator` roles, with no new nav pages added.
- No `st.set_page_config` is invoked inside Admin.
- Existing Admin tabs and functionality remain intact.
- Public Board / Player Profile remain a separate restore-nav task (out of scope here).
