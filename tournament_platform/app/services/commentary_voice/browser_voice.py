"""
Browser voice picker JS and localStorage logic for the commentary voice system.
"""

from __future__ import annotations

import json


def build_voice_picker_html(profile_id: str, volume: float) -> str:
    escaped_profile = json.dumps(profile_id)
    escaped_volume = json.dumps(volume)
    return f"""
    <div id="voice-picker-{profile_id}" style="display:none;"></div>
    <script>
    (function() {{
        const profileId = {escaped_profile};
        const volume = {escaped_volume};

        function getSelectedVoice() {{
            const stored = localStorage.getItem('selectedCommentaryVoice');
            return stored || 'default';
        }}

        function setSelectedVoice(name) {{
            localStorage.setItem('selectedCommentaryVoice', name);
        }}

        function speakWithProfile(text) {{
            if (!('speechSynthesis' in window)) {{
                console.warn('SpeechSynthesis not supported.');
                return;
            }}
            window.speechSynthesis.cancel();
            const utter = new SpeechSynthesisUtterance(text);
            utter.lang = 'en-US';
            utter.rate = 1.0;
            utter.pitch = 1.0;
            utter.volume = volume;
            const voices = window.speechSynthesis.getVoices();
            const selectedName = getSelectedVoice();
            if (selectedName && selectedName !== 'default') {{
                const match = voices.find(v => v.name === selectedName || v.name.includes(selectedName));
                if (match) {{
                    utter.voice = match;
                }}
            }}
            window.speechSynthesis.speak(utter);
        }}

        window.__commentaryVoicePicker = {{
            getSelectedVoice: getSelectedVoice,
            setSelectedVoice: setSelectedVoice,
            speakWithProfile: speakWithProfile,
        }};
    }})();
    </script>
    """
