# LitIT Brandbook Implementation Plan — Streamlit App

**Branch:** `ux-redesign-safe-pages`
**Mode:** Plan only (no code changes)
**Date:** 2026-07-11
**Scope:** Apply LitIT visual brand system across the Streamlit app without breaking existing functionality, navigation, tests, APIs, database logic, tournament workflows, voice scoring, public board, operator console, or admin features.

---

## 1. Brand System Foundation

### 1.1 Color Palette (Design Tokens)
Replace the existing `design_system.py` `COLORS` dict with LitIT brand tokens:

```python
COLORS = {
    "litit_black": "#1A1C1B",     # Brand black (primary surfaces)
    "litit_white": "#FFFFFF",      # Brand white (text on dark)
    "primary": "#1A1C1B",          # LitIT Black used as primary action
    "primary_hover": "#2D2E2D",    # Slightly lighter black for hover
    "accent_blue": "#0066FF",      # Energetic blue for interactive accents
    "accent_green": "#00C853",     # Success / active states
    "accent_orange": "#FF6D00",    # Warning / attention
    "accent_red": "#FF1744",       # Danger / active alerts
    "accent_yellow": "#FFD600",    # Called / pending
    "background": "#0D0D0D",       # Deep black (app background)
    "surface": "#1A1C1B",          # Card / panel background
    "surface_elevated": "#242526", # Elevated cards / dropdowns
    "border": "#333436",           # Subtle borders
    "border_strong": "#4A4D4E",    # Stronger borders for focus
    "text_primary": "#FFFFFF",     # Primary text
    "text_secondary": "#B0B3B8",   # Secondary text
    "text_muted": "#6B7280",       # Muted / placeholder
}
```

Update `STATUS_COLORS` to use brand-consistent hex values:
- active → `#FF1744` (brand red)
- called → `#FFD600` (brand yellow)
- completed → `#00C853` (brand green)
- pending → `#0066FF` (brand blue)
- delayed → `#FF6D00` (brand orange)

