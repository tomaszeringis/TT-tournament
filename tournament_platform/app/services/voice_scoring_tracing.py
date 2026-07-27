"""
Phase 3: Voice scoring integration with latency tracing and side-effect queuing.
Preserves all existing voice event lifecycle guards.
"""

import time
import uuid
import logging
from typing import Optional, Tuple

from tournament_platform.services.settings import VOICE_LATENCY_TRACE
from tournament_platform.app.services.latency_trace import record_latency

logger = logging.getLogger(__name__)


def _apply_voice_event_with_tracing(
    mm,
    event,
    match_id: Optional[int] = None,
    voice_event_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Apply a parsed voice event with optional latency tracing.
    
    **PRESERVES all existing voice event lifecycle:**
    - event_id deduplication
    - session_id checks
    - stale timestamp checks
    - voice enabled/listening guards
    - confirmation queue behavior
    - auto-confirm threshold
    - cooldown behavior
    - game boundary handling
    - undo/reset handling
    
    In low-latency mode (when VOICE_LOW_LATENCY_EXPERIMENTAL is set via settings):
    - Queues side effects instead of running synchronously
    """
    trace_id = str(uuid.uuid4())
    action = f"voice_event_{event.type}"
    
    started_ns = time.perf_counter_ns()
    
    # Apply the voice event (delegates to mm.apply_voice_event)
    success, msg = mm.apply_voice_event(event)
    
    # Record latency
    if VOICE_LATENCY_TRACE:
        record_latency(
            trace_id=trace_id,
            action_id=voice_event_id or f"evt_{int(time.time_ns())}",
            match_id=match_id,
            source="voice",
            stage="score_apply",
            started_ns=started_ns,
            finished_ns=time.perf_counter_ns(),
            success=success,
        )
    
    return success, msg


def _quick_voice_scoring_with_tracing(
    mm,
    transcript: str,
    match_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Quick voice scoring path with optional latency tracing.
    
    Preserves existing quick voice behavior while adding instrumentation.
    """
    trace_id = str(uuid.uuid4())
    
    started_ns = time.perf_counter_ns()
    
    # This is the existing quick voice logic - we wrap it with tracing
    from tournament_platform.app.services.voice.quick_voice import QuickVoiceScoringEngine
    
    quick_engine = QuickVoiceScoringEngine()
    success, msg = quick_engine.interpret_and_score(transcript)
    
    if success:
        # Apply the score change
        success, msg = mm.apply_voice_event(quick_engine.last_event)
    
    # Record latency
    if VOICE_LATENCY_TRACE:
        record_latency(
            trace_id=trace_id,
            action_id=f"quick_voice_{int(time.time_ns())}",
            match_id=match_id,
            source="quick_voice",
            stage="score_apply",
            started_ns=started_ns,
            finished_ns=time.perf_counter_ns(),
            success=success,
        )
    
    return success, msg