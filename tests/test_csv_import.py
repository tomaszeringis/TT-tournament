"""
Tests for CSV bulk import (Phase 2): parse, validate, duplicate detection,
transactional commit with rollback on error.
"""

import pytest

from tournament_platform.app.components.csv_import_panel import (
    parse_csv_text,
    validate_rows,
    partition_rows,
    commit_rows,
)
from tournament_platform.models import SessionLocal, Player, init_db


VALID_CSV = "name,email,rating\nAlice,alice@example.com,1300\nBob,bob@example.com,1200\n"


class TestCsvParsing:
    def test_parse_valid_csv(self):
        rows = parse_csv_text(VALID_CSV)
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert rows[0]["email"] == "alice@example.com"
        assert rows[0]["rating_raw"] == "1300"

    def test_parse_blank_rows(self):
        rows = parse_csv_text("name,email\n\n")
        assert all(r["name"] == "" and r["email"] == "" for r in rows)

    def test_parse_missing_header(self):
        # csv.DictReader treats the first row as the header when none is given,
        # so a headerless file yields no data rows. The UI requires a header.
        rows = parse_csv_text("Alice,alice@example.com")
        assert rows == []


class TestCsvValidation:
    def test_valid_rows_have_no_errors(self):
        rows = parse_csv_text(VALID_CSV)
        results = validate_rows(rows, existing_players=[])
        assert all(not r["errors"] for r in results)
        assert all(r["rating"] in (1300, 1200) for r in results)

    def test_missing_name_and_email_flagged(self):
        rows = parse_csv_text("name,email\n,alice@example.com\nBob,\n")
        results = validate_rows(rows, existing_players=[])
        assert "Missing name" in results[0]["errors"]
        assert "Missing email" in results[1]["errors"]

    def test_bad_rating_flagged(self):
        rows = parse_csv_text("name,email,rating\nAlice,alice@example.com,abc\n")
        results = validate_rows(rows, existing_players=[])
        assert "Rating must be an integer" in results[0]["errors"]

    def test_duplicate_within_file_flagged(self):
        csv = "name,email\nAlice,a@x.com\nAlice,a@x.com\n"
        rows = parse_csv_text(csv)
        results = validate_rows(rows, existing_players=[])
        assert results[1]["duplicate_intra"] == "name"

    def test_duplicate_against_existing_flagged(self):
        rows = parse_csv_text("name,email\nAlice,alice@example.com\n")
        results = validate_rows(
            rows, existing_players=[{"name": "Alice", "email": "alice@example.com"}]
        )
        assert results[0]["duplicate_existing"] == "name"

    def test_partition_skips_invalid_and_duplicates(self):
        csv = (
            "name,email,rating\n"
            "Alice,alice@example.com,1200\n"
            ",bob@example.com,1200\n"
            "Alice,alice@example.com,1200\n"
        )
        rows = parse_csv_text(csv)
        results = validate_rows(rows, existing_players=[])
        importable, skipped = partition_rows(results)
        assert len(importable) == 1
        assert len(skipped) == 2


class TestCsvCommit:
    def test_commit_writes_approved_rows(self):
        init_db()
        db = SessionLocal()
        try:
            for nm in ("CSVTestA", "CSVTestB"):
                p = db.query(Player).filter(Player.name == nm).first()
                if p:
                    db.delete(p)
            db.commit()

            rows = parse_csv_text("name,email,rating\nCSVTestA,a@csv.test,1250\nCSVTestB,b@csv.test,1150\n")
            results = validate_rows(rows, existing_players=[])
            importable, _ = partition_rows(results)
            created, errors = commit_rows(importable, db)
            assert errors == []
            assert created == 2
            assert db.query(Player).filter(Player.name == "CSVTestA").first() is not None
        finally:
            db.rollback()
            db.close()

    def test_commit_rollback_on_duplicate_name(self):
        init_db()
        db = SessionLocal()
        try:
            if not db.query(Player).filter(Player.name == "CSVPre").first():
                db.add(Player(name="CSVPre", email="pre@csv.test", rating=1200))
                db.commit()

            rows = parse_csv_text("name,email\nCSVPre,pre@csv.test\n")
            results = validate_rows(rows, existing_players=[])
            importable, _ = partition_rows(results)
            created, errors = commit_rows(importable, db)
            assert created == 0
            assert errors
        finally:
            p = db.query(Player).filter(Player.name == "CSVPre").first()
            if p:
                db.delete(p)
                db.commit()
            db.close()
