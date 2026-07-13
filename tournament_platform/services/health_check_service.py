"""
Health Check Service

Provides readiness and liveness probes for deployment.
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tournament_platform.models import Tournament, Match, Player


class HealthStatus:
    """Health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


def check_database_health(db: Session) -> Dict[str, Any]:
    """
    Check database connectivity and basic query performance.

    Returns:
        Dict with database health status
    """
    try:
        start = datetime.now(timezone.utc)
        db.query(Tournament).limit(1).first()
        db.query(Player).limit(1).first()
        db.query(Match).limit(1).first()
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()

        return {
            "status": HealthStatus.HEALTHY if elapsed < 1.0 else HealthStatus.DEGRADED,
            "response_time_seconds": round(elapsed, 3),
            "details": "Database queries successful",
        }
    except Exception as e:
        return {
            "status": HealthStatus.UNHEALTHY,
            "response_time_seconds": None,
            "details": f"Database error: {str(e)}",
        }


def check_readiness(db: Session) -> Dict[str, Any]:
    """
    Check if the application is ready to serve traffic.

    A degraded state means the app can serve traffic but with reduced functionality.

    Returns:
        Dict with readiness status and details
    """
    checks = {
        "database": check_database_health(db),
    }

    overall_status = HealthStatus.HEALTHY
    for check_name, check_result in checks.items():
        if check_result["status"] == HealthStatus.UNHEALTHY:
            overall_status = HealthStatus.UNHEALTHY
            break
        elif check_result["status"] == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
            overall_status = HealthStatus.DEGRADED

    return {
        "status": overall_status,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def check_liveness(db: Session) -> Dict[str, Any]:
    """
    Check if the application is alive and responding.

    This is a lightweight check that doesn't hit the database.

    Returns:
        Dict with liveness status
    """
    return {
        "status": HealthStatus.HEALTHY,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": "Application is alive",
    }


def get_health_summary(db: Session) -> Dict[str, Any]:
    """
    Get a comprehensive health summary.

    Returns:
        Dict with readiness and liveness status
    """
    readiness = check_readiness(db)
    liveness = check_liveness(db)

    return {
        "readiness": readiness,
        "liveness": liveness,
        "overall_status": readiness["status"],
    }
