from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Enum, Text, LargeBinary, Float, Boolean
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

class RatingHistory(Base):
    __tablename__ = "rating_history"
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    rating = Column(Integer)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship
    player = relationship("Player", back_populates="rating_history")


# ============================================================================
# Operator Workflow Models
# ============================================================================

class VenueTable(Base):
    """Represents a physical table at the venue."""
    __tablename__ = "venue_tables"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    is_active = Column(Integer, default=1)  # SQLite boolean as Integer
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


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

    # Operator workflow fields
    call_status = Column(String, default="not_called")  # not_called, queued, called, active, delayed, completed, cancelled
    called_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    delayed_until = Column(DateTime, nullable=True)
    operator_note = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    tournament = relationship("Tournament", back_populates="matches")
    next_match = relationship("Match", remote_side=[id], backref="previous_matches")
    player1_rel = relationship("Player", foreign_keys=[player1_id])
    player2_rel = relationship("Player", foreign_keys=[player2_id])
    winner_rel = relationship("Player", foreign_keys=[winner_id])


class Announcement(Base):
    """Tracks announcements sent for matches/tournaments."""
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=True)
    message = Column(String)
    channel = Column(String, default="local")
    sent_status = Column(String, default="pending")
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    match = relationship("Match", foreign_keys=[match_id])
    tournament = relationship("Tournament", foreign_keys=[tournament_id])


class AuditLog(Base):
    """Audit trail for operator state-changing actions."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String, default="operator")
    action = Column(String)
    entity_type = Column(String)
    entity_id = Column(Integer, nullable=True)
    payload_json = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ============================================================================
# Multimodal AI Models
# ============================================================================

class Dataset(Base):
    """Registry of available datasets for training/analysis."""
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(String, unique=True, index=True)  # e.g., "mozilla_common_voice"
    name = Column(String)
    modality = Column(String)  # audio, video, sensor, text, trajectory
    task = Column(String)  # asr, intent, ball_detection, etc.
    license = Column(String)  # cc0, cc_by, mit, apache, bsd, non_commercial, research_only
    commercial_allowed = Column(Boolean, default=False)
    source_url = Column(String, nullable=True)
    local_raw_path = Column(String, nullable=True)
    local_processed_path = Column(String, nullable=True)
    required_for_phase = Column(String, nullable=True)  # JSON list of phases
    notes = Column(String, nullable=True)
    size_gb = Column(Float, nullable=True)
    version = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    artifacts = relationship("DatasetArtifact", back_populates="dataset", cascade="all, delete-orphan")
    samples = relationship("DataSample", back_populates="dataset", cascade="all, delete-orphan")


class DatasetArtifact(Base):
    """Tracks downloaded/processed files for a dataset."""
    __tablename__ = "dataset_artifacts"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"))
    artifact_type = Column(String)  # raw, processed, model, index
    path = Column(String)
    checksum = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    dataset = relationship("Dataset", back_populates="artifacts")


class DataSample(Base):
    """Individual samples from a dataset."""
    __tablename__ = "data_samples"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"))
    sample_key = Column(String, index=True)  # Unique identifier within dataset
    timestamp = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON string for flexible metadata

    # Relationships
    dataset = relationship("Dataset", back_populates="samples")
    annotations = relationship("Annotation", back_populates="data_sample", cascade="all, delete-orphan")


class Annotation(Base):
    """Labels/annotations for data samples."""
    __tablename__ = "annotations"
    id = Column(Integer, primary_key=True, index=True)
    data_sample_id = Column(Integer, ForeignKey("data_samples.id"))
    annotator_id = Column(String, nullable=True)
    label = Column(String)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    data_sample = relationship("DataSample", back_populates="annotations")


class MultimodalSession(Base):
    """A recording session combining multiple modalities."""
    __tablename__ = "multimodal_sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_name = Column(String, nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    player1_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    player2_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON for flexible session metadata

    # Relationships
    player1 = relationship("Player", foreign_keys=[player1_id])
    player2 = relationship("Player", foreign_keys=[player2_id])
    sensor_streams = relationship("SensorStream", back_populates="session", cascade="all, delete-orphan")
    video_segments = relationship("VideoSegment", back_populates="session", cascade="all, delete-orphan")
    audio_segments = relationship("AudioSegment", back_populates="session", cascade="all, delete-orphan")
    ball_trajectories = relationship("BallTrajectory", back_populates="session", cascade="all, delete-orphan")
    stroke_events = relationship("StrokeEvent", back_populates="session", cascade="all, delete-orphan")
    coaching_feedback = relationship("CoachingFeedback", back_populates="session", cascade="all, delete-orphan")


class SensorStream(Base):
    """IMU or other sensor data stream from a session."""
    __tablename__ = "sensor_streams"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("multimodal_sessions.id"))
    sensor_type = Column(String)  # imu, audio, etc.
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    sample_rate = Column(Float, nullable=True)
    data_path = Column(String, nullable=True)  # Path to stored sensor data

    # Relationships
    session = relationship("MultimodalSession", back_populates="sensor_streams")


class VideoSegment(Base):
    """Video clip from a session."""
    __tablename__ = "video_segments"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("multimodal_sessions.id"))
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    video_path = Column(String, nullable=True)
    frame_count = Column(Integer, nullable=True)

    # Relationships
    session = relationship("MultimodalSession", back_populates="video_segments")


class AudioSegment(Base):
    """Audio clip from a session."""
    __tablename__ = "audio_segments"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("multimodal_sessions.id"))
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    audio_path = Column(String, nullable=True)
    sample_rate = Column(Integer, nullable=True)

    # Relationships
    session = relationship("MultimodalSession", back_populates="audio_segments")


class BallTrajectory(Base):
    """2D/3D ball trajectory data."""
    __tablename__ = "ball_trajectories"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("multimodal_sessions.id"))
    frame_data_json = Column(Text, nullable=True)  # JSON array of trajectory points
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    session = relationship("MultimodalSession", back_populates="ball_trajectories")


class StrokeEvent(Base):
    """Detected stroke event in a session."""
    __tablename__ = "stroke_events"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("multimodal_sessions.id"))
    stroke_type = Column(String)  # forehand, backhand, serve, etc.
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    confidence = Column(Float, nullable=True)

    # Relationships
    session = relationship("MultimodalSession", back_populates="stroke_events")


class CoachingFeedback(Base):
    """AI-generated coaching feedback for a session."""
    __tablename__ = "coaching_feedback"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("multimodal_sessions.id"))
    feedback_text = Column(Text, nullable=True)
    recommendations_json = Column(Text, nullable=True)  # JSON array of recommendations
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    session = relationship("MultimodalSession", back_populates="coaching_feedback")


class ModelExperiment(Base):
    """Tracks ML model training/evaluation experiments."""
    __tablename__ = "model_experiments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    model_config_json = Column(Text, nullable=True)  # JSON config
    dataset_combination = Column(String, nullable=True)  # e.g., "voice_core"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    evaluation_runs = relationship("EvaluationRun", back_populates="experiment", cascade="all, delete-orphan")


class EvaluationRun(Base):
    """Results from evaluating a model experiment."""
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("model_experiments.id"))
    metric_name = Column(String)
    metric_value = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    experiment = relationship("ModelExperiment", back_populates="evaluation_runs")


def init_db():
    Base.metadata.create_all(bind=engine)
