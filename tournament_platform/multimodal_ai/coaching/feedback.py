"""Coaching feedback data structures."""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CoachingFeedback:
    """Coaching feedback record."""
    session_id: str
    feedback_text: str
    recommendations: List[str] = None
    technique_score: Optional[float] = None
    confidence: Optional[float] = None
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "session_id": self.session_id,
            "feedback_text": self.feedback_text,
            "recommendations": self.recommendations,
            "technique_score": self.technique_score,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoachingFeedback":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            feedback_text=data["feedback_text"],
            recommendations=data.get("recommendations", []),
            technique_score=data.get("technique_score"),
            confidence=data.get("confidence"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )