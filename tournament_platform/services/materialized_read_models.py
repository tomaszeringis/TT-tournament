"""
Materialized Read Models

Pre-computed read models for expensive queries. These are refreshed
on-demand and cached to reduce database load.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from collections import defaultdict
import time

from sqlalchemy.orm import Session

from tournament_platform.models import Match, Tournament, Player, MatchStatus


class MaterializedReadModels:
    """Materialized read models for expensive queries."""

    def __init__(self, db: Session):
        self.db = db
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl = 30  # seconds

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache entry is still valid."""
        if key not in self._cache_timestamps:
            return False
        age = time.time() - self._cache_timestamps[key]
        return age < self._cache_ttl

    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate cache entries."""
        if key:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()

    def get_dashboard_summary(self, tournament_id: Optional[int] = None) -> Dict[str, Any]:
        """Get dashboard summary with materialized counts."""
        cache_key = f"dashboard_summary_{tournament_id}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        match_query = self.db.query(Match)
        player_query = self.db.query(Player)
        if tournament_id is not None:
            match_query = match_query.filter(Match.tournament_id == tournament_id)

        total_players = player_query.count()
        total_matches = match_query.count()
        completed_matches = match_query.filter(Match.status == MatchStatus.completed).count()
        active_matches = match_query.filter(Match.call_status == "active").count()

        result = {
            "total_players": total_players,
            "total_matches": total_matches,
            "completed_matches": completed_matches,
            "active_matches": active_matches,
            "completion_rate": round(completed_matches / total_matches * 100, 1) if total_matches > 0 else 0.0,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        self._cache[cache_key] = result
        self._cache_timestamps[cache_key] = time.time()
        return result

    def get_tournament_list(self) -> List[Dict[str, Any]]:
        """Get tournament list with match counts."""
        cache_key = "tournament_list"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        tournaments = self.db.query(Tournament).order_by(Tournament.name.asc()).all()
        result = [
            {
                "id": t.id,
                "name": t.name,
                "type": t.tournament_type.value if t.tournament_type else "knockout",
                "match_count": len(t.matches),
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tournaments
        ]

        self._cache[cache_key] = result
        self._cache_timestamps[cache_key] = time.time()
        return result

    def get_operator_queue(self, tournament_id: int) -> List[Dict[str, Any]]:
        """Get operator queue with match details."""
        cache_key = f"operator_queue_{tournament_id}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        matches = self.db.query(Match).filter(
            Match.tournament_id == tournament_id
        ).order_by(Match.scheduled_time.asc(), Match.round_number.asc()).all()

        result = []
        for m in matches:
            conflict_flags = []
            if not m.location:
                conflict_flags.append("missing_table")
            if not m.scheduled_time:
                conflict_flags.append("missing_scheduled_time")

            result.append({
                "id": m.id,
                "player1": m.player1,
                "player2": m.player2,
                "status": m.status.value if m.status else "pending",
                "call_status": m.call_status or "not_called",
                "scheduled_time": m.scheduled_time.isoformat() if m.scheduled_time else None,
                "location": m.location,
                "round_number": m.round_number,
                "conflict_flags": conflict_flags,
            })

        self._cache[cache_key] = result
        self._cache_timestamps[cache_key] = time.time()
        return result

    def get_standings(self, tournament_id: int) -> List[Dict[str, Any]]:
        """Get standings with materialized player stats."""
        cache_key = f"standings_{tournament_id}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        matches = self.db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status == MatchStatus.completed,
        ).all()

        players = self.db.query(Player).all()
        player_map = {p.id: p for p in players}

        stats = {}
        for p in players:
            stats[p.id] = {
                "player_id": p.id,
                "name": p.name,
                "rating": p.rating,
                "wins": 0,
                "losses": 0,
                "matches_played": 0,
            }

        for m in matches:
            p1_id = m.player1_id
            p2_id = m.player2_id
            if not p1_id or not p2_id:
                continue

            if p1_id in stats:
                stats[p1_id]["matches_played"] += 1
                if m.winner_id == p1_id:
                    stats[p1_id]["wins"] += 1
                else:
                    stats[p1_id]["losses"] += 1

            if p2_id in stats:
                stats[p2_id]["matches_played"] += 1
                if m.winner_id == p2_id:
                    stats[p2_id]["wins"] += 1
                else:
                    stats[p2_id]["losses"] += 1

        standings = sorted(
            stats.values(),
            key=lambda s: (-s["wins"], s["matches_played"], s["name"]),
        )

        self._cache[cache_key] = standings
        self._cache_timestamps[cache_key] = time.time()
        return standings
