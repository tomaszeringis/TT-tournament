# Voice Scorekeeper — Rerun Site Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`
Total rerun calls: 28+

## Centralized Rerun Entry Points

| Call | Line | Trigger |
|------|------|---------|
| `_request_voice_rerun()` | 559 | Generic queue |
| `_maybe_voice_rerun()` | 564 | Polled in `render_voice_sections` |
| `st.rerun()` (player change) | 5800 | Player selection update |
| `st.rerun()` (format apply) | 5836 | Match format change |
| `st.rerun()` (add_point_a) | 5865 | Score A++ |
| `st.rerun()` (sub_point_a) | 5886 | Score A-- |
| `st.rerun()` (undo_point) | 5922 | Undo from center |
| `st.rerun()` (undo_game) | (implicit via engine) | Undo game |
| `st.rerun()` (reset_game) | 5947 | Reset current game |
| `st.rerun()` (reset_match) | 5959 | Reset match |
| `st.rerun()` (add_point_b) | 6014 | Score B++ |
| `st.rerun()` (sub_point_b) | 6035 | Score B-- |
| `st.rerun()` (next_game) | 6124 | Next game after game_won |
| `st.rerun()` (submit_result) | 6182 | Result submission |
| `st.rerun()` (rematch) | 6228 | Rematch |
| `st.rerun()` (new_match) | 6234 | New match |
| `st.rerun()` (speaker change) | 5979 | Speaker selection |
| `st.rerun()` (clear log) | 5069 / 5235 | Log clear |
| `st.rerun()` (debug process) | 5169 | Debug command |
| `st.rerun()` (ASR refresh) | 5051 | ASR status refresh |
| `st.rerun()` (AI summary) | 5510 | AI summary generate |
| `st.rerun()` (regenerate recap) | 5611 | Recap regenerate |
| `st.rerun()` (copy message) | (implicit via toast) | Copy Teams message |

## Planned Centralization

Replace all 28+ `st.rerun()` calls with `request_rerun(reason)` in `services/voice_scorekeeper/rerun_policy.py`, coalescing multiple reasons into one rerun per cycle.
