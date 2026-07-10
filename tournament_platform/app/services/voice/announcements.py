"""
Voice Announcements Service (Phase 4)

Automatic player and match announcements with deduplication.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from tournament_platform.app.services.voice.event_log import VoiceEventRepository

logger = logging.getLogger(__name__)


@dataclass
class Announcement:
    text: str
    event_type: str
    dedupe_key: str
    timestamp: float


class AnnouncementService:
    def __init__(self) -> None:
        self.last_announced_event_id: Optional[str] = None

    def generate_match_start(self, player_a: str, player_b: str, table: Optional[str] = None) -> Announcement:
        table_text = f" on table {table}" if table else ""
        text = f"Opening game between {player_a} and {player_b}{table_text}."
        return Announcement(
            text=text,
            event_type="match_start",
            dedupe_key=f"match_start:{player_a}:{player_b}",
            timestamp=time.time(),
        )

    def generate_next_match(self, player_a: str, player_b: str, table: Optional[str] = None) -> Announcement:
        table_text = f"table {table}" if table else "the next table"
        text = f"Next match on {table_text}: {player_a} versus {player_b}."
        return Announcement(
            text=text,
            event_type="next_match",
            dedupe_key=f"next_match:{player_a}:{player_b}",
            timestamp=time.time(),
        )

    def generate_game_won(self, player: str, score: str) -> Announcement:
        text = f"Game to {player}, {score}."
        return Announcement(
            text=text,
            event_type="game_won",
            dedupe_key=f"game_won:{player}:{score}",
            timestamp=time.time(),
        )

    def generate_match_won(self, player: str, sets_a: int, sets_b: int) -> Announcement:
        text = f"{player} wins the match {sets_a} games to {sets_b}."
        return Announcement(
            text=text,
            event_type="match_won",
            dedupe_key=f"match_won:{player}:{sets_a}:{sets_b}",
            timestamp=time.time(),
        )

    def should_announce(self, announcement: Announcement) -> bool:
        if self.last_announced_event_id == announcement.dedupe_key:
            return False
        return True

    def mark_announced(self, announcement: Announcement) -> None:
        self.last_announced_event_id = announcement.dedupe_key
