"""
UI Feedback — optional sound cues for the scoreboard.

Feature-flagged via ``SCORE_ENABLE_SOUNDS`` (default ``false``). When disabled,
all functions are no-ops. When enabled, a tiny ``streamlit.components.v1``
HTML/JS component plays Web Audio cues for key events.

No audio asset files are required; all sounds are synthesized in the browser.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def _sounds_enabled() -> bool:
    """Return True if sound cues are enabled via environment / config."""
    import os
    val = os.environ.get("SCORE_ENABLE_SOUNDS", "false").lower()
    return val in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Sound cue definitions (Web Audio oscillator-based)
# ---------------------------------------------------------------------------

_CUE_JS = """
<script>
(function() {
  if (window.__scoreCueCtx) return;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;
  window.__scoreCueCtx = new AudioContext();

  const cues = {
    point:   { freq: 880,  type: 'sine',     dur: 0.08, vol: 0.15 },
    undo:    { freq: 440,  type: 'triangle', dur: 0.15, vol: 0.12 },
    deuce:   { freq: 660,  type: 'square',   dur: 0.20, vol: 0.10 },
    game:    { freq: 1047, type: 'sine',     dur: 0.30, vol: 0.18 },
    match:   { freq: 1319, type: 'sine',     dur: 0.50, vol: 0.20 },
    reject:  { freq: 220,  type: 'sawtooth', dur: 0.25, vol: 0.08 },
  };

  window.__playScoreCue = function(name) {
    const c = window.__scoreCueCtx;
    if (c.state === 'suspended') c.resume();
    const cue = cues[name];
    if (!cue) return;
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = cue.type;
    osc.frequency.setValueAtTime(cue.freq, c.currentTime);
    gain.gain.setValueAtTime(cue.vol, c.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, c.currentTime + cue.dur);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(c.currentTime);
    osc.stop(c.currentTime + cue.dur);
  };
})();
</script>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def play_cue(event_type: str, *, enabled: Optional[bool] = None) -> None:
    """Play a sound cue for the given event type.

    Args:
        event_type: One of ``point``, ``undo``, ``deuce``, ``game``,
                    ``match``, ``reject``.
        enabled: Override the feature flag. If None, reads from env.
    """
    if enabled is None:
        enabled = _sounds_enabled()
    if not enabled:
        return

    try:
        import streamlit.components.v1 as components
        # Mount the JS once per page load; subsequent calls just trigger playback.
        components.html(_CUE_JS, height=0, width=0)
        # Trigger the cue via a second tiny HTML fragment that calls the function.
        trigger = (
            f"<script>window.__playScoreCue && window.__playScoreCue({event_type!r});</script>"
        )
        components.html(trigger, height=0, width=0)
    except Exception as exc:
        logger.debug("Sound cue suppressed (%s): %s", event_type, exc)


def render_sound_toggle() -> None:
    """Render a small toggle in the Streamlit UI to enable/disable sounds."""
    import streamlit as st
    import os

    current = _sounds_enabled()
    new_val = st.checkbox(
        "🔊 Sound cues",
        value=current,
        help="Play short browser-side sounds for point, undo, deuce, game, match, and reject events.",
        key="score_sound_toggle",
    )
    if new_val != current:
        os.environ["SCORE_ENABLE_SOUNDS"] = "true" if new_val else "false"
        st.rerun()
