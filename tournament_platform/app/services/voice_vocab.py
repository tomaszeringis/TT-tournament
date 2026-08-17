"""
Voice Vocabulary & Domain Adaptation (Phase 6)

Provides:
- VoiceVocabulary: loads custom vocabulary JSON for ASR biasing and post-processing.
- TranscriptPostProcessor: applies vocabulary corrections, player/team name normalization,
  and domain-specific cleanup to ASR transcripts before parsing.

Design goals:
- Additive only — never changes scoring rules or parser behavior.
- Offline-first — vocabulary is a local JSON file, no network calls.
- Privacy-aware — player names are normalized for display/audit only, not stored
  in scoring state unless explicitly configured.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Pattern

logger = logging.getLogger(__name__)


@dataclass
class VoiceVocabulary:
    """
    Custom vocabulary for ASR biasing and transcript post-processing.

    Loads from a JSON file (path from VOICE_ASR_VOCAB_FILE env var or explicit arg).
    JSON schema:
    {
      "score_words": ["love", "zero", "one", "two", ...],
      "commands": ["point", "undo", "take back", ...],
      "player_names": ["Alice", "Bob", ...],
      "team_names": ["Team Alpha", "Team Beta", ...],
      "corrections": {"read": "red", "for": "four", ...},
      "initial_prompt": "Table tennis score: ..."
    }
    """

    score_words: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    player_names: List[str] = field(default_factory=list)
    team_names: List[str] = field(default_factory=list)
    corrections: Dict[str, str] = field(default_factory=dict)
    initial_prompt: str = ""
    _compiled_corrections: Dict[Pattern, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Compile correction patterns for efficient substitution."""
        self._compiled_corrections = {}
        for wrong, right in self.corrections.items():
            # Case-insensitive whole-word match
            pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
            self._compiled_corrections[pattern] = right

    @classmethod
    def load(cls, vocab_path: Optional[str] = None) -> "VoiceVocabulary":
        """
        Load vocabulary from a JSON file.

        Args:
            vocab_path: Path to JSON file. Falls back to VOICE_ASR_VOCAB_FILE env var.

        Returns:
            VoiceVocabulary instance (empty if file not found/invalid).
        """
        path = vocab_path or os.environ.get("VOICE_ASR_VOCAB_FILE", "")
        if not path:
            logger.debug("No VOICE_ASR_VOCAB_FILE set; using empty vocabulary")
            return cls()

        if not os.path.isfile(path):
            logger.warning("Vocabulary file not found: %s", path)
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded voice vocabulary from %s", path)
            return cls(
                score_words=data.get("score_words", []),
                commands=data.get("commands", []),
                player_names=data.get("player_names", []),
                team_names=data.get("team_names", []),
                corrections=data.get("corrections", {}),
                initial_prompt=data.get("initial_prompt", ""),
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load vocabulary from %s: %s", path, e)
            return cls()

    def get_initial_prompt(self) -> str:
        """Return the ASR initial prompt for biasing, or empty string."""
        return self.initial_prompt

    def get_biasing_words(self) -> List[str]:
        """
        Return all vocabulary words suitable for ASR biasing/hotwords.

        Combines score_words, commands, player_names, and team_names.
        """
        return list(
            set(self.score_words + self.commands + self.player_names + self.team_names)
        )

    def get_player_names(self) -> List[str]:
        """Return configured player names."""
        return list(self.player_names)

    def get_team_names(self) -> List[str]:
        """Return configured team names."""
        return list(self.team_names)


class TranscriptPostProcessor:
    """
    Post-processes ASR transcripts using a VoiceVocabulary.

    Applies corrections, normalizes player/team names, and performs
    domain-specific cleanup. Never mutates scoring state directly.
    """

    _DEFAULT_CORRECTIONS: Dict[str, str] = {
        "points": "point",
        "point read": "point red",
        "points read": "point red",
        "point red": "point red",
        "points red": "point red",
        "point blue": "point blue",
        "points blue": "point blue",
        "red point": "point red",
        "blue point": "point blue",
        "point to red": "point red",
        "point to blue": "point blue",
    }

    _LT_ALIAS_MAP: Dict[str, str] = {
        # LEFT variants (Deepgram & common variants)
        "taškas kairė": "point left",
        "taškas kairėje": "point left",
        "taškas kairės": "point left",
        "taškas kairi": "point left",
        "taškas kairį": "point left",
        "taskas kaire": "point left",
        "taskas kaireje": "point left",
        "taskas kairi": "point left",
        "taskas kairi.": "point left",  # Safety for internal dots if \b fails

        # RIGHT variants (Deepgram & common variants)
        "taškas dešinė": "point right",
        "taškas dešinėje": "point right",
        "taškas dešinės": "point right",
        "taskas desine": "point right",
        "taskas desineje": "point right",

        # Side only
        "kairė": "point left",
        "kairėje": "point left",
        "kairės": "point left",
        "kairi": "point left",
        "kairį": "point left",
        "kaire": "point left",
        "kaireje": "point left",
        "dešinė": "point right",
        "dešinėje": "point right",
        "dešinės": "point right",
        "desine": "point right",
        "desineje": "point right",

        # Commands & Players
        "taškas pirmam": "point player one",
        "taškas antram": "point player two",
        "atšaukti": "undo",
        "atgal": "undo",
    }

    def __init__(self, vocabulary: Optional[VoiceVocabulary] = None):
        """
        Initialize with an optional vocabulary.

        Args:
            vocabulary: VoiceVocabulary instance. If None, uses empty defaults.
        """
        self.vocabulary = vocabulary or VoiceVocabulary()
        self._compiled_defaults: Dict[Pattern, str] = {}
        for wrong, right in self._DEFAULT_CORRECTIONS.items():
            pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
            self._compiled_defaults[pattern] = right
        self._compiled_lt_aliases: Dict[Pattern, str] = {}
        for lt, en in self._LT_ALIAS_MAP.items():
            # Use strict matching for Lithuanian aliases to avoid conversational false positives
            pattern = re.compile(rf"^\s*{re.escape(lt)}\s*$", re.IGNORECASE)
            self._compiled_lt_aliases[pattern] = en

    def process(self, transcript: str, language: str = "en") -> str:
        """
        Apply post-processing to an ASR transcript.

        Steps:
         1. Apply built-in safe corrections (homophones, plural normalization).
         2. Apply language-aware alias expansion (Lithuanian → English canonical).
         3. Apply vocabulary corrections (e.g., "read" → "red").
         4. Normalize player/team names for display/audit.
         5. Clean up extra whitespace.

        Args:
            transcript: Raw ASR transcript text.
            language: Language code (e.g. "en", "lt") for canonicalization.

        Returns:
            Processed transcript string.
        """
        if not transcript:
            return transcript

        # Strip terminal punctuation (.,!?) to ensure deterministic alias matching
        text = transcript.strip()
        text = re.sub(r'[.,!?]+$', '', text)

        # Apply built-in corrections first (most specific)
        for pattern, replacement in self._compiled_defaults.items():
            text = pattern.sub(replacement, text)

        # Language-aware alias expansion
        if language and language.lower() == "lt":
            for pattern, replacement in self._compiled_lt_aliases.items():
                text = pattern.sub(replacement, text)

        # Apply vocabulary corrections
        for pattern, replacement in self.vocabulary._compiled_corrections.items():
            text = pattern.sub(replacement, text)

        # Normalize player/team names (case-insensitive match, preserve original casing
        # of the transcript but flag for audit)
        for name in self.vocabulary.player_names + self.vocabulary.team_names:
            pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
            text = pattern.sub(name, text)

        # Collapse multiple spaces
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def extract_entities(self, transcript: str) -> Dict[str, List[str]]:
        """
        Extract named entities from a transcript for audit/display.

        Returns a dict with keys: player_names, team_names, score_words, commands.
        """
        found_players = [
            name for name in self.vocabulary.player_names
            if re.search(rf"\b{re.escape(name)}\b", transcript, re.IGNORECASE)
        ]
        found_teams = [
            name for name in self.vocabulary.team_names
            if re.search(rf"\b{re.escape(name)}\b", transcript, re.IGNORECASE)
        ]
        found_scores = [
            word for word in self.vocabulary.score_words
            if re.search(rf"\b{re.escape(word)}\b", transcript, re.IGNORECASE)
        ]
        found_commands = [
            cmd for cmd in self.vocabulary.commands
            if re.search(rf"\b{re.escape(cmd)}\b", transcript, re.IGNORECASE)
        ]

        return {
            "player_names": found_players,
            "team_names": found_teams,
            "score_words": found_scores,
            "commands": found_commands,
        }
