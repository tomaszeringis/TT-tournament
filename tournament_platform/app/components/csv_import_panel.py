"""
CSV Import Panel — bulk participant onboarding with preview, validation, and
duplicate detection.

Pure functions (``parse_csv_text``, ``validate_rows``, ``commit_rows``) are kept
free of Streamlit so they can be unit-tested in isolation. The Streamlit UI
(``render_csv_import_panel``) wraps them and reuses the existing duplicate
detection philosophy (exact name/email + intra-file checks).

The entire write loop is wrapped in a single transaction: if any committed row
fails, the whole import is rolled back (no partial imports).
"""

import csv
import io
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Pure parsing / validation (no Streamlit, no DB)
# ---------------------------------------------------------------------------

def parse_csv_text(raw_text: str) -> List[Dict]:
    """Parse CSV text into raw row dicts (one entry per data line).

    Raises ``ValueError`` if the CSV cannot be read.
    """
    reader = csv.DictReader(io.StringIO(raw_text))
    rows = []
    for line_no, row in enumerate(reader, start=2):  # line 1 is the header
        name = (row.get("name") or row.get("Name") or "").strip()
        email = (row.get("email") or row.get("Email") or "").strip()
        rating_raw = (row.get("rating") or row.get("Rating") or "").strip()
        rows.append({"line": line_no, "name": name, "email": email, "rating_raw": rating_raw})
    return rows


def validate_rows(
    rows: List[Dict],
    existing_players: List[Dict],
) -> List[Dict]:
    """Validate parsed rows and flag duplicates.

    Args:
        rows: output of ``parse_csv_text``.
        existing_players: list of ``{"name": ..., "email": ...}`` from the DB.

    Returns:
        List of enriched dicts with keys: ``line``, ``name``, ``email``,
        ``rating`` (int or None), ``errors`` (list), ``warnings`` (list),
        ``duplicate_existing`` ("name"/"email"/None),
        ``duplicate_intra`` ("name"/"email"/None).
    """
    seen_names: Dict[str, bool] = {}
    seen_emails: Dict[str, bool] = {}
    results: List[Dict] = []

    for r in rows:
        errors: List[str] = []
        warnings: List[str] = []
        name = r["name"]
        email = r["email"]
        rating: Optional[int] = None

        if not name:
            errors.append("Missing name")
        if not email:
            errors.append("Missing email")
        elif "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Invalid email format")

        if r["rating_raw"]:
            try:
                rating = int(r["rating_raw"])
                if rating < 0:
                    errors.append("Rating must be non-negative")
            except ValueError:
                errors.append("Rating must be an integer")

        duplicate_existing = None
        if name and any(p["name"] and p["name"].lower() == name.lower() for p in existing_players):
            duplicate_existing = "name"
        elif email and any(
            p["email"] and p["email"].lower() == email.lower() for p in existing_players
        ):
            duplicate_existing = "email"

        duplicate_intra = None
        key_n = name.lower() if name else None
        key_e = email.lower() if email else None
        if key_n in seen_names:
            duplicate_intra = "name"
        elif key_e and key_e in seen_emails:
            duplicate_intra = "email"
        if key_n:
            seen_names[key_n] = True
        if key_e:
            seen_emails[key_e] = True

        results.append({
            "line": r["line"],
            "name": name,
            "email": email,
            "rating": rating,
            "errors": errors,
            "warnings": warnings,
            "duplicate_existing": duplicate_existing,
            "duplicate_intra": duplicate_intra,
        })

    return results


def partition_rows(results: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Split validated rows into (importable, skipped).

    Importable = no errors and not an intra-file or existing duplicate.
    """
    importable = []
    skipped = []
    for r in results:
        if r["errors"]:
            skipped.append(r)
            continue
        if r["duplicate_existing"] or r["duplicate_intra"]:
            skipped.append(r)
            continue
        importable.append(r)
    return importable, skipped


# ---------------------------------------------------------------------------
# DB commit (transactional)
# ---------------------------------------------------------------------------

def commit_rows(
    importable: List[Dict],
    db,
    default_rating: int = 1200,
    import_source: str = "import",
    registration_status: str = "approved",
) -> Tuple[int, List[str]]:
    """Insert importable rows inside a single transaction.

    Returns ``(created_count, errors)``. On any DB error the transaction is
    rolled back and ``created_count`` is 0.
    """
    from tournament_platform.models import Player

    errors: List[str] = []
    created = 0
    try:
        for r in importable:
            player = Player(
                name=r["name"],
                email=r["email"],
                rating=r["rating"] if r["rating"] is not None else default_rating,
                import_source=import_source,
                registration_status=registration_status,
            )
            db.add(player)
        db.commit()
        created = len(importable)
    except Exception as e:
        db.rollback()
        errors.append(str(e))
    return created, errors


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def render_csv_import_panel() -> None:
    """Render the CSV bulk-import panel (upload, preview, validate, commit)."""
    import streamlit as st
    from tournament_platform.models import SessionLocal, Player
    from tournament_platform.config import settings

    st.subheader("📥 CSV Bulk Import")

    uploaded = st.file_uploader(
        "Upload a CSV (columns: name, email, rating?)",
        type=["csv"],
        key="csv_import_uploader",
    )

    if not uploaded:
        st.caption("Tip: include a header row with at least `name` and `email`.")
        return

    raw_text = uploaded.getvalue().decode("utf-8", errors="replace")

    try:
        rows = parse_csv_text(raw_text)
    except Exception as e:
        st.error(f"Could not parse CSV: {e}")
        return

    if not rows:
        st.warning("No data rows found in the CSV.")
        return

    db = SessionLocal()
    try:
        existing = [
            {"name": p.name, "email": p.email}
            for p in db.query(Player).all()
        ]
    finally:
        db.close()

    results = validate_rows(rows, existing)
    importable, skipped = partition_rows(results)

    # Build preview table
    preview = []
    for r in results:
        notes = []
        if r["errors"]:
            notes.append("; ".join(r["errors"]))
        if r["duplicate_existing"]:
            notes.append(f"Duplicate {r['duplicate_existing']} (already in database)")
        if r["duplicate_intra"]:
            notes.append(f"Duplicate {r['duplicate_intra']} (within file)")
        preview.append({
            "Line": r["line"],
            "Name": r["name"],
            "Email": r["email"],
            "Rating": r["rating"] if r["rating"] is not None else "",
            "Status": "Skip" if r in skipped else "Import",
            "Notes": "; ".join(notes),
        })

    st.dataframe(preview, use_container_width=True, hide_index=True)

    st.caption(f"Will import **{len(importable)}** players; **{len(skipped)}** will be skipped.")

    if importable and st.button("📥 Import Players", type="primary", key="csv_import_confirm"):
        db = SessionLocal()
        try:
            created, errors = commit_rows(
                importable,
                db,
                default_rating=settings.DEFAULT_PLAYER_RATING,
                import_source="import",
                registration_status="approved",
            )
            if errors:
                for err in errors:
                    st.error(f"Import failed: {err}")
            else:
                st.toast(f"Imported {created} player(s)!", icon="✅")
                st.cache_data.clear()
                st.rerun()
        finally:
            db.close()
