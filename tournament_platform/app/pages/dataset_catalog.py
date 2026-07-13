"""
Dataset Catalog page for the Multimodal AI system.
Allows browsing and managing registered datasets.
"""

import streamlit as st

from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.app.components.tour import render_tour

st.set_page_config(page_title="LIT_IT Dataset Catalog", layout="wide")
apply_global_styles()
import pandas as pd
from typing import List, Optional

from tournament_platform.multimodal_ai.dataset_registry import DatasetRegistry, LicenseType, Modality


def get_registry() -> DatasetRegistry:
    """Get or create the dataset registry instance."""
    if "dataset_registry" not in st.session_state:
        st.session_state.dataset_registry = DatasetRegistry()
    return st.session_state.dataset_registry


def show():
    """Display the dataset catalog page."""
    from tournament_platform.app.components.page_header import render_page_header

    render_page_header(
        title="LIT_IT Dataset Catalog",
        description="Browse and manage datasets for the Multimodal AI system.",
        icon_name="dataset_catalog",
    )
    render_tour("dataset_catalog")
    
    registry = get_registry()
    
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["All Datasets", "By Modality", "Combinations"])
    
    with tab1:
        st.subheader("All Registered Datasets")
        
        # Get all datasets
        datasets = registry.list_datasets()
        
        if not datasets:
            st.info("No datasets registered yet. Add datasets via the API or check the manifest.")
        else:
            # Convert to list of dicts for display
            datasets_dicts = [d.to_dict() for d in datasets]
            df = pd.DataFrame(datasets_dicts)
            
            # Add license warning column
            def license_warning(row):
                if row.get("license") in ["non_commercial", "research_only"]:
                    return "⚠️ Non-commercial"
                return "✅ Commercial OK"
            
            df["license_status"] = df.apply(license_warning, axis=1)
            
            # Display with selection
            st.dataframe(
                df[["dataset_id", "name", "modality", "task", "license", "license_status", "size_gb", "version"]],
                use_container_width=True,
                hide_index=True,
            )
            
            # Dataset detail view
            selected_id = st.selectbox(
                "Select dataset for details",
                options=[d.dataset_id for d in datasets],
                format_func=lambda x: x,
            )
            
            if selected_id:
                dataset = registry.get_dataset(selected_id)
                if dataset:
                    dataset_dict = dataset.to_dict()
                    with st.expander(f"Details: {selected_id}", expanded=True):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Name:** {dataset_dict.get('name')}")
                            st.markdown(f"**Modality:** {dataset_dict.get('modality')}")
                            st.markdown(f"**Task:** {dataset_dict.get('task')}")
                        with col2:
                            st.markdown(f"**License:** {dataset_dict.get('license')}")
                            st.markdown(f"**Commercial Allowed:** {'Yes' if dataset_dict.get('commercial_allowed') else 'No'}")
                            st.markdown(f"**Size:** {dataset_dict.get('size_gb', 'Unknown')} GB")
                        
                        if dataset_dict.get("source_url"):
                            st.markdown(f"**Source:** [{dataset_dict.get('source_url')}]({dataset_dict.get('source_url')})")
                        
                        if dataset_dict.get("notes"):
                            st.markdown(f"**Notes:** {dataset_dict.get('notes')}")
    
    with tab2:
        st.subheader("Datasets by Modality")
        
        modalities = ["audio", "video", "sensor", "text", "trajectory"]
        selected_modality = st.selectbox("Select modality", options=modalities)
        
        if selected_modality:
            modality_datasets = registry.list_datasets_by_modality(Modality(selected_modality))
            
            if not modality_datasets:
                st.info(f"No datasets found for modality: {selected_modality}")
            else:
                df = pd.DataFrame([d.to_dict() for d in modality_datasets])
                st.dataframe(
                    df[["dataset_id", "name", "task", "license", "commercial_allowed"]],
                    use_container_width=True,
                    hide_index=True,
                )
    
    with tab3:
        st.subheader("Dataset Combinations")
        
        combinations = [
            "voice_core",
            "tt_perception_core", 
            "coaching_core",
            "research_full",
            "commercial_safe_baseline",
        ]
        
        selected_combo = st.selectbox("Select combination", options=combinations)
        
        if selected_combo:
            combo_datasets = registry.get_combination(selected_combo)
            
            if not combo_datasets:
                st.info(f"No datasets found for combination: {selected_combo}")
            else:
                # Check license compliance
                validation_results = registry.validate_combination(selected_combo, allow_non_commercial=True)
                all_valid = all(validation_results.values())
                invalid_datasets = [ds_id for ds_id, valid in validation_results.items() if not valid]
                
                if all_valid:
                    st.success(f"✅ Combination '{selected_combo}' is valid for commercial use")
                else:
                    st.warning(f"⚠️ Combination '{selected_combo}' has license restrictions")
                    for ds_id in invalid_datasets:
                        st.warning(f"  - {ds_id} has non-commercial license")
                
                df = pd.DataFrame([d.to_dict() for d in combo_datasets])
                st.dataframe(
                    df[["dataset_id", "name", "modality", "task", "license"]],
                    use_container_width=True,
                    hide_index=True,
                )


if __name__ == "__main__":
    show()