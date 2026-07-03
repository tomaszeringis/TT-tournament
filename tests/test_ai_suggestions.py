"""
Tests for AI Tournament Suggestions Service.
"""

import pytest
import time
from tournament_platform.models import SessionLocal, Player, Match, Tournament, init_db, MatchStatus
from tournament_platform.services.ai_tournament_suggestions import suggest_seeding, suggest_schedule, detect_anomalies


def _unique_name(base: str) -> str:
    """Generate a unique name using timestamp to avoid database conflicts."""
    return f"{base}_{int(time.time() * 1000000)}"


class TestSuggestSeeding:
    """Test seeding suggestions."""

    def test_suggest_seeding_no_tournament(self):
        """Test seeding with non-existent tournament."""
        db = SessionLocal()
        try:
            result = suggest_seeding(99999, db)
            assert result == []
        finally:
            db.close()

    def test_suggest_seeding_no_matches(self):
        """Test seeding with tournament that has no matches."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("seeding")
            tournament = Tournament(name=f"Seeding Test {ts}")
            db.add(tournament)
            db.commit()
            
            result = suggest_seeding(tournament.id, db)
            assert result == []
            
            db.delete(tournament)
            db.commit()
        finally:
            db.close()

    def test_suggest_seeding_with_players(self):
        """Test seeding with players of different ratings."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("seeding_players")
            
            # Create players with different ratings
            p1 = Player(name=f"Seed{ts}P1", rating=1200)
            p2 = Player(name=f"Seed{ts}P2", rating=1000)
            p3 = Player(name=f"Seed{ts}P3", rating=1100)
            db.add_all([p1, p2, p3])
            db.commit()
            
            # Create tournament with matches
            tournament = Tournament(name=f"Seeding Test {ts}")
            db.add(tournament)
            db.flush()
            
            # Create matches to register players
            match1 = Match(
                player1=p1.name, player2=p2.name,
                player1_id=p1.id, player2_id=p2.id,
                tournament_id=tournament.id,
                status=MatchStatus.pending
            )
            match2 = Match(
                player1=p1.name, player2=p3.name,
                player1_id=p1.id, player2_id=p3.id,
                tournament_id=tournament.id,
                status=MatchStatus.pending
            )
            db.add_all([match1, match2])
            db.commit()
            
            result = suggest_seeding(tournament.id, db)
            
            # Should return 3 players
            assert len(result) == 3
            
            # P1 (rating 1200) should be seed 1
            # P3 (rating 1100) should be seed 2
            # P2 (rating 1000) should be seed 3
            assert result[0][0] == p1.name
            assert result[0][1] == 1
            assert result[1][0] == p3.name
            assert result[1][1] == 2
            assert result[2][0] == p2.name
            assert result[2][1] == 3
            
            # Cleanup
            for m in [match1, match2]:
                db.delete(m)
            db.delete(tournament)
            for p in [p1, p2, p3]:
                db.delete(p)
            db.commit()
        finally:
            db.close()


class TestSuggestSchedule:
    """Test schedule suggestions."""

    def test_suggest_schedule_no_tournament(self):
        """Test schedule with non-existent tournament."""
        db = SessionLocal()
        try:
            result = suggest_schedule(99999, db)
            assert result == []
        finally:
            db.close()

    def test_suggest_schedule_no_pending_matches(self):
        """Test schedule with no pending matches."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("schedule")
            tournament = Tournament(name=f"Schedule Test {ts}")
            db.add(tournament)
            db.commit()
            
            result = suggest_schedule(tournament.id, db)
            assert result == []
            
            db.delete(tournament)
            db.commit()
        finally:
            db.close()

    def test_suggest_schedule_with_matches(self):
        """Test schedule with pending matches."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("schedule_matches")
            
            # Create players
            p1 = Player(name=f"Sched{ts}P1")
            p2 = Player(name=f"Sched{ts}P2")
            db.add_all([p1, p2])
            db.commit()
            
            # Create tournament with pending matches
            tournament = Tournament(name=f"Schedule Test {ts}")
            db.add(tournament)
            db.flush()
            
            match1 = Match(
                player1=p1.name, player2=p2.name,
                player1_id=p1.id, player2_id=p2.id,
                tournament_id=tournament.id,
                status=MatchStatus.pending,
                round_number=1
            )
            match2 = Match(
                player1=p1.name, player2=p2.name,
                player1_id=p1.id, player2_id=p2.id,
                tournament_id=tournament.id,
                status=MatchStatus.pending,
                round_number=2
            )
            db.add_all([match1, match2])
            db.commit()
            
            result = suggest_schedule(tournament.id, db)
            
            assert len(result) == 2
            assert result[0]["match_id"] == match1.id
            assert result[0]["round"] == 1
            assert result[1]["match_id"] == match2.id
            assert result[1]["round"] == 2
            
            # Cleanup
            for m in [match1, match2]:
                db.delete(m)
            db.delete(tournament)
            for p in [p1, p2]:
                db.delete(p)
            db.commit()
        finally:
            db.close()


