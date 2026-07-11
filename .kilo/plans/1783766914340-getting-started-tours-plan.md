# Getting Started Tours — Implementation Plan

## Context (repository-grounded)

Branch: `ux-redesign-safe-pages` (Streamlit multipage app, `tournament_platform/app/`).

**Existing tour:** `tournament_platform/app/components/getting_started_tour.py`
- Uses `st.dialog` (Streamlit 1.35+), step-based via `st.session_state.tour_step` / `show_tour`.
- Only opened from a **Home sidebar button**. Never auto-shows.
- Has an unused `is_first_visit()` helper.
- Content = 5 generic platform-overview steps (Welcome, Setup, Matches, Public Board, Dashboard).
- Invoked by `render_home()` in `pages/home.py:150`.

**Navigation (`main.py`):** Home, Tournament (`events_draws.py`), Dashboard, AI Assistant (Experimental), Admin/Operator (`admin.py`, admin/operator roles only), and experimental pages (Voice/Video Scorekeeper, Dataset Catalog, Coaching Lab, Experiment Dashboard) gated by `settings.DEBUG_UI_ENABLED or user_role == "admin"`.

**Key findings:**
- `operator_console.py` is **NOT** in navigation; `admin.py` is the "Admin / Operator" nav entry. (Fold operator content into the Admin tour per decision.)
- `participants.py` / `rankings.py` are redirect stubs (consolidated into Events & Draws / Dashboard) — no tour needed.
- Centralized design system in `design_system.py` (`GLOBAL_STYLES`, brand tokens, `render_page_header`). Page titles are brand-enforced by `tests/test_page_titles.py` (AST scan of `set_page_config`).
- Tests are pytest, mostly pure-Python. Adding tour content does **not** affect existing tests.

## Decisions (confirmed with user)
1. **Manual-only**: tours open from a "Getting Started" help affordance, NOT auto-popped. (Keep "remember completed" + "Replay".)
2. **UI pattern**: `st.dialog` guided tour **+** a collapsible `st.expander` "Getting started" card at top of each page (mobile-friendly, always-available reference).
3. **Operator Console**: folded into the **Admin/Operator** tour (no new page/nav change).
4. **Scope**: the 9 brief areas **+ Public Board + Schedule Board + Video Scorekeeper**.
   Pages to receive tours: `home`, `events_draws` (Tournament), `voice_scorekeeper`, `ai_assistant`, `admin` (incl. operator workflows), `dataset_catalog`, `coaching_lab`, `experiment_dashboard`, `public_board`, `schedule_board`, `video_scorekeeper`.

## Architecture

### New shared module: `tournament_platform/app/components/tour.py`
Single source of truth (extend, do not duplicate, the existing tour).

- `TOUR_CONTENT: dict[str, dict]` — registry keyed by tour id. Each entry:
  ```python
  {
    "title": "<Page purpose, one line>",
    "intro": "<What this page is for + recommended first action>",
    "steps": [
        {"title": str, "icon": str, "content": str, "danger": bool, "example": str},
        ...
    ],
  }
  ```
  Required step keys: `title`, `icon`, `content`. Optional: `danger` (renders a ⚠️ warning style), `example`.
- Session-state helpers, **all namespaced with prefix `gs_tour_`** to avoid collisions with `voice_scorekeeper`'s many `voice_*` keys:
  - `gs_tour_{key}_show` (dialog open), `gs_tour_{key}_step`, `gs_tour_{key}_done`.
- Public API:
  - `render_tour(tour_key: str)` — calls `render_tour_expander` then `render_tour_dialog`. **This is the single call each page adds.**
  - `render_tour_expander(tour_key)` — `st.expander("❓ Getting started" + " ✅" if done, expanded=False)` with `intro`, a short bullet list of steps, and a "Start guided tour" button that sets `_show=True`, `_step=1`, `st.rerun()`.
  - `render_tour_dialog(tour_key)` — `@st.dialog(f"Getting started — {title}", width="large")` rendering current step, `st.progress`, and **Back / Next / Skip / Finish / Replay** controls:
    - Step 1 only → no Back.
    - Last step → "Finish" marks `gs_tour_{key}_done=True`, closes.
    - "Skip" marks done + closes (manual-only: we never force).
    - "Replay" (visible after done / on last step) resets `_step=1`.
    - All transitions use `st.rerun()` (matches existing pattern, safe with Streamlit reruns).
  - `is_tour_completed(tour_key) -> bool`, `reset_tour(tour_key)`.
- Keep `components/getting_started_tour.py` as a thin **back-compat shim**: `render_getting_started_tour()` and `is_first_visit()` delegate to `tour.py` (so any current import/test keeps working). Home tour id = `"home"`.

### Sidebar global launcher (optional, low-risk)
In `main.py` sidebar (near Logout), add a single `st.button("❓ Getting Started Tour")` that opens the `"home"` overview tour from any page (acts as global "Replay"). Reuses `render_tour_dialog("home")`.

## Per-page integration
Add exactly one line `render_tour("<key>")` immediately after each page's `st.title(...)` (or `render_page_header(...)`), inside the existing `if __name__ == "__main__":` render entry. Pages and hook locations:

