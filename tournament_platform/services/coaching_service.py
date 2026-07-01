"""
Coaching service for the Multimodal AI system.
Integrates with the existing AI engine for RAG-based coaching feedback.
"""

import logging
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from tournament_platform.services.ai_engine import AIEngine
from tournament_platform.multimodal_ai.feature_extraction import (
    AudioFeatures,
    VideoFeatures,
    SensorFeatures,
    TrajectoryFeatures,
)

logger = logging.getLogger(__name__)


@dataclass
class CoachingRecommendation:
    """A single coaching recommendation."""
    category: str  # technique, footwork, timing, etc.
    priority: str  # high, medium, low
    suggestion: str
    confidence: Optional[float] = None


@dataclass
class CoachingFeedback:
    """Complete coaching feedback for a session."""
    session_id: int
    feedback_text: str
    recommendations: List[CoachingRecommendation]
    asr_transcript: Optional[str] = None
    detected_strokes: Optional[List[Dict[str, Any]]] = None
    ball_trajectory_points: Optional[int] = None


class CoachingService:
    """
    Service for generating coaching feedback from multimodal session data.
    
    Pipeline:
    raw session -> feature extraction -> normalized events -> 
    retrieval context -> LLM structured coaching feedback -> saved CoachingFeedback record
    """
    
    def __init__(self, ai_engine: Optional[AIEngine] = None):
        self.ai_engine = ai_engine or AIEngine()
    
    def generate_feedback(
        self,
        session_id: int,
        transcript: str,
        stroke_type: Optional[str] = None,
        audio_features: Optional[AudioFeatures] = None,
        video_features: Optional[VideoFeatures] = None,
        sensor_features: Optional[SensorFeatures] = None,
        trajectory_features: Optional[TrajectoryFeatures] = None,
    ) -> CoachingFeedback:
        """
        Generate coaching feedback from extracted features and transcript.
        
        This uses the AI engine with RAG to provide stroke-specific coaching.
        """
        # Build context for RAG
        context_parts = []
        
        if transcript:
            context_parts.append(f"Player query: {transcript}")
        
        if stroke_type:
            context_parts.append(f"Stroke type: {stroke_type}")
        
        if audio_features:
            if audio_features.transcript:
                context_parts.append(f"Audio transcript: {audio_features.transcript}")
            if audio_features.intent:
                context_parts.append(f"Intent: {audio_features.intent}")
        
        if video_features:
            if video_features.stroke_classifications:
                context_parts.append(f"Strokes detected: {len(video_features.stroke_classifications)}")
            if video_features.bounce_events:
                context_parts.append(f"Bounces detected: {len(video_features.bounce_events)}")
        
        if sensor_features:
            if sensor_features.swing_phase:
                context_parts.append(f"Swing phase: {sensor_features.swing_phase}")
        
        if trajectory_features:
            if trajectory_features.ball_speed:
                context_parts.append(f"Ball speed: {trajectory_features.ball_speed} m/s")
        
        context = "\n".join(context_parts)
        
        # Use AI engine for coaching feedback if available
        try:
            # Retrieve coaching knowledge from RAG
            coaching_context = self.ai_engine.rules_retriever.search_rules(
                f"table tennis {stroke_type or 'technique'} coaching advice",
                n_results=3
            )
            
            # Build prompt for LLM
            prompt = f"""You are a table tennis coach providing feedback to a player.
            
Context from player: {context}

Coaching knowledge from T3Set dataset: {coaching_context if coaching_context else 'No specific knowledge available'}

Provide a JSON response with:
- feedback_text: A short, encouraging coaching message (2-3 sentences)
- recommendations: A list of 2-3 specific, actionable suggestions

Format:
{{
    "feedback_text": "...",
    "recommendations": [
        {{"category": "technique", "priority": "high|medium|low", "suggestion": "..."}}
    ]
}}

Respond ONLY with valid JSON."""
            
            response = self.ai_engine._chat_with_fallback(
                messages=[{'role': 'user', 'content': prompt}],
                format="json"
            )
            
            response_text = response['message']['content']
            feedback_dict = json.loads(response_text)
            
            recommendations = [
                CoachingRecommendation(
                    category=rec.get("category", "general"),
                    priority=rec.get("priority", "medium"),
                    suggestion=rec.get("suggestion", ""),
                    confidence=rec.get("confidence")
                )
                for rec in feedback_dict.get("recommendations", [])
            ]
            
            return CoachingFeedback(
                session_id=session_id,
                feedback_text=feedback_dict.get("feedback_text", "Coaching feedback generated."),
                recommendations=recommendations,
                asr_transcript=transcript,
                detected_strokes=video_features.stroke_classifications if video_features else None,
                ball_trajectory_points=len(trajectory_features.trajectory_points) if trajectory_features and trajectory_features.trajectory_points else 0,
            )
            
        except Exception as e:
            logger.warning(f"AI coaching failed, using fallback: {e}")
            # Fallback to mock feedback
            recommendations = [
                CoachingRecommendation(
                    category="technique",
                    priority="medium",
                    suggestion=f"Focus on your {stroke_type or 'stroke'} technique for better consistency",
                    confidence=0.8,
                ),
            ]
            
            return CoachingFeedback(
                session_id=session_id,
                feedback_text=f"Coaching tip for {stroke_type or 'your game'}: Keep practicing and focus on consistent contact.",
                recommendations=recommendations,
                asr_transcript=transcript,
                detected_strokes=video_features.stroke_classifications if video_features else None,
                ball_trajectory_points=len(trajectory_features.trajectory_points) if trajectory_features and trajectory_features.trajectory_points else 0,
            )
    
    def get_coaching_rules(self) -> List[Dict[str, Any]]:
        """
        Get table tennis coaching rules and techniques.
        
        These would be indexed in the RAG system.
        """
        return [
            {
                "technique": "forehand",
                "key_points": ["Racket angle", "Body position", "Follow through"],
                "common_mistakes": ["Too much wrist", "Late contact"],
            },
            {
                "technique": "backhand",
                "key_points": ["Elbow position", "Racket angle", "Weight transfer"],
                "common_mistakes": ["Collapsed wrist", "No follow through"],
            },
            {
                "technique": "serve",
                "key_points": ["Ball toss", "Racket motion", "Contact point"],
                "common_mistakes": ["High toss", "No spin"],
            },
        ]