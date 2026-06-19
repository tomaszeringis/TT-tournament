import streamlit as st
import pandas as pd
import itables
from itables import to_html_datatable

def render_interactive_table(df: pd.DataFrame):
    """
    Renders an interactive DataTable using itables and streamlit components.
    Includes searching, pagination, and length menu.
    """
    # Define DataTables options
    options = {
        "searching": True,
        "paging": True,
        "lengthMenu": [10, 25, 50, 100],
        "responsive": True,
        "dom": "lfrtip",
    }
    
    # Generate HTML with custom styling for responsiveness
    # itables by default uses a 100% width table
    html = to_html_datatable(df, **options)
    
    # Wrap in a responsive container and add Streamlit-friendly styling
    custom_html = f"""
    <div style="width: 100%; overflow-x: auto;">
        {html}
    </div>
    <style>
        .dataTables_wrapper {{
            font-family: sans-serif;
            color: inherit;
        }}
    </style>
    """
    
    # Render in Streamlit
    st.components.v1.html(custom_html, height=500, scrolling=True)
