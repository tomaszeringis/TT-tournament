"""
Observability Service

Provides application metrics, health checks, and monitoring endpoints.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from collections import defaultdict
import time

from sqlalchemy.orm import Session

from tournament_platform.models import Match, Tournament, Player, AuditLog


class LatencyTracker:
    """Tracks latency metrics for operations."""

    def __init__(self):
        self._latencies: Dict[str, List[float]] = defaultdict(list)

    def record(self, operation: str, latency_ms: float) -> None:
        """Record a latency measurement."""
        self._latencies[operation].append(latency_ms)
        if len(self._latencies[operation]) > 1000:
            self._latencies[operation] = self._latencies[operation][-1000:]

    def get_p95(self, operation: str) -> Optional[float]:
        """Get p95 latency for an operation."""
        latencies = self._latencies.get(operation, [])
        if not latencies:
            return None
        sorted_latencies = sorted(latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    def get_stats(self, operation: str) -> Dict[str, Any]:
        """Get latency stats for an operation."""
        latencies = self._latencies.get(operation, [])
        if not latencies:
            return {"count": 0}
        return {
            "count": len(latencies),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "avg_ms": sum(latencies) / len(latencies),
            "p95_ms": self.get_p95(operation),
        }


_latency_tracker = LatencyTracker()


def get_latency_tracker() -> LatencyTracker:
    """Get the global latency tracker."""
    return _latency_tracker


class ObservabilityService:
    """Service for collecting and exposing application metrics."""

    def __init__(self, db: Session):
        self.db = db
        self._metrics: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "matches": {},
            "tournaments": {},
            "players": {},
            "system": {},
            "latency": {},
        }

    def collect_match_metrics(self, tournament_id: Optional[int] = None) -> Dict[str, Any]:
        """Collect match-related metrics."""
        start = time.perf_counter()
        query = self.db.query(Match)
        if tournament_id is not None:
            query = query.filter(Match.tournament_id == tournament_id)

        matches = query.all()
        elapsed_ms = (time.perf_counter() - start) * 1000
        _latency_tracker.record("db.query.matches", elapsed_ms)

        total = len(matches)
        completed = sum(1 for m in matches if m.status.value == "completed")
        active = sum(1 for m in matches if m.call_status == "active")
        called = sum(1 for m in matches if m.call_status == "called")
        pending = sum(1 for m in matches if m.status.value == "pending")
        delayed = sum(1 for m in matches if m.call_status == "delayed")

        self._metrics["matches"] = {
            "total": total,
            "completed": completed,
            "active": active,
            "called": called,
            "pending": pending,
            "delayed": delayed,
            "completion_rate": round(completed / total * 100, 1) if total > 0 else 0.0,
            "query_latency_ms": round(elapsed_ms, 2),
        }
        return self._metrics["matches"]

    def collect_tournament_metrics(self) -> Dict[str, Any]:
        """Collect tournament-related metrics."""
        start = time.perf_counter()
        tournaments = self.db.query(Tournament).all()
        elapsed_ms = (time.perf_counter() - start) * 1000
        _latency_tracker.record("db.query.tournaments", elapsed_ms)

        total = len(tournaments)
        with_matches = sum(1 for t in tournaments if t.matches)
        without_matches = total - with_matches

        self._metrics["tournaments"] = {
            "total": total,
            "with_matches": with_matches,
            "without_matches": without_matches,
            "query_latency_ms": round(elapsed_ms, 2),
        }
        return self._metrics["tournaments"]

    def collect_player_metrics(self) -> Dict[str, Any]:
        """Collect player-related metrics."""
        start = time.perf_counter()
        players = self.db.query(Player).all()
        elapsed_ms = (time.perf_counter() - start) * 1000
        _latency_tracker.record("db.query.players", elapsed_ms)

        total = len(players)

        self._metrics["players"] = {
            "total": total,
            "query_latency_ms": round(elapsed_ms, 2),
        }
        return self._metrics["players"]

    def collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system-level metrics."""
        start = time.perf_counter()
        audit_count = self.db.query(AuditLog).count()
        elapsed_ms = (time.perf_counter() - start) * 1000
        _latency_tracker.record("db.query.audit_logs", elapsed_ms)

        self._metrics["system"] = {
            "audit_log_entries": audit_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_latency_ms": round(elapsed_ms, 2),
        }
        return self._metrics["system"]

    def collect_latency_metrics(self) -> Dict[str, Any]:
        """Collect latency metrics."""
        latency_stats = {}
        for operation in ["db.query.matches", "db.query.tournaments", "db.query.players", "db.query.audit_logs"]:
            stats = _latency_tracker.get_stats(operation)
            if stats.get("count", 0) > 0:
                latency_stats[operation] = stats

        self._metrics["latency"] = latency_stats
        return self._metrics["latency"]

    def get_metrics(
        self, tournament_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get all metrics."""
        self.collect_match_metrics(tournament_id=tournament_id)
        self.collect_tournament_metrics()
        self.collect_player_metrics()
        self.collect_system_metrics()
        self.collect_latency_metrics()

        return {
            "matches": self._metrics["matches"],
            "tournaments": self._metrics["tournaments"],
            "players": self._metrics["players"],
            "system": self._metrics["system"],
            "latency": self._metrics["latency"],
        }

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of key metrics for quick display."""
        self.collect_match_metrics()
        self.collect_tournament_metrics()
        self.collect_player_metrics()
        self.collect_system_metrics()
        self.collect_latency_metrics()

        return {
            "total_matches": self._metrics["matches"].get("total", 0),
            "completed_matches": self._metrics["matches"].get("completed", 0),
            "active_matches": self._metrics["matches"].get("active", 0),
            "total_tournaments": self._metrics["tournaments"].get("total", 0),
            "total_players": self._metrics["players"].get("total", 0),
            "audit_entries": self._metrics["system"].get("audit_log_entries", 0),
            "latency": self._metrics["latency"],
        }
