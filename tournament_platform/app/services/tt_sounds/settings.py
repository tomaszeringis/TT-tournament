"""Re-export TT Sounds feature flags from the central settings module."""

from tournament_platform.services.settings import (  # noqa: F401
    TT_SOUNDS_ENABLED,
    TT_SOUNDS_ABS_MIN_ENERGY,
    TT_SOUNDS_THRESHOLD_MULTIPLIER,
    TT_SOUNDS_NOISE_FLOOR_DECAY,
    TT_SOUNDS_COOLDOWN_MS,
    TT_SOUNDS_WINDOW_MS,
    TT_SOUNDS_EVENT_WINDOW_MS,
    TT_SOUNDS_MIN_INTERVAL_MS,
    TT_SOUNDS_DEBUG,
    TT_SOUNDS_MODEL_DIR,
)
