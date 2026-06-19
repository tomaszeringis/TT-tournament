import os
import streamlit.components.v1 as components

# Create a _RELEASE constant. We'll set this to False while we're developing
# the component, and True when we're ready to package it and distribute it.
_RELEASE = True

if not _RELEASE:
    _component_func = components.declare_component(
        "bracket_viewer",
        url="http://localhost:3001",
    )
else:
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.abspath(os.path.join(parent_dir, "frontend"))
    if not os.path.exists(build_dir):
        raise FileNotFoundError(f"Frontend directory not found: {build_dir}")
    _component_func = components.declare_component("bracket_viewer", path=build_dir)

def interactive_bracket(bracket_data, height=600, key=None):
    """
    Renders a tournament bracket and returns the clicked match data.
    
    Args:
        bracket_data (dict): The tournament bracket data.
        height (int): The height of the component in pixels.
        key (str, optional): An optional key that uniquely identifies this component.
        
    Returns:
        dict: The match data if a match was clicked, otherwise None.
    """
    component_value = _component_func(bracket_data=bracket_data, height=height, key=key, default=None)
    return component_value