### 1.2 Typography
- Primary: System sans-serif stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`)
- Monospace accent: `"Fira Code", "JetBrains Mono", "SF Mono", Consolas, monospace` (for code-like elements, scores, technical labels)
- Inject base font-family via `GLOBAL_STYLES` CSS:
  ```css
  body, .stApp { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  code, .mono { font-family: "Fira Code", "JetBrains Mono", "SF Mono", Consolas, monospace; }
  ```

### 1.3 Logo & Wordmark
**Verified:** No official LitIT logo assets exist in the repository (no SVG, PNG, WebP, or brand directory).

Create asset placeholder paths (do **not** generate fake logos):
- `assets/brand/litit-logo-light.svg` — black wordmark on transparent/light
- `assets/brand/litit-logo-dark.svg` — white wordmark on transparent/dark
- `assets/brand/litit-favicon.svg` — simplified mark for browser tab

**Rules:**
- Place logo in sidebar top with `2X` clearspace (use letter "I" width as unit X).
- On dark backgrounds: use `litit-logo-dark.svg` (white wordmark).
- On light backgrounds: use `litit-logo-light.svg` (black wordmark).
- Minimum digital size: full logo ≥ 30px wide; favicon ≥ 15px.
- Do not stretch, rotate, recolor, add shadows/gradients, or alter proportions.
- Add `part of NTT DATA` tagline at ~75% logo width when used in header lockup.

**Implementation:**
- Add `assets/brand/` directory to repo.
- In `main.py` sidebar, render logo with `<img>` tag using placeholder `src` pointing to the above paths.
- Add `onerror` fallback to render a CSS-styled text fallback: `<span style="font-weight:900;font-size:20px;letter-spacing:2px;">LIT_IT</span>`.
- Tagline rendered as `<small style="opacity:0.7;font-size:10px;">part of NTT DATA</small>` below the wordmark.

### 1.4 Favicon
- Update `st.set_page_config(page_title="LIT_IT ...", page_icon="assets/brand/litit-favicon.svg")` in `main.py` and any standalone page wrappers.
- Streamlit supports SVG favicons in recent versions; verify `streamlit>=1.58.0` supports it.

---

## 2. Global Theme Injection

### 2.1 Update `GLOBAL_STYLES` in `design_system.py`
Replace the existing CSS block with LitIT-branded styles:

- **Background:** `#0D0D0D` body, `#1A1C1B` containers.
- **Cards:** `background: #1A1C1B`, `border: 1px solid #333436`, `border-radius: 8px`.
- **Buttons:**
  - Primary: `background: #1A1C1B`, `color: #FFFFFF`, `border: 1px solid #FFFFFF`, hover → `#2D2E2D`.
  - Secondary: `background: transparent`, `color: #B0B3B8`, `border: 1px solid #333436`, hover → `border-color: #B0B3B8`.
- **Focus indicators:** `outline: 2px solid #0066FF`, `outline-offset: 2px`.
- **Tabs:** active tab → `border-bottom: 2px solid #0066FF`, inactive → `color: #6B7280`.
- **Sidebar:** `background: #0D0D0D`, `border-right: 1px solid #333436`.
- **Metric cards:** consistent with dark surface, accent-colored top border or left accent bar.
- **Scrollbars:** dark theme (`#333436` track, `#4A4D4E` thumb) for webkit.

### 2.2 Centralize Inline CSS
Many pages have repeated inline `<style>` blocks in markdown:
- `public_board.py` — match cards, coming up, delayed, announcements, recent results.
- `dashboard.py` — recent results, upcoming matches.
- `operator_console.py` — match queue items (via `operator_components.py`).
- `home.py` — containers.

**Action:** Create helper functions in `design_system.py` (or a new `tournament_platform/app/components/branded_cards.py`) that generate the branded HTML strings:
- `render_litit_match_card(...)` replacing `render_match_card`
- `render_litit_coming_up_card(...)` replacing `render_coming_up_card`
- `render_litit_delayed_card(...)` replacing `render_delayed_card`
- `render_litit_announcement_card(...)` replacing inline announcement HTML
- `render_litit_result_row(...)` replacing inline recent-results HTML

Each helper accepts `**kwargs` for dynamic data and returns the branded HTML. This reduces duplication and makes future theme changes safe.

---

## 3. Page-by-Page Updates

### 3.1 `main.py` — Entry Point & Sidebar
- Update `page_title` to `"LIT_IT Tournament Platform"`.
- Update sidebar:
  - Render `assets/brand/litit-logo-dark.svg` at top with clearspace.
  - Render tagline `part of NTT DATA` below.
  - Update user info section to use `text_secondary` color.
  - Add brand-colored divider (`border-top: 1px solid #333436`).
- Keep all auth and navigation logic untouched.

### 3.2 `pages/home.py` — Home Page
- Update `render_page_header` title from `"Tournament Platform"` to `"LIT_IT"` (or `"LIT_IT Tournament Platform"`).
- Update section subheaders to use brand styling (via `GLOBAL_STYLES`).
- Replace generic `st.success` / `st.warning` / `st.info` colors where possible — Streamlit's built-in status colors cannot be fully overridden via CSS, but the surrounding containers and text can be branded.
- Quick action buttons: ensure `type="primary"` uses the new LitIT primary color via global CSS.

### 3.3 `pages/public_board.py` — Public Board
- Update page title markdown to `🏆 LIT_IT Tournament Board`.
- Replace all hardcoded `#1e1e1e`, `#333`, `#4CAF50`, `#2196F3`, `#f44336`, `#FFC107` with brand tokens.
- Use centralized card helpers from `design_system.py`.
- Kiosk mode CSS override stays, but ensure background matches `#0D0D0D`.
- Update timestamp and section headers to use brand-consistent text colors.

### 3.4 `pages/operator_console.py` — Operator Console
- Update title to `🎛️ LIT_IT Match Center`.
- Update `operator_components.py` to use brand colors for:
  - Table status cards (busy → accent red, available → accent green, inactive → text muted).
  - Quick action buttons.
  - Command bar styling.
- Ensure `st.container(border=True)` renders with brand border color (via global CSS on `[data-testid="stContainer"]`).

### 3.5 `pages/admin.py` — Admin / Operator Console
- Update title from `"Admin / Operator Console"` to `"LIT_IT Admin"` (or keep `"LIT_IT Admin / Operator"`).
- Update `ui.metric_card` calls to use brand-appropriate styling.
- Ensure Danger Zone section uses brand red accents.
- Tab labels remain functional; no emoji changes needed unless requested.

### 3.6 `pages/dashboard.py` — Dashboard
- Update title to `📊 LIT_IT Dashboard`.
- Update tab labels to brand style (keep icons or remove per clean-top-bar rule).
- Replace hardcoded colors in `render_recent_results_tab` and `render_upcoming_matches_tab` with brand tokens.
- Plotly radar chart: update title/colors if needed to match dark theme.

### 3.7 `pages/events_draws.py` — Events & Draws
- Update tournament creation wizard header.
- Ensure bracket renderer (`components/interactive_bracket/`) uses brand colors for lines, nodes, and backgrounds.

### 3.8 Other Pages
- `ai_assistant.py` — update header.
- `voice_scorekeeper.py` — update header, ensure status indicators use brand colors.
- `video_scorekeeper.py` — update header.
- `dataset_catalog.py` — update header.
- `coaching_lab.py` — update header.
- `experiment_dashboard.py` — update header.

---

## 4. Component Updates

### 4.1 `design_system.py`
- Replace `COLORS` and `STATUS_COLORS` with brand tokens.
- Update `GLOBAL_STYLES` CSS block with full brand theme.
- Add centralized card HTML generators.
- Add `BRAND = { ... }` dict for brand metadata (name, tagline, logo paths).

### 4.2 `components/page_header.py`
- Update `render_page_header` to optionally accept a `branded: bool = True` flag.
- When branded, prepend the LIT_IT wordmark (text fallback or logo image) to the title area.
- Keep icons intentionally omitted per existing convention.

### 4.3 `components/operator_components.py`
- Update `render_table_status_card` colors.
- Update `render_quick_actions`, `render_command_bar`, `render_voice_shortcut` to use brand button styles.

### 4.4 `components/empty_state.py`
- Update empty state illustrations/text to use brand-consistent colors.

---

## 5. Navigation & Top Bar

### 5.1 Page Titles
- Replace `"TT Platform"` with `"LIT_IT"` everywhere.
- Update `st.set_page_config(page_title=...)` in:
  - `main.py`
  - `pages/public_board.py`
  - `pages/operator_console.py`
  - `pages/admin.py`
  - `pages/dashboard.py`
  - Any standalone page wrappers.

### 5.2 Sidebar
- Add logo + tagline at top.
- Use brand divider (`border-top: 1px solid #333436`) between sections.
- User info text: `#B0B3B8`.
- Logout button: use brand styling.

---

## 6. Asset Directory

### 6.1 Directory Structure
```
assets/
  brand/
    litit-logo-light.svg   (placeholder — needs official asset)
    litit-logo-dark.svg    (placeholder — needs official asset)
    litit-favicon.svg      (placeholder — needs official asset)
    README.md              (documents placeholder status and official asset request)
```

### 6.2 README.md Content
```markdown
# LitIT Brand Assets

This directory contains placeholder paths for the LitIT brand logo assets.

**Status:** Placeholders only. No official LitIT logo files have been added yet.

Before production deployment, replace these placeholders with official assets:
- `litit-logo-light.svg` — black wordmark for light backgrounds
- `litit-logo-dark.svg` — white wordmark for dark backgrounds
- `litit-favicon.svg` — simplified mark for browser tab

Logo rules:
- Do not stretch, rotate, recolor, add shadows, or alter proportions.
- Minimum full-logo width: ~30px. Favicon minimum: ~15px.
- Clearspace: 2X around logo (X = width of letter "I").
```

---

## 7. Accessibility & WCAG

- Verify all text/background contrast ratios meet WCAG AA (≥ 4.5:1 for normal text, ≥ 3:1 for large text).
- `#FFFFFF` on `#1A1C1B` → ~15:1 (passes).
- `#B0B3B8` on `#1A1C1B` → ~5.5:1 (passes for normal text).
- `#6B7280` on `#1A1C1B` → ~3.2:1 (use only for large text/decorative).
- Focus outlines: `#0066FF` on any background → verify contrast.
- Do not rely on color alone for status; keep icons (🔴🟡🟢🔵) alongside colored indicators.

---

## 8. Testing

### 8.1 Existing Tests
- `tests/test_admin_tabs.py` — already covers role gate and embeddable renderer smoke tests. No changes needed unless brand changes affect imports.
- Run: `pytest tournament_platform -q` and `pytest tests/ -q`.

### 8.2 New / Updated Tests
- **Brand token test:** `tests/test_design_system.py` — assert `design_system.COLORS` contains LitIT brand keys and values; assert `GLOBAL_STYLES` contains key CSS rules.
- **Page title test:** `tests/test_page_titles.py` — scan page modules for `set_page_config` and assert `page_title` starts with `"LIT_IT"`.
- **Logo placeholder test:** assert `assets/brand/` directory exists and contains the three placeholder files (or at least the README documenting the placeholder status).
- **No fake logo test:** assert no hardcoded text-based "LIT_IT" logos are rendered as production logos in `main.py` sidebar without the placeholder comment.

### 8.3 Manual Validation Checklist
- [ ] `streamlit run tournament_platform/app/main.py` loads with dark brand background.
- [ ] Sidebar shows logo placeholder + tagline with correct clearspace.
- [ ] All pages show `LIT_IT` branding in titles.
- [ ] Cards, buttons, tabs, badges use brand colors.
- [ ] Public Board displays correctly in kiosk mode with brand colors.
- [ ] Operator Console action buttons use brand primary/secondary styles.
- [ ] No broken images if logo assets are missing (fallback text renders).
- [ ] No `DuplicateWidgetID` or `set_page_config` errors.
- [ ] All existing pytest suites pass.

---

## 9. Rollback

- Revert `design_system.py` to previous color dict and CSS block.
- Revert `main.py` title/sidebar changes.
- Revert per-page title and inline-style changes.
- No database or API contract changes. All changes are UI-only.

---

## 10. Out of Scope

- Official LitIT logo asset creation (only placeholder paths and README are in scope).
- NTT DATA brand integration beyond the tagline text.
- Mobile-specific responsive redesign beyond what Streamlit naturally provides.
- Adding new pages or changing navigation structure.
- Changing tournament logic, voice scoring, AI engine, or database models.

---

## 11. Implementation Order

1. **Phase 1 — Foundation:** `design_system.py` brand tokens + `GLOBAL_STYLES` CSS + `assets/brand/` placeholders.
2. **Phase 2 — Core Pages:** `main.py` (titles, sidebar, favicon), `home.py`, `public_board.py`.
3. **Phase 3 — Operator & Admin:** `operator_console.py`, `components/operator_components.py`, `admin.py`.
4. **Phase 4 — Dashboard & Events:** `dashboard.py`, `events_draws.py`, bracket components.
5. **Phase 5 — Remaining Pages:** `ai_assistant.py`, `voice_scorekeeper.py`, `video_scorekeeper.py`, `dataset_catalog.py`, `coaching_lab.py`, `experiment_dashboard.py`.
6. **Phase 6 — Tests & Polish:** Brand token tests, title tests, manual validation, contrast audit.