class TestDetectAnomalies:
    """Test anomaly detection."""

    def test_detect_anomalies_no_tournament(self):
        """Test anomaly detection with non-existent tournament."""
        db = SessionLocal()
        try:
            result = detect_anomalies(99999, db)
            assert result == []
        finally:
            db.close()

    def test_detect_anomalies_no_anomalies(self):
        """Test anomaly detection with clean data."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("anomaly_clean")
            
            # Create players
            p1 = Player(name=f"Anom{ts}P1")
            p2 = Player(name=f"Anom{ts}P2")
            db.add_all([p1, p2])
            db.commit()
            
            # Create tournament with completed match with valid score
            tournament = Tournament(name=f"Anomaly Test {ts}")
            db.add(tournament)
            db.flush()
            
            match = Match(
                player1=p1.name, player2=p2.name,
                player1_id=p1.id, player2_id=p2.id,
                tournament_id=tournament.id,
                status=MatchStatus.completed,
                score="11-5"
            )
            db.add(match)
            db.commit()
            
            result = detect_anomalies(tournament.id, db)
            assert result == []
            
            # Cleanup
            db.delete(match)
            db.delete(tournament)
            for p in [p1, p2]:
                db.delete(p)
            db.commit()
        finally:
            db.close()

    def test_detect_anomalies_missing_score(self):
        """Test detection of missing scores on completed matches."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("anomaly_missing")
            
            # Create players
            p1 = Player(name=f"Anom{ts}P1")
            p2 = Player(name=f"Anom{ts}P2")
            db.add_all([p1, p2])
            db.commit()
            
            # Create tournament with completed match without score
            tournament = Tournament(name=f"Anomaly Test {ts}")
            db.add(tournament)
            db.flush()
            
            match = Match(
                player1=p1.name, player2=p2.name,
                player1_id=p1.id, player2_id=p2.id,
                tournament_id=tournament.id,
                status=MatchStatus.completed,
                score=None
            )
            db.add(match)
            db.commit()
            
            result = detect_anomalies(tournament.id, db)
            
            assert len(result) == 1
            assert result[0]["type"] == "missing_score"
            
            # Cleanup
            db.delete(match)
            db.delete(tournament)
            for p in [p1, p2]:
                db.delete(p)
            db.commit()
        finally:
            db.close()

    def test_detect_anomalies_unusual_score(self):
        """Test detection of unusual scores."""
        init_db()
        db = SessionLocal()
        try:
            ts = _unique_name("anomaly_unusual")
            
            # Create players
            p1 = Player(name=f"Anom{ts}P1")
            p2 = Player(name=f"Anom{ts}P2")
            db.add_all([p1, p2])
            db.commit()
            
            # Create tournament with unusual score
            tournament = Tournament(name=f"Anomaly Test {ts}")
            db.add(tournament)
            db.flush()
            
            match = Match(
                player1=p1.name, player2=p2.name,
                player1_id=p1.id, player2_id=p2.id,
                tournament_id=tournament.id,
                status=MatchStatus.completed,
                score="15-12"  # Unusual in table tennis
            )
            db.add(match)
            db.commit()
            
            result = detect_anomalies(tournament.id, db)
            
            assert len(result) == 1
            assert result[0]["type"] == "unusual_score"
            
            # Cleanup
            db.delete(match)
            db.delete(tournament)
            for p in [p1, p2]:
                db.delete(p)
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])