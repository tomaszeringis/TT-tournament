"""
Coaching Lab page for the Multimodal AI system.
Provides interface for session analysis and coaching feedback.
"""

import streamlit as st
import pandas as pd
from typing import List, Optional
import json

from tournament_platform.multimodal_ai.dataset_registry import DatasetRegistry
from tournament_platform.multimodal_ai.intent_classifier import IntentClassifier


def get_registry() -> DatasetRegistry:
    """Get or create the dataset registry instance."""
    if "dataset_registry" not in st.session_state:
        st.session_state.dataset_registry = DatasetRegistry()
    return st.session_state.dataset_registry


def get_intent_classifier() -> IntentClassifier:
    """Get or create the intent classifier instance."""
    if "intent_classifier" not in st.session_state:
        st.session_state.intent_classifier = IntentClassifier()
    return st.session_state.intent_classifier


def show():
    """Display the coaching lab page."""
    st.title("Coaching Lab")
    st.markdown("Analyze table tennis sessions and get AI-powered coaching feedback.")
    
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["Session Analysis", "Intent Classification", "Recommendations"])
    
    with tab1:
        st.subheader("Session Analysis")
        
        # Session creation form
        with st.form("create_session"):
            session_name = st.text_input("Session Name", placeholder="e.g., Player1 vs Player2 - Training")
            
            col1, col2 = st.columns(2)
            with col1:
                player1_id = st.number_input("Player 1 ID", min_value=1, value=None, step=1)
            with col2:
                player2_id = st.number_input("Player 2 ID", min_value=1, value=None, step=1)
            
            metadata_str = st.text_area(
                "Session Metadata (JSON)",
                value='{"location": "table_1", "date": "2024-01-15"}',
                height=100,
            )
            
            submitted = st.form_submit_button("Create Session")
            
            if submitted:
                try:
                    metadata = json.loads(metadata_str) if metadata_str else {}
                    st.success(f"Session '{session_name}' created (placeholder - implement API call)")
                except json.JSONDecodeError:
                    st.error("Invalid JSON in metadata")
        
        st.divider()
        
        # Analysis options
        st.subheader("Analyze Existing Session")
        
        session_id = st.number_input("Session ID to Analyze", min_value=1, value=1, step=1)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            include_asr = st.checkbox("Include ASR", value=True)
        with col2:
            include_stroke = st.checkbox("Include Stroke Analysis", value=True)
        with col3:
            include_trajectory = st.checkbox("Include Trajectory", value=True)
        with col4:
            include_recommendations = st.checkbox("Include Recommendations", value=True)
        
        if st.button("Run Analysis"):
            st.info("Analysis placeholder - implement API call to /api/coaching/analyze")
            st.markdown("**Sample Output:**")
            st.markdown("- Detected 15 forehand strokes")
            st.markdown("- Ball trajectory: 2.3 m/s average speed")
            st.markdown("- Recommendation: Improve backhand positioning")
    
    with tab2:
        st.subheader("Intent Classification")
        
        classifier = get_intent_classifier()
        
        text_input = st.text_area(
            "Enter transcribed text to classify",
            placeholder="e.g., 'What was my forehand technique?' or 'Score is 11-5'",
            height=100,
        )
        
        threshold = st.slider("Confidence Threshold", 0.0, 1.0, 0.5, 0.05)
        
        if st.button("Classify Intent"):
            if text_input:
                result = classifier.classify(text_input, threshold)
                st.success(f"Intent: **{result.intent}** (confidence: {result.confidence:.2f})")
                
                if result.entities:
                    st.json(result.entities)
            else:
                st.warning("Please enter some text to classify")
        
        st.divider()
        
        st.subheader("Supported Intents")
        intents = classifier.get_supported_intents()
        for intent in intents:
            st.markdown(f"- {intent}")
    
    with tab3:
        st.subheader("Coaching Recommendations")
        
        st.info("Recommendations will be generated based on session analysis.")
        
        # Sample recommendations table
        sample_recommendations = [
            {"category": "Technique", "priority": "High", "suggestion": "Keep racket angle consistent on forehand"},
            {"category": "Footwork", "priority": "Medium", "suggestion": "Move to ball earlier on backhand"},
            {"category": "Timing", "priority": "Low", "suggestion": "Practice rally consistency drills"},
        ]
        
        df = pd.DataFrame(sample_recommendations)
        st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    show()