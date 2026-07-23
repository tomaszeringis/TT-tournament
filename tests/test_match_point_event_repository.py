"""
Tests for MatchPointEventRepository persistence layer.
"""
import csv
import json

import pytest

from tournament_platform.models import Base, MatchPointEvent, engine
from tournament_platform.services.match_point_event_repository import MatchPointEventRepository


class TestMatchPointEventRepository:
    @pytest.fixture(autouse=True)
    def _setup_db(self):
        Base.metadata.create_all(bind=engine)
        from tournament_platform.models import SessionLocal
        db = SessionLocal()
        try:
            db.query(MatchPointEvent).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        yield
        db = SessionLocal()
        try:
            db.query(MatchPointEvent).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _make_repo(self):
        from tournament_platform.models import SessionLocal
        db = SessionLocal()
        repo = MatchPointEventRepository(db)
        return db, repo

    def test_create_and_list_by_match(self):
        db, repo = self._make_repo()
        try:
            ev = MatchPointEvent(
                match_id=1,
                game_index=0,
                point_index=0,
                scorer_side="A",
                score_a_before=0,
                score_b_before=0,
                score_a_after=1,
                score_b_after=0,
                games_a_before=0,
                games_b_before=0,
                games_a_after=0,
                games_b_after=0,
                game_target=11,
                best_of=5,
            )
            repo.create(ev)
            db.commit()
            results = repo.list_by_match(1)
            assert len(results) == 1
            assert results[0].scorer_side == "A"
        finally:
            db.close()

    def test_create_many(self):
        db, repo = self._make_repo()
        try:
            events = [
                MatchPointEvent(
                    match_id=1,
                    game_index=0,
                    point_index=i,
                    scorer_side="A" if i % 2 == 0 else "B",
                    score_a_before=i,
                    score_b_before=i,
                    score_a_after=i + 1,
                    score_b_after=i,
                    games_a_before=0,
                    games_b_before=0,
                    games_a_after=0,
                    games_b_after=0,
                    game_target=11,
                    best_of=5,
                )
                for i in range(3)
            ]
            repo.create_many(events)
            db.commit()
            results = repo.list_by_match(1)
            assert len(results) == 3
        finally:
            db.close()

    def test_delete_by_match(self):
        db, repo = self._make_repo()
        try:
            ev = MatchPointEvent(
                match_id=1,
                game_index=0,
                point_index=0,
                scorer_side="A",
                score_a_before=0,
                score_b_before=0,
                score_a_after=1,
                score_b_after=0,
                games_a_before=0,
                games_b_before=0,
                games_a_after=0,
                games_b_after=0,
                game_target=11,
                best_of=5,
            )
            repo.create(ev)
            db.commit()
            repo.delete_by_match(1)
            db.commit()
            results = repo.list_by_match(1)
            assert len(results) == 0
        finally:
            db.close()

    def test_to_json(self):
        db, repo = self._make_repo()
        try:
            ev = MatchPointEvent(
                match_id=1,
                game_index=0,
                point_index=0,
                scorer_side="A",
                score_a_before=0,
                score_b_before=0,
                score_a_after=1,
                score_b_after=0,
                games_a_before=0,
                games_b_before=0,
                games_a_after=0,
                games_b_after=0,
                game_target=11,
                best_of=5,
                notes="great serve",
            )
            repo.create(ev)
            db.commit()
            results = repo.list_by_match(1)
            payload = json.loads(repo.to_json(results))
            assert len(payload) == 1
            assert payload[0]["scorer_side"] == "A"
            assert payload[0]["notes"] == "great serve"
        finally:
            db.close()

    def test_to_csv(self):
        db, repo = self._make_repo()
        try:
            ev = MatchPointEvent(
                match_id=1,
                game_index=0,
                point_index=0,
                scorer_side="A",
                score_a_before=0,
                score_b_before=0,
                score_a_after=1,
                score_b_after=0,
                games_a_before=0,
                games_b_before=0,
                games_a_after=0,
                games_b_after=0,
                game_target=11,
                best_of=5,
                notes="csv test",
            )
            repo.create(ev)
            db.commit()
            results = repo.list_by_match(1)
            csv_text = repo.to_csv(results)
            reader = csv.DictReader(csv_text.splitlines())
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["scorer_side"] == "A"
            assert rows[0]["notes"] == "csv test"
        finally:
            db.close()
