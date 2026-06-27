"""
Shared AI utilities for model availability and status checks.
Used by ai_engine.py, umpire_engine.py, and UI components.
"""

import ollama
import logging
from typing import Tuple, Optional

from tournament_platform.config import settings

logger = logging.getLogger(__name__)


def get_available_ollama_models() -> list:
    """
    Get list of available Ollama models.
    
    Returns:
        List of model names, or empty list if Ollama unavailable.
    """
    try:
        available_models_resp = ollama.list()
        
        if hasattr(available_models_resp, 'models'):
            model_names = [m.model for m in available_models_resp.models]
        else:
            model_names = [m.get('name') for m in available_models_resp.get('models', [])]
        
        return model_names
    except Exception as e:
        logger.error(f"Error connecting to Ollama: {e}")
        return []


def get_ollama_model_with_fallback(preferred_model: str = None) -> Tuple[str, bool]:
    """
    Get the best available Ollama model with fallback logic.
    
    Args:
        preferred_model: The preferred model name (defaults to settings.OLLAMA_MODEL)
    
    Returns:
        Tuple of (model_name, is_fallback) where is_fallback indicates
        if a fallback was used instead of the preferred model.
    """
    preferred = preferred_model or settings.OLLAMA_MODEL
    model_names = get_available_ollama_models()
    
    if not model_names:
        return preferred, False  # Will fail later with connection error
    
    # Check for preferred model
    if preferred in model_names:
        return preferred, False
    
    # Try fallbacks
    fallbacks = [
        "llama3.1:8b",
        "llama3:latest", 
        "llama3:8b",
        "llama3.2:3b",
        "llama3.2:1b"
    ]
    
    for fallback in fallbacks:
        if fallback in model_names:
            logger.info(f"Ollama model fallback: {preferred} -> {fallback}")
            return fallback, True
    
    # No model found, return preferred (will error on use)
    return preferred, False


def get_ai_status() -> dict:
    """
    Get comprehensive AI system status.
    
    Returns:
        Dictionary with connection status, model info, and any errors.
    """
    status = {
        "ollama_connected": False,
        "model_available": False,
        "current_model": settings.OLLAMA_MODEL,
        "fallback_model": None,
        "error": None
    }
    
    try:
        model_names = get_available_ollama_models()
        status["ollama_connected"] = len(model_names) > 0
        
        if model_names:
            model, is_fallback = get_ollama_model_with_fallback()
            status["current_model"] = model
            status["model_available"] = True
            if is_fallback:
                status["fallback_model"] = model
                
    except Exception as e:
        status["error"] = str(e)
    
    return status


def ensure_model_available(model: str = None, silent: bool = False) -> str:
    """
    Ensure the specified model is available, with fallback.
    
    Args:
        model: Model name to check (defaults to settings.OLLAMA_MODEL)
        silent: If True, don't print warnings
    
    Returns:
        The model name to use (may be a fallback)
    
    Raises:
        ValueError: If no model is available (with helpful message)
    """
    preferred = model or settings.OLLAMA_MODEL
    model_names = get_available_ollama_models()
    
    if not model_names:
        raise ValueError(
            f"Cannot connect to Ollama at {settings.OLLAMA_HOST}. "
            f"Please ensure Ollama is running ('ollama serve')."
        )
    
    if preferred in model_names:
        return preferred
    
    # Try fallbacks
    fallbacks = ["llama3.1:8b", "llama3:latest", "llama3:8b", "llama3.2:3b", "llama3.2:1b"]
    for fallback in fallbacks:
        if fallback in model_names:
            if not silent:
                print(f"Warning: Model '{preferred}' not found. Falling back to '{fallback}'.")
            return fallback
    
    raise ValueError(
        f"Model '{preferred}' not found in Ollama. "
        f"Please run 'ollama pull {preferred}' or set OLLAMA_MODEL to an available model. "
        f"Available models: {model_names}"
    )