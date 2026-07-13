"""
Tests for commentary event logging helpers.
"""

import pytest
from unittest.mock import Mock, MagicMock

from tournament_platform.services.commentary_service import (
    log_commentary_event,
    get_recent_commentary_events,
    get_commentary_events_for_tournament,
)


class TestLogCommentaryEvent:
    def test_persists_row(self):
        db = MagicMock()
        row = log_commentary_event(
            db_session=db,
            tournament_id=1,
            match_id=2,
            player_a="Alice",
            player_b="Bob",
            event_type="point_scored",
            source_event_json="{}",
            score_before_json="{}",
            score_after_json="{}",
            style="neutral",
            language="en",
            commentary_mode="every_point",
            intensity="medium",
            template_id="t1",
            generated_text="Point for Alice. 1 to 0.",
            final_text="Point for Alice. 1 to 0.",
            used_ollama=False,
            ollama_model=None,
            ollama_cache_hit=False,
            spoken=True,
            tts_mode="audio_every_score",
            latency_ms=10.0,
            error=None,
            cache_key="ck1",
        )
        assert row.player_a == "Alice"
        assert row.event_type == "point_scored"
        assert db.add.called
        assert db.commit.called

    def test_rollback_on_commit_error(self):
        db = MagicMock()
        db.commit.side_effect = Exception("db error")
        with pytest.raises(Exception):
            log_commentary_event(
                db_session=db,
                tournament_id=None,
                match_id=None,
                player_a=None,
                player_b=None,
                event_type="unknown",
                source_event_json="{}",
                score_before_json=None,
                score_after_json=None,
                style="neutral",
                language="en",
                commentary_mode="off",
                intensity="low",
                template_id=None,
                generated_text="",
                final_text="",
                used_ollama=False,
                ollama_model=None,
                ollama_cache_hit=False,
                spoken=False,
                tts_mode=None,
                latency_ms=None,
                error=None,
                cache_key=None,
            )
        assert db.rollback.called


class TestGetRecentCommentaryEvents:
    def test_returns_empty_when_no_events(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        from tournament_platform.services.commentary_service import get_recent_commentary_events
        result = get_recent_commentary_events(1, limit=5)
        assert result == []


class TestGetCommentaryEventsForTournament:
    def test_returns_empty_when_no_events(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        from tournament_platform.services.commentary_service import get_commentary_events_for_tournament
        result = get_commentary_events_for_tournament(1, limit=5)
        assert result == []