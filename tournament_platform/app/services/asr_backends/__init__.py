from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.app.services.asr_backends.faster_whisper_backend import FasterWhisperBackend

__all__ = ["ASRBackend", "BackendStatus", "FasterWhisperBackend"]

try:
    from tournament_platform.app.services.asr_backends.speechbrain_backend import SpeechBrainBackend

    __all__.append("SpeechBrainBackend")
except Exception:
    pass
