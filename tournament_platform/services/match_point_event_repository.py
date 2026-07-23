import csv
import json
import logging
from io import StringIO
from typing import List, Optional

from sqlalchemy.orm import Session

from tournament_platform.models import MatchPointEvent

logger = logging.getLogger(__name__)


class MatchPointEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, event: MatchPointEvent) -> MatchPointEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def create_many(self, events: List[MatchPointEvent]) -> None:
        self.db.bulk_save_objects(events)

    def list_by_match(self, match_id: int) -> List[MatchPointEvent]:
        return (
            self.db.query(MatchPointEvent)
            .filter(MatchPointEvent.match_id == match_id)
            .order_by(MatchPointEvent.game_index, MatchPointEvent.point_index)
            .all()
        )

    def delete_by_match(self, match_id: int) -> None:
        self.db.query(MatchPointEvent).filter(MatchPointEvent.match_id == match_id).delete()

    def to_json(self, events: List[MatchPointEvent]) -> str:
        payload = []
        for ev in events:
            payload.append({
                "id": ev.id,
                "match_id": ev.match_id,
                "game_index": ev.game_index,
                "point_index": ev.point_index,
                "scorer_side": ev.scorer_side,
                "score_a_before": ev.score_a_before,
                "score_b_before": ev.score_b_before,
                "score_a_after": ev.score_a_after,
                "score_b_after": ev.score_b_after,
                "games_a_before": ev.games_a_before,
                "games_b_before": ev.games_b_before,
                "games_a_after": ev.games_a_after,
                "games_b_after": ev.games_b_after,
                "game_target": ev.game_target,
                "best_of": ev.best_of,
                "is_game_winning_point": ev.is_game_winning_point,
                "is_match_winning_point": ev.is_match_winning_point,
                "timestamp": ev.timestamp,
                "source": ev.source,
                "server_id": ev.server_id,
                "rally_length": ev.rally_length,
                "end_reason": ev.end_reason,
                "shot_type": ev.shot_type,
                "placement": ev.placement,
                "notes": ev.notes,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            })
        return json.dumps(payload, indent=2)

    def to_csv(self, events: List[MatchPointEvent]) -> str:
        if not events:
            return ""
        buf = StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "id",
                "match_id",
                "game_index",
                "point_index",
                "scorer_side",
                "score_a_before",
                "score_b_before",
                "score_a_after",
                "score_b_after",
                "games_a_before",
                "games_b_before",
                "games_a_after",
                "games_b_after",
                "game_target",
                "best_of",
                "is_game_winning_point",
                "is_match_winning_point",
                "timestamp",
                "source",
                "server_id",
                "rally_length",
                "end_reason",
                "shot_type",
                "placement",
                "notes",
                "created_at",
            ],
        )
        writer.writeheader()
        for ev in events:
            writer.writerow({
                "id": ev.id,
                "match_id": ev.match_id,
                "game_index": ev.game_index,
                "point_index": ev.point_index,
                "scorer_side": ev.scorer_side,
                "score_a_before": ev.score_a_before,
                "score_b_before": ev.score_b_before,
                "score_a_after": ev.score_a_after,
                "score_b_after": ev.score_b_after,
                "games_a_before": ev.games_a_before,
                "games_b_before": ev.games_b_before,
                "games_a_after": ev.games_a_after,
                "games_b_after": ev.games_b_after,
                "game_target": ev.game_target,
                "best_of": ev.best_of,
                "is_game_winning_point": ev.is_game_winning_point,
                "is_match_winning_point": ev.is_match_winning_point,
                "timestamp": ev.timestamp,
                "source": ev.source,
                "server_id": ev.server_id,
                "rally_length": ev.rally_length,
                "end_reason": ev.end_reason,
                "shot_type": ev.shot_type,
                "placement": ev.placement,
                "notes": ev.notes,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            })
        return buf.getvalue()
