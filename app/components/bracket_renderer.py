import streamlit as st
import streamlit.components.v1 as components
import json

def render_bracket(bracket_data: dict, height: int = 800):
    """
    Renders a tournament bracket using brackets-viewer.js.
    
    Args:
        bracket_data (dict): The bracket data in brackets-manager.js format.
                             Should contain 'stages', 'matches', 'matchGames', and 'participants'.
        height (int): The height of the component in pixels.
    """
    
    # Convert dict to JSON string for JS injection
    # We escape < to prevent </script> injection
    bracket_json = json.dumps(bracket_data).replace('<', '\\u003c')
    
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
            body {{
                margin: 0;
                padding: 10px;
                background-color: #0e1117; /* Default Streamlit Dark Background */
                color: #fafafa;
                font-family: "Source Sans Pro", sans-serif;
            }}
            #bracket-container {{
                width: 100%;
                height: {height - 20}px;
                overflow: auto;
            }}
            /* Customizing scrollbar to match Streamlit style */
            ::-webkit-scrollbar {{
                width: 8px;
                height: 8px;
            }}
            ::-webkit-scrollbar-track {{
                background: rgba(0,0,0,0);
            }}
            ::-webkit-scrollbar-thumb {{
                background: #464b5d;
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
                        '<p style="color: red;">Error: brackets-viewer library failed to load.</p>';
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    components.html(html_content, height=height, scrolling=True)
