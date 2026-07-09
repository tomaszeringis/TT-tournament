"""
Experiment Dashboard page for the Multimodal AI system.
Tracks model training and evaluation experiments.
"""

import streamlit as st

st.set_page_config(page_title="Experiment Dashboard - TT Platform", layout="wide")
import pandas as pd
from typing import List, Optional
import json

from tournament_platform.multimodal_ai.dataset_registry import DatasetRegistry


def get_registry() -> DatasetRegistry:
    """Get or create the dataset registry instance."""
    if "dataset_registry" not in st.session_state:
        st.session_state.dataset_registry = DatasetRegistry()
    return st.session_state.dataset_registry


def show():
    """Display the experiment dashboard page."""
    st.title("Experiment Dashboard")
    st.markdown("Track and manage ML model training/evaluation experiments.")
    
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["Experiments", "Create Experiment", "Evaluation Results"])
    
    with tab1:
        st.subheader("All Experiments")
        
        # Placeholder for experiments list
        st.info("Experiments will be loaded from the database via API.")
        
        # Sample data
        sample_experiments = [
            {"id": 1, "name": "Voice ASR Baseline", "combination": "voice_core", "status": "completed", "created": "2024-01-15"},
            {"id": 2, "name": "Stroke Detection v1", "combination": "tt_perception_core", "status": "running", "created": "2024-01-20"},
            {"id": 3, "name": "Coaching Model", "combination": "coaching_core", "status": "pending", "created": "2024-01-25"},
        ]
        
        df = pd.DataFrame(sample_experiments)
        st.dataframe(df, use_container_width=True, hide_index=True)
    
    with tab2:
        st.subheader("Create New Experiment")
        
        registry = get_registry()
        
        with st.form("create_experiment"):
            name = st.text_input("Experiment Name", placeholder="e.g., Voice ASR Fine-tune")
            
            # Get available combinations
            combinations = [
                "voice_core",
                "tt_perception_core",
                "coaching_core",
                "research_full",
                "commercial_safe_baseline",
            ]
            
            dataset_combination = st.selectbox(
                "Dataset Combination",
                options=combinations,
            )
            
            config_str = st.text_area(
                "Model Config (JSON)",
                value='{"model_type": "whisper", "epochs": 10, "batch_size": 32}',
                height=150,
            )
            
            submitted = st.form_submit_button("Create Experiment")
            
            if submitted:
                try:
                    config = json.loads(config_str) if config_str else {}
                    st.success(f"Experiment '{name}' created (placeholder - implement API call)")
                except json.JSONDecodeError:
                    st.error("Invalid JSON in config")
    
    with tab3:
        st.subheader("Evaluation Results")
        
        # Sample evaluation data
        sample_evaluations = [
            {"experiment_id": 1, "metric": "WER", "value": 0.15, "timestamp": "2024-01-16"},
            {"experiment_id": 1, "metric": "Accuracy", "value": 0.89, "timestamp": "2024-01-16"},
            {"experiment_id": 2, "metric": "mAP", "value": 0.72, "timestamp": "2024-01-21"},
        ]
        
        df = pd.DataFrame(sample_evaluations)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.divider()
        
        st.subheader("Add Evaluation Result")
        
        with st.form("add_evaluation"):
            experiment_id = st.number_input("Experiment ID", min_value=1, value=1, step=1)
            metric_name = st.text_input("Metric Name", placeholder="e.g., WER, mAP, Accuracy")
            metric_value = st.number_input("Metric Value", min_value=0.0, max_value=1.0, value=0.5, step=0.01)
            
            submitted = st.form_submit_button("Add Result")
            
            if submitted:
                st.success(f"Evaluation result added (placeholder - implement API call)")


if __name__ == "__main__":
    show()