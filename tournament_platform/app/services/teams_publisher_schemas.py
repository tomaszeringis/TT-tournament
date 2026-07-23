"""
Lightweight dataclasses for the Teams integration layer.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class TeamsEvent:
    event_type: str
    tournament_id: int
    match_id: Optional[int]
    title: str
    body: str
    facts: Dict[str, Any]
    created_at: datetime


@dataclass
class TeamsPostResult:
    success: bool
    status: str
    message: str
    event_key: str
    posted_at: Optional[datetime] = None


@dataclass
class TeamsPreview:
    event_key: str
    text: str
    event_type: str
    posted_at: Optional[datetime] = None


@dataclass
class TeamsPostRecord:
    id: int
    event_type: Optional[str]
    status: str
    error: Optional[str]
    posted_at: datetime
    event_key: str
