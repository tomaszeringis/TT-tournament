"""
Spoken Commentary Component — browser-native speech synthesis for Streamlit.

Uses the Web Speech API (SpeechSynthesis) via a hidden Streamlit HTML component.
No network calls. No heavy dependencies. Works offline in modern browsers.
"""

import streamlit as st


def speak_commentary(
    text: str,
    key: str,
    voice: str = "default",
    lang: str = "en-US",
    rate: float = 1.0,
    pitch: float = 1.0,
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

    Returns:
        None. This is fire-and-forget; the browser handles playback.
    """
    if not text:
        return

    import streamlit.components.v1 as components

    # Escape text for safe JS embedding
    escaped_text = (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )

    html = f"""
    <div id="speak-{key}" style="display:none;"></div>
    <script>
    (function() {{
        const text = '{escaped_text}';
        const lang = '{lang}';
        const voiceName = '{voice}';
        const rate = {rate};
        const pitch = {pitch};

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
