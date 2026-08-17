# Voice Scorekeeper — Component Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`

## Existing Reusable Components (do not duplicate, extend instead)

| Component | Location | Used for |
|-----------|----------|----------|
| `render_page_header` | `app/components/page_header.py` | Page title |
| `render_tour` | `app/components/tour.py` | Getting Started expander |
| `render_commentary_settings` | `app/services/voice/commentary.py` | Spoken Commentary config |
| `render_commentary_log` | `app/services/voice/commentary.py` | Commentary log expander |
| `render_commentary_debug` | `app/services/voice/commentary.py` | Commentary debug |
| `render_active_match_selector` | `app/components/match_selector.py` | Active tournament match selector |
| `render_selected_match_summary` | `app/components/match_selector.py` | Selected match summary |
| `render_runtime_diagnostics` | `app/components/runtime_diagnostics.py` | Runtime diagnostics inside voice diagnostics |

## New Components To Extract (per plan)

| Component | Target file | Source lines | Notes |
|-----------|-------------|--------------|-------|
| `manual_scoring` | `app/components/voice_scorekeeper/manual_scoring.py` | 5675–6235 | Player selection + scoreboard + correction controls + winner screens + rematch/new match |
| `voice_settings` | `app/components/voice_scorekeeper/voice_settings.py` | 4460–4562 | Voice toggle + mode + Audio Rally Assistant + noise calibration |
| `voice_input` | `app/components/voice_scorekeeper/voice_input.py` | 4563–5337 | Push-to-talk + continuous listening expander + WebRTC + debug pipeline + observability + dataset |
| `analytics_panel` | `app/components/voice_scorekeeper/analytics_panel.py` | 5352–5631 | Match Analytics + Teams Recap |
