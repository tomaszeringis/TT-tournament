"""
Spoken Commentary Component — browser-native speech synthesis for Streamlit.

Uses the Web Speech API (SpeechSynthesis) via a hidden Streamlit HTML component.
No network calls. No heavy dependencies. Works offline in modern browsers.
"""

import json
from pathlib import Path
import streamlit as st


def speak_commentary(
    text: str,
    key: str,
    voice: str = "default",
    lang: str = "en-US",
    rate: float = 1.0,
    pitch: float = 1.0,
    volume: float = 1.0,
    voice_profile_id: str = "browser_default",
) -> None:
    """
    Trigger browser-native speech synthesis for a short commentary line.

    Args:
        text: The text to speak.
        key: Unique Streamlit widget key (used for dedupe).
        voice: Browser voice name or "default".
        lang: BCP-47 language tag (e.g. "en-US", "en-GB").
        rate: Speech rate (0.1 to 10, default 1.0).
        pitch: Speech pitch (0 to 2, default 1.0).
        volume: Speech volume (0.0 to 1.0, default 1.0).
        voice_profile_id: Voice profile identifier for localStorage persistence.

    Returns:
        None. This is fire-and-forget; the browser handles playback.
    """
    if not text:
        return

    import streamlit.components.v1 as components

    escaped_text = json.dumps(text, ensure_ascii=False)

    html = f"""
    <div id="speak-{key}" style="display:none;"></div>
    <script>
    (function() {{
        const text = {escaped_text};
        const lang = '{lang}';
        const voiceName = '{voice}';
        const rate = {rate};
        const pitch = {pitch};
        const volume = {volume};
        const profileId = '{voice_profile_id}';

        if (!('speechSynthesis' in window)) {{
            console.warn('SpeechSynthesis not supported in this browser.');
            return;
        }}

        // Cancel any ongoing speech to avoid queue buildup
        window.speechSynthesis.cancel();

        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = lang;
        utter.rate = rate;
        utter.pitch = pitch;
        utter.volume = volume;

        if (voiceName && voiceName !== 'default') {{
            const voices = window.speechSynthesis.getVoices();
            const match = voices.find(v => v.name === voiceName || v.name.includes(voiceName));
            if (match) {{
                utter.voice = match;
            }}
        }}

        window.speechSynthesis.speak(utter);
    }})();
    </script>
    """

    # Render with zero size; the script runs in the browser context.
    components.html(html, height=0, width=0)


def play_local_audio(wav_path: str, *, key: str = "local_audio") -> None:
    """
    Play a locally synthesized WAV file via Streamlit st.audio().

    Args:
        wav_path: Path to the WAV file.
        key: Unique widget key.
    """
    if not wav_path:
        return
    try:
        st.audio(wav_path, format="audio/wav", start_time=0)
    except Exception as exc:
        logger = __import__("logging").getLogger(__name__)
        logger.debug("Local audio playback failed (%s): %s", wav_path, exc)


def speak_commentary_audio_file(audio_path: Path, *, key: str | None = None) -> None:
    """
    Play a WAV file via browser-native HTML audio autoplay.

    Uses base64-encoded audio data injected through a hidden Streamlit HTML
    component so the file plays automatically without manual user interaction.

    Args:
        audio_path: Path to the WAV file.
        key: Optional unique element id suffix.
    """
    if not audio_path or not Path(audio_path).exists():
        return
    try:
        import base64

        audio_bytes = Path(audio_path).read_bytes()
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        element_id = f"audio-{key or audio_path.name}"
        html = f"""
        <div id="{element_id}" style="display:none;"></div>
        <script>
        (function() {{
            const audio = new Audio('data:audio/wav;base64,{audio_b64}');
            audio.play().catch(function(err) {{
                console.warn('Autoplay blocked:', err);
            }});
        }})();
        </script>
        """
        import streamlit.components.v1 as components

        components.html(html, height=0, width=0)
    except Exception as exc:
        logger = __import__("logging").getLogger(__name__)
        logger.debug("Audio file playback failed (%s): %s", audio_path, exc)


def get_available_voices() -> list:
    """
    Return list of available SpeechSynthesis voices from the browser.

    Note: This must be called from a browser context. In Streamlit, voices
    may not be available until the page has fully loaded. Use with caution.
    """
    import streamlit.components.v1 as components

    html = """
    <script>
    (function() {
        const voices = window.speechSynthesis.getVoices();
        const names = voices.map(v => v.name + '|' + v.lang).join('\\n');
        window.parent.postMessage({type: 'streamlit:voices', voices: names}, '*');
    })();
    </script>
    """
    components.html(html, height=0, width=0)
    return []
