"""
Pydantic schemas for Multimodal AI API endpoints.
These schemas are used by the FastAPI endpoints for dataset management,
multimodal sessions, and coaching analysis.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================================================
# Dataset Registry Schemas
# ============================================================================

class LicenseType(str, Enum):
    """License types for datasets."""
    CC0 = "cc0"
    CC_BY = "cc_by"
    MIT = "mit"
    APACHE = "apache"
    BSD = "bsd"
    NON_COMMERCIAL = "non_commercial"
    RESEARCH_ONLY = "research_only"


class Modality(str, Enum):
    """Data modalities for datasets."""
    AUDIO = "audio"
    VIDEO = "video"
    SENSOR = "sensor"
    TEXT = "text"
    TRAJECTORY = "trajectory"


class Task(str, Enum):
    """ML tasks supported by datasets."""
    ASR = "asr"
    INTENT = "intent"
    ANTI_SPOOF = "anti_spoof"
    BALL_DETECTION = "ball_detection"
    BOUNCE_EVENT = "bounce_event"
    STROKE_CLASSIFICATION = "stroke_classification"
    POSTURE_ESTIMATION = "posture_estimation"
    RALLY_OUTCOME = "rally_outcome"
    TRAJECTORY_RECONSTRUCTION = "trajectory_reconstruction"
    SPEAKER_ID = "speaker_id"
    EMOTION = "emotion"
    ACOUSTIC_EVENT = "acoustic_event"


class DatasetInfo(BaseModel):
    """Dataset information for API responses."""
    dataset_id: str
    name: str
    modality: str
    task: str
    license: str
    commercial_allowed: bool
    source_url: Optional[str] = None
    local_raw_path: Optional[str] = None
    local_processed_path: Optional[str] = None
    required_for_phase: Optional[List[str]] = None
    notes: Optional[str] = None
    size_gb: Optional[float] = None
    version: Optional[str] = None


class DatasetRegisterRequest(BaseModel):
    """Request to register a dataset."""
    dataset_id: str
    name: str
    modality: str
    task: str
    license: str
    commercial_allowed: bool = False
    source_url: Optional[str] = None
    local_raw_path: Optional[str] = None
    local_processed_path: Optional[str] = None
    required_for_phase: Optional[List[str]] = None
    notes: Optional[str] = None


class DatasetValidationRequest(BaseModel):
    """Request to validate a dataset combination."""
    combination: str
    commercial_use: bool = False


class DatasetValidationResponse(BaseModel):
    """Response from dataset validation."""
    valid: bool
    combination: str
    datasets: List[DatasetInfo]
    warnings: List[str] = []
    errors: List[str] = []


# ============================================================================
# Multimodal Session Schemas
# ============================================================================

class MultimodalSessionCreate(BaseModel):
    """Request to create a multimodal session."""
    session_name: Optional[str] = None
    player1_id: Optional[int] = None
    player2_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class MultimodalSessionResponse(BaseModel):
    """Response for multimodal session."""
    id: int
    session_name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    player1_id: Optional[int] = None
    player2_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class AudioSegmentCreate(BaseModel):
    """Request to create an audio segment."""
    session_id: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    audio_path: Optional[str] = None
    sample_rate: Optional[int] = None


class VideoSegmentCreate(BaseModel):
    """Request to create a video segment."""
    session_id: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    video_path: Optional[str] = None
    frame_count: Optional[int] = None


class SensorStreamCreate(BaseModel):
    """Request to create a sensor stream."""
    session_id: int
    sensor_type: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    sample_rate: Optional[float] = None
    data_path: Optional[str] = None


# ============================================================================
# Coaching Analysis Schemas
# ============================================================================

class CoachingAnalyzeRequest(BaseModel):
    """Request to analyze a session for coaching feedback."""
    session_id: int
    include_asr: bool = True
    include_stroke_analysis: bool = True
    include_trajectory: bool = True
    include_recommendations: bool = True


class CoachingRecommendation(BaseModel):
    """Single coaching recommendation."""
    category: str  # technique, footwork, timing, etc.
    priority: str  # high, medium, low
    suggestion: str
    confidence: Optional[float] = None


class CoachingAnalyzeResponse(BaseModel):
    """Response from coaching analysis."""
    session_id: int
    status: str
    feedback_text: Optional[str] = None
    recommendations: List[CoachingRecommendation] = []
    asr_transcript: Optional[str] = None
    detected_strokes: List[Dict[str, Any]] = []
    ball_trajectory_points: Optional[int] = None


# ============================================================================
# Model Experiment Schemas
# ============================================================================

class ModelExperimentCreate(BaseModel):
    """Request to create a model experiment."""
    name: str
    config: Optional[Dict[str, Any]] = None
    dataset_combination: Optional[str] = None


class ModelExperimentResponse(BaseModel):
    """Response for model experiment."""
    id: int
    name: str
    config: Optional[Dict[str, Any]] = None
    dataset_combination: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class EvaluationRunCreate(BaseModel):
    """Request to create an evaluation run."""
    experiment_id: int
    metric_name: str
    metric_value: float


class EvaluationRunResponse(BaseModel):
    """Response for evaluation run."""
    id: int
    experiment_id: int
    metric_name: str
    metric_value: float
    created_at: datetime


# ============================================================================
# Intent Classification Schemas
# ============================================================================

class IntentType(str, Enum):
    """Types of intents for voice commands."""
    SCORE_UPDATE = "score_update"
    COACHING_QUERY = "coaching_query"
    SESSION_CONTROL = "session_control"
    PLAYER_INFO = "player_info"
    UNKNOWN = "unknown"


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: IntentType
    confidence: float
    entities: Dict[str, Any] = {}


class IntentClassifyRequest(BaseModel):
    """Request to classify intent from text."""
    text: str
    threshold: float = 0.5


# ============================================================================
# Dataset Combination Presets
# ============================================================================

class DatasetCombination(str, Enum):
    """Predefined dataset combinations."""
    VOICE_CORE = "voice_core"
    TT_PERCEPTION_CORE = "tt_perception_core"
    COACHING_CORE = "coaching_core"
    RESEARCH_FULL = "research_full"
    COMMERCIAL_SAFE_BASELINE = "commercial_safe_baseline"