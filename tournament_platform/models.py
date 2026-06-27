from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from pathlib import Path
import datetime
import enum

# Build absolute path to database file
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "tournament.db"
# Use 3 slashes for Windows absolute paths. Path.as_posix() ensures forward slashes
# which are generally better handled by SQLAlchemy's URI parser.
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# Final check for accessibility
if not DATA_DIR.exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

try:
    # Test file access - create it if it doesn't exist
    if not DATABASE_PATH.exists():
        open(DATABASE_PATH, 'a').close()
except Exception as e:
    print(f"WARNING: Cannot access database file at {DATABASE_PATH}: {e}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MatchStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    completed = "completed"

class TournamentType(str, enum.Enum):
    knockout = "knockout"
    round_robin = "round-robin"

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    email = Column(String)
    rating = Column(Integer, default=1200)

    # Relationships
    rating_history = relationship("RatingHistory", back_populates="player", cascade="all, delete-orphan")

class Tournament(Base):
    __tablename__ = "tournaments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)
    tournament_type = Column(Enum(TournamentType), default=TournamentType.knockout)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship
    matches = relationship("Match", back_populates="tournament")

class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True, index=True)
    player1 = Column(String)
    player2 = Column(String)
    winner = Column(String, nullable=True)
    score = Column(String, nullable=True)
    status = Column(Enum(MatchStatus), default=MatchStatus.pending)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=True)
    scheduled_time = Column(DateTime, default=datetime.datetime.utcnow)
    location = Column(String, nullable=True)

    # Bracket-specific fields
    round_number = Column(Integer, nullable=True)
    bracket_index = Column(Integer, nullable=True)
    next_match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)

    # Foreign keys to Player (nullable for incremental migration)
    player1_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    player2_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    winner_id = Column(Integer, ForeignKey("players.id"), nullable=True)

    # Relationships
    tournament = relationship("Tournament", back_populates="matches")
    next_match = relationship("Match", remote_side=[id], backref="previous_matches")
    player1_rel = relationship("Player", foreign_keys=[player1_id])
    player2_rel = relationship("Player", foreign_keys=[player2_id])
    winner_rel = relationship("Player", foreign_keys=[winner_id])

class RatingHistory(Base):
    __tablename__ = "rating_history"
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    rating = Column(Integer)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship
    player = relationship("Player", back_populates="rating_history")

def init_db():
    Base.metadata.create_all(bind=engine)
