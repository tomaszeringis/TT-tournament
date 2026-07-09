"""
Voice Dataset Recorder (Phase 4)

Opt-in, privacy-safe capture of voice command samples for grammar
evaluation and improvement. No audio is stored by default.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tournament_platform.services.settings import VOICE_DATASET_OPT_IN
from tournament_platform.models import VoiceCommand
from tournament_platform.app.services.voice.event_log import VoiceCommandRepository

logger = logging.getLogger(__name__)


@dataclass
class VoiceDatasetSample:
    """In-memory representation of a dataset sample."""
    id: Optional[int] = None
    match_id: Optional[int] = None
    transcript: str = ""
    parsed_intent: Optional[str] = None
    expected_intent: Optional[str] = None
    matched: Optional[bool] = None
    correction: Optional[str] = None
    match_context: Optional[Dict[str, Any]] = None
    mic_type: Optional[str] = None
    noise_condition: Optional[str] = None
    audio_stored: bool = False
    created_at: Optional[str] = None


class VoiceDatasetRecorder:
    """Opt-in recorder for voice command dataset samples."""

    def __init__(self, enabled: bool = VOICE_DATASET_OPT_IN):
        self.enabled = enabled

    def record(
        self,
        transcript: str,
        parsed_intent: Optional[str] = None,
        expected_intent: Optional[str] = None,
        match_id: Optional[int] = None,
        match_context: Optional[Dict[str, Any]] = None,
        mic_type: Optional[str] = None,
        noise_condition: Optional[str] = None,
        record_audio: bool = False,
        db: Any = None,
    ) -> Optional[VoiceDatasetSample]:
        """
        Record a dataset sample if opt-in is enabled.

        Args:
            transcript: Raw ASR transcript.
            parsed_intent: Intent parsed by the grammar.
            expected_intent: Operator-corrected intent label.
            match_id: Optional match context.
            match_context: Snapshot of match state (players, score, game#).
            mic_type: Microphone type label.
            noise_condition: Noise condition label.
            record_audio: If True, store audio (default False).
            db: Optional SQLAlchemy session.

        Returns:
            VoiceDatasetSample or None if disabled.
        """
        if not self.enabled:
            return None

        matched = None
        if expected_intent is not None and parsed_intent is not None:
            matched = expected_intent == parsed_intent

        payload: Dict[str, Any] = {
            "match_id": match_id,
            "transcript": transcript,
            "parsed_intent": parsed_intent,
            "expected_intent": expected_intent,
            "matched": matched,
            "correction": expected_intent if parsed_intent != expected_intent else None,
            "match_context": match_context,
            "mic_type": mic_type,
            "noise_condition": noise_condition,
            "audio_stored": record_audio,
        }

        try:
            cmd = VoiceCommandRepository.record(payload, db=db)
            return VoiceDatasetSample(
                id=cmd.id,
                match_id=cmd.match_id,
                transcript=cmd.transcript,
                parsed_intent=cmd.parsed_intent,
                expected_intent=cmd.expected_intent,
                matched=cmd.matched,
                correction=cmd.correction,
                match_context=json.loads(cmd.match_context) if cmd.match_context else None,
                mic_type=cmd.mic_type,
                noise_condition=cmd.noise_condition,
                audio_stored=cmd.audio_stored,
                created_at=cmd.created_at.isoformat() if cmd.created_at else None,
            )
        except Exception as exc:
            logger.error("Failed to record dataset sample: %s", exc)
            return None

    def get_samples(self, match_id: Optional[int] = None, limit: int = 200, db: Any = None) -> List[VoiceDatasetSample]:
        """
        Retrieve recorded samples.

        Args:
            match_id: Optional filter by match.
            limit: Maximum samples to return.
            db: Optional SQLAlchemy session.

        Returns:
            List of VoiceDatasetSample.
        """
        from tournament_platform.app.services.voice.event_log import VoiceCommandRepository

        close = False
        if db is None:
            db = VoiceCommandRepository._session()
            close = True
        try:
            query = db.query(VoiceCommand)
            if match_id is not None:
                query = query.filter(VoiceCommand.match_id == match_id)
            rows = query.order_by(VoiceCommand.created_at.desc()).limit(limit).all()
            return [
                VoiceDatasetSample(
                    id=row.id,
                    match_id=row.match_id,
                    transcript=row.transcript,
                    parsed_intent=row.parsed_intent,
                    expected_intent=row.expected_intent,
                    matched=row.matched,
                    correction=row.correction,
                    match_context=json.loads(row.match_context) if row.match_context else None,
                    mic_type=row.mic_type,
                    noise_condition=row.noise_condition,
                    audio_stored=row.audio_stored,
                    created_at=row.created_at.isoformat() if row.created_at else None,
                )
                for row in rows
            ]
        finally:
            if close:
                db.close()

    def export_jsonl(self, samples: Optional[List[VoiceDatasetSample]] = None, match_id: Optional[int] = None, db: Any = None) -> str:
        """
        Export samples as JSONL string.

        Args:
            samples: Optional pre-fetched samples.
            match_id: Optional filter by match when samples not provided.
            db: Optional SQLAlchemy session.

        Returns:
            JSONL string.
        """
        if samples is None:
            samples = self.get_samples(match_id=match_id, db=db)
        lines = []
        for sample in samples:
            obj = {
                "id": sample.id,
                "match_id": sample.match_id,
                "transcript": sample.transcript,
                "parsed_intent": sample.parsed_intent,
                "expected_intent": sample.expected_intent,
                "matched": sample.matched,
                "correction": sample.correction,
                "match_context": sample.match_context,
                "mic_type": sample.mic_type,
                "noise_condition": sample.noise_condition,
                "audio_stored": sample.audio_stored,
                "created_at": sample.created_at,
            }
            lines.append(json.dumps(obj, default=str))
        return "\n".join(lines) + ("\n" if lines else "")

    def export_csv(self, samples: Optional[List[VoiceDatasetSample]] = None, match_id: Optional[int] = None, db: Any = None) -> str:
        """
        Export samples as CSV string with accuracy summary.

        Args:
            samples: Optional pre-fetched samples.
            match_id: Optional filter by match when samples not provided.
            db: Optional SQLAlchemy session.

        Returns:
            CSV string.
        """
        if samples is None:
            samples = self.get_samples(match_id=match_id, db=db)
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id", "match_id", "transcript", "parsed_intent", "expected_intent",
                "matched", "correction", "mic_type", "noise_condition", "created_at",
            ],
        )
        writer.writeheader()
        for sample in samples:
            writer.writerow({
                "id": sample.id,
                "match_id": sample.match_id,
                "transcript": sample.transcript,
                "parsed_intent": sample.parsed_intent,
                "expected_intent": sample.expected_intent,
                "matched": sample.matched,
                "correction": sample.correction,
                "mic_type": sample.mic_type,
                "noise_condition": sample.noise_condition,
                "created_at": sample.created_at,
            })
        return output.getvalue()

    def accuracy_summary(self, samples: Optional[List[VoiceDatasetSample]] = None, match_id: Optional[int] = None, db: Any = None) -> Dict[str, Any]:
        """
        Compute accuracy summary for exported samples.

        Args:
            samples: Optional pre-fetched samples.
            match_id: Optional filter by match when samples not provided.
            db: Optional SQLAlchemy session.

        Returns:
            Dict with total, matched, accuracy, and confusion counts.
        """
        if samples is None:
            samples = self.get_samples(match_id=match_id, db=db)
        total = len(samples)
        matched = sum(1 for s in samples if s.matched is True)
        mismatched = sum(1 for s in samples if s.matched is False)
        unlabeled = total - matched - mismatched
        accuracy = (matched / total) if total else 0.0
        confusion: Dict[str, Dict[str, int]] = {}
        for sample in samples:
            if sample.parsed_intent and sample.expected_intent:
                confusion.setdefault(sample.expected_intent, {})
                confusion[sample.expected_intent][sample.parsed_intent] = (
                    confusion[sample.expected_intent].get(sample.parsed_intent, 0) + 1
                )
        return {
            "total": total,
            "matched": matched,
            "mismatched": mismatched,
            "unlabeled": unlabeled,
            "accuracy": accuracy,
            "confusion": confusion,
        }
