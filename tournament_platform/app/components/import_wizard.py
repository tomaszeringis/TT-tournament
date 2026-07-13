"""
Import Wizard Component

Multi-step dry-run wizard for Excel/CSV bulk import with preview,
column mapping, validation, and commit flow.
"""

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from tournament_platform.services.import_assistant import (
    detect_file_type,
    load_file_data,
    suggest_column_mapping,
    validate_import_data,
    preview_import,
    commit_import,
    SUPPORTED_ENTITIES,
    DEFAULT_COLUMN_MAPPINGS,
)
from tournament_platform.models import SessionLocal


WIZARD_STEPS = ["Upload", "Map Columns", "Preview", "Commit"]


def _init_wizard_state():
    if "import_wizard_step" not in st.session_state:
        st.session_state["import_wizard_step"] = 1
    if "import_file_data" not in st.session_state:
        st.session_state["import_file_data"] = None
    if "import_file_type" not in st.session_state:
        st.session_state["import_file_type"] = None
    if "import_entity_type" not in st.session_state:
        st.session_state["import_entity_type"] = "players"
    if "import_column_mapping" not in st.session_state:
        st.session_state["import_column_mapping"] = {}
    if "import_df" not in st.session_state:
        st.session_state["import_df"] = None
    if "import_preview" not in st.session_state:
        st.session_state["import_preview"] = None
    if "import_validation" not in st.session_state:
        st.session_state["import_validation"] = None


def render_step_upload() -> None:
    st.subheader("📁 Upload File")
    uploaded = st.file_uploader("Choose an Excel or CSV file", type=["xlsx", "xls", "csv"], key="import_wizard_upload")
    if uploaded is not None:
        file_data = uploaded.read()
        file_type = detect_file_type(file_data)
        if file_type == "unknown":
            st.error("Unsupported file format. Please upload an Excel or CSV file.")
            return
        df = load_file_data(file_data, file_type)
        st.session_state["import_file_data"] = file_data
        st.session_state["import_file_type"] = file_type
        st.session_state["import_df"] = df
        st.success(f"Loaded {len(df)} rows from {uploaded.name}")
        st.dataframe(df.head(10), use_container_width=True)


def render_step_map_columns() -> None:
    st.subheader("🔗 Map Columns")
    df = st.session_state.get("import_df")
    if df is None:
        st.warning("Upload a file first.")
        return

    entity_type = st.selectbox(
        "Entity type",
        options=SUPPORTED_ENTITIES,
        index=SUPPORTED_ENTITIES.index(st.session_state.get("import_entity_type", "players")),
        key="import_entity_select",
    )
    st.session_state["import_entity_type"] = entity_type

    suggestion = suggest_column_mapping(df, entity_type)
    current_mapping = st.session_state.get("import_column_mapping") or suggestion

    cols = st.columns(2)
    new_mapping = {}
    for idx, (field, default_col) in enumerate(DEFAULT_COLUMN_MAPPINGS.get(entity_type, {}).items()):
        with cols[idx % 2]:
            new_mapping[field] = st.selectbox(
                f"Map '{field}' to:",
                options=[""] + list(df.columns),
                index=list(df.columns).index(current_mapping.get(field, default_col)) if current_mapping.get(field, default_col) in df.columns else 0,
                key=f"import_map_{field}",
            )
    st.session_state["import_column_mapping"] = new_mapping


def render_step_preview() -> None:
    st.subheader("🔍 Preview Import")
    df = st.session_state.get("import_df")
    mapping = st.session_state.get("import_column_mapping")
    entity_type = st.session_state.get("import_entity_type", "players")
    if df is None or not mapping:
        st.warning("Complete upload and mapping first.")
        return

    db = SessionLocal()
    try:
        preview = preview_import(db, entity_type=entity_type, df=df, column_mapping=mapping)
    finally:
        db.close()
    st.session_state["import_preview"] = preview

    if not preview.get("success"):
        st.error("Validation failed:")
        for err in preview.get("errors", []):
            st.error(err)
        return

    st.success(f"Ready to import {preview.get('rows_to_add', 0)} rows")
    if preview.get("warnings"):
        for w in preview.get("warnings", []):
            st.warning(w)
    sample = preview.get("sample_data", [])
    if sample:
        st.dataframe(pd.DataFrame(sample), use_container_width=True)


def render_step_commit() -> None:
    st.subheader("✅ Commit Import")
    preview = st.session_state.get("import_preview")
    if not preview or not preview.get("success"):
        st.warning("Run preview first.")
        return

    st.info(f"About to import {preview.get('rows_to_add', 0)} rows.")
    st.caption("This action cannot be undone.")

    entity_type = st.session_state.get("import_entity_type", "players")
    mapping = st.session_state.get("import_column_mapping", {})
    df = st.session_state.get("import_df")

    if st.button("Import Data", type="primary", key="import_commit_btn"):
        db = SessionLocal()
        try:
            result = commit_import(db, entity_type=entity_type, df=df, column_mapping=mapping, actor="operator")
            if result.get("success"):
                st.success(f"Imported {result.get('rows_added', 0)} rows")
                st.session_state["import_wizard_step"] = 1
                for key in ["import_file_data", "import_file_type", "import_df", "import_column_mapping", "import_preview", "import_validation"]:
                    st.session_state[key] = None if key not in ["import_wizard_step"] else 1
                st.rerun()
            else:
                st.error(result.get("error", "Import failed"))
        finally:
            db.close()


def render_import_wizard() -> None:
    _init_wizard_state()
    step = st.session_state.get("import_wizard_step", 1)

    st.markdown("**Step**")
    cols = st.columns(len(WIZARD_STEPS))
    for idx, label in enumerate(WIZARD_STEPS, start=1):
        with cols[idx - 1]:
            st.markdown(f"{'**' if idx == step else ''}{idx}. {label}{'**' if idx == step else ''}")

    if step == 1:
        render_step_upload()
    elif step == 2:
        render_step_map_columns()
    elif step == 3:
        render_step_preview()
    elif step == 4:
        render_step_commit()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("← Back", key="import_wizard_back") and step > 1:
            st.session_state["import_wizard_step"] = step - 1
            st.rerun()
    with c4:
        if st.button("Next →", key="import_wizard_next") and step < len(WIZARD_STEPS):
            st.session_state["import_wizard_step"] = step + 1
            st.rerun()
