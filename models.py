from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime
import enum

DATABASE_URL = "sqlite:///./data/tournament.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MatchStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    completed = "completed"

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    email = Column(String)
    rating = Column(Integer, default=1200)

class Tournament(Base):
    __tablename__ = "tournaments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)
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

    # Relationship
    tournament = relationship("Tournament", back_populates="matches")

def init_db():
    Base.metadata.create_all(bind=engine)
