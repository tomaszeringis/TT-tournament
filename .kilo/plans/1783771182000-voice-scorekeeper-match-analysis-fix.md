# Fix Voice Scorekeeper Match Analysis & Dashboard Completed Matches

## Branch
`ux-redesign-safe-pages`

## Root Cause (verified by code reading)

1. **Match Analysis shows `0-0`** — `voice_scorekeeper.py:3012` builds the summary
   `score` from `st.session_state.match_manager.state.get_score_string()`, which is the
   *current game point score*. In `score_engine.py:402-408` (`complete_game`) the game
   score is reset to `0-0` the moment a game (incl. the final/match-winning game)
   completes. So right after the match is won, `state.score_a/score_b == 0` and the
   Analytics section reports `0-0`. The real match result lives in
   `engine.games_won_a / engine.games_won_b` (e.g. `2-1`).

2. **Dashboard shows no completed matches** — `persist_voice_match_to_db`
   (`voice_scorekeeper.py:723`) is only invoked from the voice event loop
   (`_process_voice_events` line 1368) and pending-confirm apply (line 1111). The manual
   `+ / −` scoring buttons (`_add_point`) and the `Submit Result` report form do **not**
   auto-finalize the DB `Match` row, so manual completion leaves the row `pending`/`active`
   with `score IS NULL`. Dashboard/Recent Results filter on `status == completed`, so
   nothing shows.

3. **Score format is correct but volatile/inconsistent** — `match.score` must stay
   `"gamesWonA-gamesWonB"` (e.g. `"2-1"`); `events_draws.py:376,429,523` and
   `ai_tournament_suggestions.py:131` parse `score.split('-')` expecting exactly two ints.
   `persist_voice_match_to_db` already uses this format (good); the game-by-game
   `round_scores` must NOT be stored in `match.score`.

4. **Ratings not updated on voice completion** — `persist_voice_match_to_db` writes
   score/winner/status but never calls `rating_manager.update_ratings`. Operator/API flows
   (`/api/report`, `/api/operator/matches/{id}/report`) do. Voice completion should be
   consistent.

## Goal
When a match is completed in Voice Scorekeeper (voice OR manual), the canonical `Match` row
is finalized once through the existing service/API flow (correct `score`, `winner`,
`winner_id`, `status=completed`, ratings), the Dashboard shows it, and Match Analysis shows
the real match result + game-by-game. No redesign; ASR/transcription untouched; existing
`/api/report`, `/api/match/parse`, models, tests preserved.

## Plan

### A. Canonical finalize helper (single source of truth)
In `tournament_platform/app/pages/voice_scorekeeper.py`:
- Keep `persist_voice_match_to_db` for **in-progress** persistence only (writes
  `score="gamesWonA-gamesWonB"`, `status=active`).
- Add `finalize_voice_match(match_id, engine)` that, when `engine.match_status == "match_won"`,
  reuses the existing `report_existing_match` (`services/match_reporting.py`) with
  `score=f"{games_won_a}-{games_won_b}"` and the winner resolved from
  `engine.player_a/b_name/id`, then calls `rating_manager.update_ratings(winner_id, loser_id)`
  exactly as `api/server.py:140-146` does. Mirror the API endpoint so rating/bracket
  behavior stays compatible. Use a guard so it runs only once per match (e.g. skip if the DB
  row is already `completed`).
- Import `report_existing_match` and `RatingManager` at top (already importable).

### B. Wire finalize into ALL completion paths
- `apply_voice_event` success path in `_process_voice_events` (after line 1368) and
  `_apply_pending` (after line 1111): if match won, call `finalize_voice_match`.
- Manual `+ / −` buttons (`add_point_a`, `add_point_b` ~line 2057/2150): after
  `_add_point`, if `st.session_state.match_manager.engine.match_status == "match_won"` and a
  `voice_selected_match_id` is set, call `finalize_voice_match`.
- Scoreboard "📤 Submit Result" (line 2210) and the "Submit Match Result" game-by-game
  button (line 2312): keep using the API, but ensure they don't double-finalize; rely on the
  `already completed` guard. (The game-by-game submit currently sends
  `score="11-3, 11-8, 11-5"` — change it to send the match result `"gamesWonA-gamesWonB"`
  for consistency with `match.score` parsers, while passing game details separately — see C.)

### C. Fix Match Analysis (lines 2997–3053)
- `score` → `f"{engine.games_won_a}-{engine.games_won_b}"` (match result), NOT
  `state.get_score_string()`.
- `winner` → resolve from `engine.games_won_a/engine.games_won_b` vs
  `engine.player_a/b_name`.
- Add `game_scores` = `[f"{a}-{b}" for a,b in engine.round_scores]` to `_meta` so
  `MatchSummaryService` carries game-by-game (already supported via `MatchSummary.game_scores`).
- If a `voice_selected_match_id` is set, prefer reading `score`/`winner` from the persisted
  DB `Match` row so the summary is correct even after a reset/rematch.

### D. Minor: `summarize_match` completion threshold (match_score.py:126-129)
`winner_side` is hardcoded to `>= 3`, which breaks `best_of=3` (needs 2). Change to
`needed = (best_of // 2) + 1` (pass `best_of` in). Ensures the "Submit Match Result" button
appears for best-of-3, so those matches can be persisted.

### E. Durable game-by-game storage (APPROVED — add `game_scores` column)
- Add nullable `game_scores = Column(Text, nullable=True)` to `Match` in
  `tournament_platform/models.py` (near other match columns).
- Add an Alembic migration
  `tournament_platform/alembic/versions/0xx_add_match_game_scores.py` mirroring the existing
  `006_add_match_player_fks.py` pattern (batch_op.add_column guarded by existing-columns check)
  so it is idempotent and re-runnable. Wire it into the migration env if the project uses
  `alembic upgrade head` in setup; otherwise rely on `Base.metadata.create_all` in `init_db()`
  (the app's normal table creation) — verify which path the repo uses and keep both consistent.
- In `finalize_voice_match`, persist
  `match.game_scores = json.dumps([list(g) for g in engine.round_scores])` (or
  `"11-3,11-8,11-5"`). `match.score` stays `"a-b"`.
- `MatchSummaryService` already exposes `game_scores`; Match Analysis passes
  `engine.round_scores` formatted as a list of `"a-b"` strings, falling back to the DB
  `game_scores` JSON when the engine state was reset.

## Files
- `tournament_platform/app/pages/voice_scorekeeper.py` (A,B,C)
- `tournament_platform/app/services/match_score.py` (D)
- `tournament_platform/services/match_reporting.py` (reused, unchanged)
- `tournament_platform/models.py` + new Alembic migration (E)
- `tournament_platform/app/services/voice/match_summary.py` (already supports game_scores)

## Validation
- Add/extend a test: score a match to `match_won` via `MatchManager`/`score_engine`, call
  `finalize_voice_match`, assert `Match.score == "2-1"`, `status == completed`,
  `winner_id` set, and `update_ratings` recorded a `RatingHistory` row.
- Assert `summarize_match`/`Match Analytics` uses `games_won_a-games_won_b` (not `0-0`).
- Run `pytest tests/test_regression.py tests/test_comprehensive.py tests/test_match_manager_engine.py`
  and the voice scorekeeper tests; confirm `/api/report`, `/api/match/parse`, rating and
  `bracket_manager` (events_draws) behavior unchanged.
- Manual: complete a match with manual buttons + with voice; verify Dashboard Recent Results
  shows it with correct winner/score and Match Analysis shows game-by-game.
