# API Compatibility Guide

This document describes the legacy `/api/report` endpoint and its compatibility requirements for Live Scoring integration.

## /api/report - Legacy Match Reporting

**Status:** Legacy but supported. This endpoint is the current mechanism for recording match results.

**Endpoint:** `POST /api/report`

### Payload Shape

The endpoint accepts a JSON payload with the following fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `match_id` | integer | Yes | The ID of the match to report. The match must already exist in the database. |
| `winner` | string | Yes | The name of the winner (must match either player1 or player2 name). |
| `score` | string | Yes | The match score (e.g., "11-9, 11-8"). Cannot be empty. |

**Example Request:**
```json
{
    "match_id": 123,
    "winner": "Alice",
    "score": "11-9, 11-8"
}
```

### Response Shape

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | "success" on successful match update |
| `match_id` | integer | The ID of the updated match |
| `message` | string | Human-readable confirmation message |

**Example Response:**
```json
{
    "status": "success",
    "match_id": 123,
    "message": "Match result recorded and notification sent"
}
```

### Error Responses

| Status Code | Condition |
|-------------|-----------|
| 400 | Invalid winner (not a participant), match already completed, or match not found |
| 400 | Invalid JSON format |
| 500 | Internal server error |

### Important Notes

1. **Match must exist:** The match must already be created in the database with `player1_id` and `player2_id` set. The endpoint does not create matches.

2. **Winner validation:** The winner name must match either `player1` or `player2` name (resolved from the FK columns).

3. **Status update:** On success, the match status is set to `completed`.

4. **Rating update:** If the match has both players and a winner, ratings are updated automatically.

## Live Scoring Integration

**Important:** Live Scoring must call `/api/report` or use the `ApiClient.report_match_legacy()` wrapper until a new `matchUp` scoring endpoint is implemented.

### Using the ApiClient Wrapper

```python
from tournament_platform.app.api_client import api_client

# Report a match result
result = api_client.report_match_legacy(
    match_id=123,
    score="11-9, 11-8",
    winner="Alice"
)

if result and result.get("status") == "success":
    print(f"Match {result['match_id']} recorded successfully")
```

### Finding a Match to Report

To report a match, you first need to find an active or pending match:

```python
# Get active matches for a tournament
matches = api_client.get(f"/api/tournaments/{tournament_id}/matches/active")
# Find a match with status "active" or "pending"
```

## Future Considerations

A new `matchUp` scoring endpoint may be added in the future to support:
- Real-time score updates during a match
- WebSocket-based live score streaming
- More granular match state management

When this endpoint is added, it will be documented here with migration guidance.