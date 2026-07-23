# Voice Annotation Roadmap

This document tracks planned voice-driven point annotations for advanced analytics.
No voice annotation features are implemented yet; this is a forward-looking roadmap.

## Planned Annotations

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `shot_type` | str | Voice command / manual selector | forehand, backhand, serve, etc. |
| `placement` | str | Voice command / manual selector | wide, body, short, etc. |
| `end_reason` | str | Voice command / manual selector | winner, error, rally, etc. |
| `rally_length` | int | Audio Rally Assistant (TT Sounds) | Auto-detected impact count |
| `notes` | str | Operator text input | Free-form per-point notes |

## Phases

- **Phase 1 (current)**: Core analytics on scoring-only point log. Annotations are accepted in schema but are optional and default to `None`.
- **Phase 2**: Add voice grammar entries for shot type, placement, and end reason. Populate fields from parsed voice events.
- **Phase 3**: Wire Audio Rally Assistant `rally_length` into the point log automatically.
- **Phase 4**: Add manual annotation dropdowns in the scorekeeper UI for operators to backfill missing annotations.
- **Phase 5**: Persist annotated point events to database (`match_point_events` table).

## Design Constraints

- Shot diversity must never hallucinate data. If >80% of points lack annotations, `compute_shot_diversity()` returns `available=False`.
- All new voice commands must go through the existing `apply_score_event_and_refresh_ui()` pipeline or a dedicated annotation endpoint.
- Do not add database migrations in Phase 1.
