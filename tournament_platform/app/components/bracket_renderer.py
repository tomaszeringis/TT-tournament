import streamlit as st
from tournament_platform.app.components.html_helper import render_html
import json


def render_bracket(bracket_data: dict, height: int = 600):
    """
    Renders a tournament bracket using brackets-viewer.js.

    Uses CSS variables for theme compatibility - the bracket will adapt to
    Streamlit's light/dark mode automatically.

    Args:
        bracket_data (dict): The bracket data in brackets-manager.js format.
                              Should contain 'stages', 'matches', 'matchGames', and 'participants'.
        height (int): The height of the component in pixels. Defaults to 600 for better
                     responsiveness on smaller screens.
    """

    # TODO(dep-warning): streamlit.components.v1.html may be removed after
    # 2026-06-01. This renders an inline HTML document (loading the
    # brackets-viewer CDN script/style) via render_html(). A future native
    # replacement would host brackets-viewer locally and/or use st.iframe.
    # Convert dict to JSON string for JS injection
    # We escape < to prevent </script> injection
    bracket_json = json.dumps(bracket_data).replace('<', '\\u003c')

    # Use CSS variables that inherit from Streamlit's theme
    # This ensures the component works in both light and dark modes
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tournament Bracket</title>

        <!-- Brackets Viewer CSS -->
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/brackets-viewer@latest/dist/brackets-viewer.min.css" />

        <!-- Brackets Viewer JS -->
        <script src="https://cdn.jsdelivr.net/npm/brackets-viewer@latest/dist/brackets-viewer.min.js"></script>

        <style>
            :root {{
                /* Use Streamlit's theme variables - they will be inherited */
                --background-color: var(--st-color-bg, #0e1117);
                --text-color: var(--st-color-text, #fafafa);
                --secondary-bg: var(--st-color-bg-secondary, #262730);
                --scrollbar-color: var(--st-color-scrollbar, #464b5d);
            }}

            body {{
                margin: 0;
                padding: 10px;
                background-color: var(--background-color);
                color: var(--text-color);
                font-family: var(--st-font, "Source Sans Pro", sans-serif);
            }}
            #bracket-container {{
                width: 100%;
                height: {height - 20}px;
                overflow: auto;
            }}
            /* Theme-aware scrollbar styling */
            ::-webkit-scrollbar {{
                width: 6px;
                height: 6px;
            }}
            ::-webkit-scrollbar-track {{
                background: transparent;
            }}
            ::-webkit-scrollbar-thumb {{
                background: var(--scrollbar-color);
                border-radius: 10px;
            }}
            ::-webkit-scrollbar-thumb:hover {{
                background: #60677a;
            }}
        </style>
    </head>
    <body>
        <div id="bracket-container" class="brackets-viewer"></div>

        <script>
            document.addEventListener('DOMContentLoaded', function() {{
                const data = {bracket_json};

                if (window.bracketsViewer) {{
                    window.bracketsViewer.render(data, {{
                        selector: '#bracket-container',
                        responsive: true,
                        separatedChildCount: true,
                        showStageName: true,
                        showFinal: true,
                    }});
                }} else {{
                    document.getElementById('bracket-container').innerHTML =
                        '<p style="color: var(--st-color-text, #fafafa); padding: 20px;">Error: brackets-viewer library failed to load. Check your network connection.</p>';
                }}
            }});
        </script>
    </body>
    </html>
    """

    # Use responsive height - let Streamlit handle the container width
    render_html(html_content, height=height, scrolling=True)
