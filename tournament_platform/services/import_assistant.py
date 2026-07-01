"""
Import Assistant - Excel/CSV import with dry-run validation.

This service provides:
- Column mapping suggestions
- Data validation
- Preview before commit
- Transactional import with audit
"""

from typing import Optional, List, Dict, Any
import logging
import base64
import io

import pandas as pd

from sqlalchemy.orm import Session

from tournament_platform.models import Player, Tournament, Match, VenueTable
from tournament_platform.services.audit_service import log_audit

logger = logging.getLogger(__name__)


# Supported entity types
SUPPORTED_ENTITIES = ["players", "tournaments", "matches", "venue_tables"]

# Default column mappings for each entity type
DEFAULT_COLUMN_MAPPINGS = {
    "players": {
        "name": "name",
        "email": "email",
        "rating": "rating",
    },
    "tournaments": {
        "name": "name",
        "type": "type",
        "start_date": "start_date",
    },
    "matches": {
        "player1": "player1",
        "player2": "player2",
        "scheduled_time": "scheduled_time",
        "location": "location",
    },
    "venue_tables": {
        "name": "name",
        "is_active": "is_active",
    },
}


def detect_file_type(file_data: bytes) -> str:
    """
    Detect if file is Excel or CSV based on content.
    
    Returns:
        "excel" or "csv"
    """
    # Check for Excel magic bytes
    if file_data[:4] == b"PK\x03\x04" or file_data[:2] == b"\xd0\xcf":
        return "excel"
    
    # Try to decode as CSV
    try:
        text = file_data.decode("utf-8")
        if "," in text.split("\n")[0] or "\t" in text.split("\n")[0]:
            return "csv"
    except UnicodeDecodeError:
        pass
    
    return "unknown"


def load_file_data(file_data: bytes, file_type: str) -> pd.DataFrame:
    """
    Load file data into a pandas DataFrame.
    
    Args:
        file_data: Raw file bytes
        file_type: "excel" or "csv"
        
    Returns:
        DataFrame with file data
    """
    if file_type == "excel":
        return pd.read_excel(io.BytesIO(file_data))
    else:
        return pd.read_csv(io.StringIO(file_data.decode("utf-8")))


def suggest_column_mapping(
    df: pd.DataFrame,
    entity_type: str,
) -> Dict[str, str]:
    """
    Suggest column mappings based on DataFrame columns.
    
    Args:
        df: DataFrame with file data
        entity_type: Type of entity to import
        
    Returns:
        Dict mapping file columns to entity fields
    """
    if entity_type not in DEFAULT_COLUMN_MAPPINGS:
        return {}
    
    suggestions = {}
    file_columns = [c.lower().strip() for c in df.columns]
    
    for field, default in DEFAULT_COLUMN_MAPPINGS[entity_type].items():
        # Look for exact match
        for col in df.columns:
            if col.lower().strip() == field:
                suggestions[field] = col
                break
        else:
            # Use default if no match found
            suggestions[field] = default
    
    return suggestions


def validate_import_data(
    df: pd.DataFrame,
    entity_type: str,
    column_mapping: Dict[str, str],
) -> Dict[str, Any]:
    """
    Validate import data and return any errors or warnings.
    
    Args:
        df: DataFrame with file data
        entity_type: Type of entity to import
        column_mapping: Column mapping to use
        
    Returns:
        Dict with valid flag, errors, warnings, and sample data
    """
    errors = []
    warnings = []
    
    if entity_type not in SUPPORTED_ENTITIES:
        return {
            "valid": False,
            "errors": [f"Unknown entity type: {entity_type}"],
            "warnings": [],
        }
    
    # Check required columns
    required = list(DEFAULT_COLUMN_MAPPINGS[entity_type].keys())
    for field in required:
        mapped_col = column_mapping.get(field)
        if mapped_col and mapped_col not in df.columns:
            errors.append(f"Missing required column for '{field}'")
    
    # Get sample data
    sample_data = df.head(5).to_dict("records")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "sample_data": sample_data,
    }


def preview_import(
    db: Session,
    entity_type: str,
    df: pd.DataFrame,
    column_mapping: Dict[str, str],
) -> Dict[str, Any]:
    """
    Preview an import operation without writing to the database.
    
    Args:
        db: Database session
        entity_type: Type of entity to import
        df: DataFrame with file data
        column_mapping: Column mapping to use
        
    Returns:
        Dict with preview data
    """
    validation = validate_import_data(df, entity_type, column_mapping)
    
    if not validation["valid"]:
        return {
            "success": False,
            "errors": validation["errors"],
        }
    
    # Count rows to add
    rows_to_add = len(df)
    
    # Check for potential duplicate players
    if entity_type == "players":
        for _, row in df.iterrows():
            name = row.get(column_mapping.get("name", "name"))
            if name:
                existing = db.query(Player).filter(Player.name == name).first()
                if existing:
                    validation["warnings"].append(f"Player '{name}' may already exist")
    
    return {
        "success": True,
        "entity_type": entity_type,
        "rows_to_add": rows_to_add,
        "warnings": validation["warnings"],
        "sample_data": validation["sample_data"],
    }


def commit_import(
    db: Session,
    entity_type: str,
    df: pd.DataFrame,
    column_mapping: Dict[str, str],
    actor: str = "import",
) -> Dict[str, Any]:
    """
    Commit an import operation to the database.
    
    This is a transactional operation that:
    1. Validates data
    2. Inserts records
    3. Logs audit entry
    4. Commits or rolls back on error
    
    Args:
        db: Database session
        entity_type: Type of entity to import
        df: DataFrame with file data
        column_mapping: Column mapping to use
        actor: Who performed the import
        
    Returns:
        Dict with result status
    """
    validation = validate_import_data(df, entity_type, column_mapping)
    
    if not validation["valid"]:
        return {
            "success": False,
            "errors": validation["errors"],
        }
    
    try:
        rows_added = 0
        
        if entity_type == "players":
            for _, row in df.iterrows():
                player = Player(
                    name=row.get(column_mapping.get("name", "name")),
                    email=row.get(column_mapping.get("email", "email")),
                    rating=int(row.get(column_mapping.get("rating", "rating"), 1000)),
                )
                db.add(player)
                rows_added += 1
        
        elif entity_type == "tournaments":
            for _, row in df.iterrows():
                tournament = Tournament(
                    name=row.get(column_mapping.get("name", "name")),
                    type=row.get(column_mapping.get("type", "type"), "single_elimination"),
                )
                db.add(tournament)
                rows_added += 1
        
        elif entity_type == "venue_tables":
            for _, row in df.iterrows():
                table = VenueTable(
                    name=row.get(column_mapping.get("name", "name")),
                    is_active=bool(row.get(column_mapping.get("is_active", "is_active"), True)),
                )
                db.add(table)
                rows_added += 1
        
        db.commit()
        
        # Log audit
        log_audit(
            db,
            action="import_data",
            entity_type=entity_type,
            actor=actor,
            payload={
                "rows_added": rows_added,
                "file_columns": list(df.columns),
            },
        )
        
        return {
            "success": True,
            "rows_added": rows_added,
            "audit_summary": f"Imported {rows_added} {entity_type}",
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during import: {e}")
        return {
            "success": False,
            "error": str(e),
        }