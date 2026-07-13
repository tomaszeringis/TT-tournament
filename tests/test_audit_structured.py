"""
Tests for audit service structured logging extension.
"""

import pytest
from unittest.mock import MagicMock

from tournament_platform.services.audit_service import log_structured


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


def test_log_structured_creates_payload(mock_db):
    entry = log_structured(
        mock_db,
        action="merge_players",
        entity_type="player",
        entity_id=1,
        actor="operator",
        tournament_id=5,
        match_id=10,
        before={"name": "old"},
        after={"name": "new"},
        metadata={"source": "duplicate_scan"},
    )
    assert entry is not None
    payload = entry.payload_json
    import json
    parsed = json.loads(payload)
    assert parsed["_structured"]["tournament_id"] == 5
    assert parsed["_structured"]["match_id"] == 10
    assert parsed["_structured"]["before"]["name"] == "old"
