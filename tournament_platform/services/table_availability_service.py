"""
Table availability service for managing venue table active/inactive status.

This service provides functions to:
- Get a summary of table availability
- Set the maximum number of available tables
- Create missing venue tables if needed
"""

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from tournament_platform.models import VenueTable, Match, AuditLog
from tournament_platform.services.audit_service import log_audit

logger = logging.getLogger(__name__)


def get_table_availability_summary(
    db: Session,
    tournament_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Return a summary of table availability.

    Returns:
        Dict with:
        - total_tables: count of all venue tables
        - active_tables: count of active venue tables
        - inactive_tables: count of inactive venue tables
        - max_available_tables: the configured max (or None if not set)
        - tables: list of table summaries with:
            - id
            - name
            - is_active
            - notes
            - current_match_id (if active/called match is on the table)
            - current_match_label (if available)
            - has_active_or_called_match: boolean
    """
    # Get all tables ordered by name
    tables = db.query(VenueTable).order_by(VenueTable.name.asc()).all()

    # Get active/called matches for busy table detection
    query = db.query(Match).filter(Match.call_status.in_(["active", "called"]))
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)

    active_matches = query.all()
    busy_table_names = {m.location for m in active_matches if m.location}

    # Build table summaries
    table_summaries = []
    for table in tables:
        # Find current match on this table
        current_match = None
        for m in active_matches:
            if m.location == table.name:
                current_match = m
                break

        # Build match label
        match_label = None
        if current_match:
            label_parts = []
            if current_match.player1 and current_match.player2:
                label_parts.append(f"{current_match.player1} vs {current_match.player2}")
            if current_match.round_number:
                label_parts.append(f"Round {current_match.round_number}")
            match_label = " · ".join(label_parts) if label_parts else f"Match {current_match.id}"

        table_summaries.append({
            "id": table.id,
            "name": table.name,
            "is_active": bool(table.is_active),
            "notes": table.notes,
            "current_match_id": current_match.id if current_match else None,
            "current_match_label": match_label,
            "has_active_or_called_match": table.name in busy_table_names,
        })

    # Count active/inactive
    active_count = sum(1 for t in table_summaries if t["is_active"])
    inactive_count = len(table_summaries) - active_count

    return {
        "total_tables": len(tables),
        "active_tables": active_count,
        "inactive_tables": inactive_count,
        "max_available_tables": None,  # Not stored separately, derived from active count
        "tables": table_summaries,
    }


def set_max_available_tables(
    db: Session,
    max_tables: int,
    tournament_id: Optional[int] = None,
    actor: str = "operator",
    prefer_keep_busy_tables_active: bool = True,
) -> Dict[str, Any]:
    """
    Set the maximum number of available/active tables.

    Behavior:
    - Validates max_tables >= 0
    - Activates up to max_tables tables
    - Deactivates tables beyond max_tables
    - If prefer_keep_busy_tables_active=True, tables with active/called matches
      stay active whenever possible
    - Does NOT change Match.location
    - Commits changes in one transaction, rolls back on error

    Args:
        db: Database session
        max_tables: Maximum number of tables to keep active
        tournament_id: Optional tournament filter (for busy table detection)
        actor: Who performed the action (default: "operator")
        prefer_keep_busy_tables_active: Keep busy tables active if possible

    Returns:
        Dict with:
        - requested_max_tables: the input value
        - resulting_active_tables: actual count after operation
        - updated_tables: count of tables that changed state
        - warnings: list of warning messages
        - table_summaries: updated table summaries
    """
    warnings = []
    updated_table_ids = []

    # Validate max_tables
    if max_tables < 0:
        return {
            "requested_max_tables": max_tables,
            "resulting_active_tables": 0,
            "updated_tables": 0,
            "warnings": ["max_tables must be >= 0"],
            "table_summaries": [],
        }

    # Get all tables ordered by name
    all_tables = db.query(VenueTable).order_by(VenueTable.name.asc()).all()

    if not all_tables:
        return {
            "requested_max_tables": max_tables,
            "resulting_active_tables": 0,
            "updated_tables": 0,
            "warnings": ["No venue tables exist. Create tables first."],
            "table_summaries": [],
        }

    # Check if max_tables exceeds total
    if max_tables > len(all_tables):
        warnings.append(
            f"Requested {max_tables} available tables, but only {len(all_tables)} venue tables exist."
        )

    # Get busy tables (tables with active/called matches)
    query = db.query(Match).filter(Match.call_status.in_(["active", "called"]))
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)

    active_matches = query.all()
    busy_table_names = {m.location for m in active_matches if m.location}

    # If prefer_keep_busy_tables_active, check if busy count exceeds max
    if prefer_keep_busy_tables_active and len(busy_table_names) > max_tables:
        warnings.append(
            f"There are {len(busy_table_names)} busy tables, so active table count exceeds requested max of {max_tables}."
        )

    try:
        # Determine which tables should be active
        # Priority: busy tables first, then by name order
        busy_tables = [t for t in all_tables if t.name in busy_table_names]
        free_tables = [t for t in all_tables if t.name not in busy_table_names]

        # Tables to activate: busy tables + enough free tables to reach max
        tables_to_activate = set(t.id for t in busy_tables)
        remaining_slots = max_tables - len(busy_tables)

        for t in free_tables:
            if remaining_slots <= 0:
                break
            tables_to_activate.add(t.id)
            remaining_slots -= 1

        # Update table states
        for table in all_tables:
            should_be_active = table.id in tables_to_activate
            is_currently_active = bool(table.is_active)

            if should_be_active and not is_currently_active:
                table.is_active = 1
                updated_table_ids.append(table.id)
            elif not should_be_active and is_currently_active:
                # Don't deactivate if it has a busy match and prefer_keep_busy_tables_active
                if prefer_keep_busy_tables_active and table.name in busy_table_names:
                    # Keep it active, but don't add to updated_table_ids
                    pass
                else:
                    table.is_active = 0
                    updated_table_ids.append(table.id)

        db.commit()

        # Get updated summary
        summary = get_table_availability_summary(db, tournament_id=tournament_id)

        # Log audit
        log_audit(
            db,
            action="set_max_available_tables",
            entity_type="venue_table",
            actor=actor,
            payload={
                "requested_max": max_tables,
                "resulting_active_count": summary["active_tables"],
                "tournament_id": tournament_id,
                "warnings": warnings,
                "changed_table_ids": updated_table_ids,
            }
        )

        return {
            "requested_max_tables": max_tables,
            "resulting_active_tables": summary["active_tables"],
            "updated_tables": len(updated_table_ids),
            "warnings": warnings,
            "table_summaries": summary["tables"],
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error setting max available tables: {e}", exc_info=True)
        return {
            "requested_max_tables": max_tables,
            "resulting_active_tables": 0,
            "updated_tables": 0,
            "warnings": [f"Error: {str(e)}"],
            "table_summaries": [],
        }


def ensure_minimum_venue_tables(
    db: Session,
    count: int,
    actor: str = "operator"
) -> Dict[str, Any]:
    """
    Create missing VenueTable rows to ensure at least 'count' tables exist.

    Creates tables named "Table 1", "Table 2", etc.
    Does not duplicate existing names.

    Args:
        db: Database session
        count: Minimum number of tables to have
        actor: Who performed the action (default: "operator")

    Returns:
        Dict with:
        - requested_count: the input value
        - created_tables: number of tables created
        - table_names: list of created table names
    """
    if count < 0:
        return {
            "requested_count": count,
            "created_tables": 0,
            "table_names": [],
            "warnings": ["count must be >= 0"],
        }

    # Get existing table names
    existing_tables = db.query(VenueTable).all()
    existing_names = {t.name for t in existing_tables}

    # Find how many we need to create
    created_names = []
    created_count = 0

    for i in range(1, count + 1):
        table_name = f"Table {i}"
        if table_name not in existing_names:
            new_table = VenueTable(name=table_name, is_active=1)
            db.add(new_table)
            created_names.append(table_name)
            created_count += 1

    if created_count > 0:
        try:
            db.commit()

            # Log audit
            log_audit(
                db,
                action="ensure_minimum_venue_tables",
                entity_type="venue_table",
                actor=actor,
                payload={
                    "requested_count": count,
                    "created_count": created_count,
                    "created_table_names": created_names,
                }
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating venue tables: {e}", exc_info=True)
            return {
                "requested_count": count,
                "created_tables": 0,
                "table_names": [],
                "warnings": [f"Error: {str(e)}"],
            }

    return {
        "requested_count": count,
        "created_tables": created_count,
        "table_names": created_names,
    }