| Page file | Tour key | Render entry |
|---|---|---|
| `pages/home.py` | `home` | in `render_home()` after `render_page_header` (replace `render_getting_started_tour()`) |
| `pages/events_draws.py` | `tournament` | after `st.title` in `render_events_draws()` |
| `pages/voice_scorekeeper.py` | `voice_scorekeeper` | after page title (module-level) |
| `pages/ai_assistant.py` | `ai_assistant` | after `st.title("LIT_IT AI Assistant")` |
| `pages/admin.py` | `admin` | after `st.title("LIT_IT Admin / Operator Console")` (include operator-console workflows) |
| `pages/dataset_catalog.py` | `dataset_catalog` | in `show()` after title |
| `pages/coaching_lab.py` | `coaching_lab` | in `show()` after title |
| `pages/experiment_dashboard.py` | `experiment_dashboard` | in `show()` after title |
| `pages/public_board.py` | `public_board` | in `render_public_board()` after title |
| `pages/schedule_board.py` | `schedule_board` | in `render_schedule_board()` after title |
| `pages/video_scorekeeper.py` | `video_scorekeeper` | after page title (module-level) |

> Note: `video_scorekeeper_live.py` is registered? Only `video_scorekeeper.py` appears in `main.py` nav. Tour `video_scorekeeper` covers the registered page; `video_scorekeeper_live.py` left as-is (note in PR).

## Tour content outline (concise; implementer expands to full copy)
- **home**: overview of full workflow (Create tournament → Register players → Generate draws → Run matches via Operator/Voice → Public Board → Dashboard/AI). First action: "Create Tournament" or "Resume". Mention Replay + per-page tours.
- **tournament (Events & Draws)**: tabs = Tournament wizard / Participants / Draws. First action: create tournament or add players. ⚠️ "Regenerate draws" discards in-progress brackets — confirm first.
- **voice_scorekeeper**: select tournament + match, start listening, confirmations gate live scoring, manual +/- fallback, dataset recording is opt-in. First action: pick active match. ⚠️ Voice commands apply to the **live** match; use confirmations; dataset recording stores audio (privacy).
- **ai_assistant (Experimental)**: ask natural-language questions; answers grounded in RAG/rules. First action: ask a rules/setup question. ⚠️ Experimental — verify critical answers against official rules.
- **admin (incl. Operator)**: DB summary, player/tournament stats; operator queue (call/start/complete/delay/reschedule matches), table status, audit log. First action depends on role. ⚠️ Maintenance actions (clear/reseed/reset) are **destructive** — explain before use; audit log records changes.
- **dataset_catalog (Experimental)**: browse `DatasetRegistry`, download, view features/license. First action: explore a dataset; watch license (non-commercial) warnings.
- **coaching_lab (Experimental)**: intent classifier + local demo recommendations. First action: run a sample analysis.
- **experiment_dashboard (Experimental)**: track ML/ASR experiment metrics. First action: view/add an evaluation result.
- **public_board**: read-only spectator view — live matches, results, announcements, auto-refresh 15s. First action: pick a tournament to follow.
- **schedule_board**: schedule/table timeline for upcoming days. First action: choose tournament + days-ahead range.
- **video_scorekeeper (Experimental)**: camera/pose-based scoring; needs camera permission. First action: grant camera + select match. ⚠️ Experimental; manual correction still required.

Consistent wording: each tour opens with "What this page is for", states "First action", flags "⚠️ Before you …" for dangerous/admin actions, and ends with "How it fits the workflow". Use brand tokens/emoji already in use; no new dependencies.

## Tests (add `tests/test_tour_framework.py`)
- `TOUR_CONTENT` contains all 11 expected keys.
- Every step dict has `title`, `icon`, `content`; `danger`/`example` optional.
- All state keys returned by helpers start with `gs_tour_` (no collision with `voice_*`).
- `render_tour`, `is_tour_completed`, `reset_tour` are callable and `is_tour_completed` defaults `False`.
- Confirm `tests/test_page_titles.py` and `tests/test_design_system.py` still pass (no page-level `set_page_config` or token changes).

## Risks / guardrails
- **No functional change**: tours are additive UI only; never touch auth, role gating, DB/API, match/voice/AI logic, or navigation structure.
- **Session-state isolation**: `gs_tour_` prefix prevents clobbering `voice_scorekeeper` keys.
- **Manual-only**: never auto-open (per decision) — no interruption of power users; completion remembered within session.
- **Experimental pages** (voice/video/dataset/coaching/experiment/ai) are gated; their tours are only visible to admins / when `DEBUG_UI_ENABLED`.

## Validation
1. `pytest` (full suite + new `test_tour_framework.py`) green.
2. `streamlit run tournament_platform/app/main.py` → log in as user and as admin.
3. For each target page: open the "❓ Getting started" expander; run the guided dialog; verify Back/Next/Skip/Finish/Replay and progress bar; confirm expander shows ✅ after completion.
4. Smoke-test preserved functionality: navigation, login/logout, create tournament, register player, generate draw, report match, voice scoring, AI assistant, admin maintenance, public board auto-refresh.
5. Verify `voice_scorekeeper` session keys/behavior unchanged (its many `voice_*` states intact).
