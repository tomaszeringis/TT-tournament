# Local-First Voice Scorekeeper Implementation Plan

## A. Current-State Findings

### Repository Structure
- **Main entry point**: `tournament_platform/app/main.py` — Streamlit multi-page app with navigation
- **Voice scorekeeper page**: `tournament_platform/app/pages/voice_scorekeeper.py` (55KB, ~1281 lines) — already exists with:
  - `st.audio_input` for push-to-talk capture
  - `UmpireEngine` for faster-whisper transcription
  - `IntentClassifier` for regex-based intent classification
  - `MatchManager` for in-memory score tracking
  - Manual scoring buttons (+/−) and undo
  - Game-by-game scoring with `match_score` utilities
  - Match result reporting via API
- **Match scoring service**: `tournament_platform/app/services/match_score.py` — pure functions for parsing/validating/summarizing game scores
- **Match manager**: `tournament_platform/services/match_manager.py` — `MatchManager` class with `MatchState`, `update_score()`, `_add_point()`, `undo_last_point()`, `reset_match()`
- **Voice event schema**: `tournament_platform/services/voice_event_schema.py` — `VoiceEvent` Pydantic model, `EventType` enum, `EventFactory`
- **Intent classifier**: `tournament_platform/multimodal_ai/intent_classifier.py` — regex-based `IntentClassifier` with `IntentType`/`IntentResult`
- **Umpire engine**: `tournament_platform/services/umpire_engine.py` — async audio capture + faster-whisper + Ollama + RealtimeTTS pipeline
- **Voice transcription**: `tournament_platform/services/voice_transcription.py` — Vosk-based transcription for operator console
- **Config**: `tournament_platform/config/__init__.py` — `Settings` with `WHISPER_MODEL_SIZE`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`
- **Dependencies**: `pyproject.toml` has `faster-whisper` in main deps, `streamlit-webrtc` in `[project.optional-dependencies] live`
- **Tests**: `tests/test_match_score.py`, `tests/test_multimodal/test_voice_scorekeeper.py`, `tests/test_multimodal/test_voice_event_schema.py`

### Key Observations
1. The existing `voice_scorekeeper.py` already uses `st.audio_input` (push-to-talk), not continuous listening.
2. `UmpireEngine` loads faster-whisper eagerly in `__init__`, which can block startup.
3. `MatchManager.update_score()` uses keyword matching, not structured score phrase parsing.
4. No explicit support for "five four" → set score 5-4, "six all" → 6-6, etc.
5. No `streamlit-webrtc` integration yet.
6. The `VoiceEvent` schema exists but is not fully utilized in the voice scorekeeper page.
7. Manual scoring buttons call `MatchManager._add_point()` directly, bypassing `update_score()`.

---

## B. Proposed File Changes

### New Files
| File | Purpose |
|------|---------|
| `tournament_platform/app/services/voice_parser.py` | Parse transcripts into structured `VoiceScoreEvent` objects |
| `tournament_platform/app/services/voice_audio.py` | Audio frame buffering, VAD/silence detection, chunking |
| `tournament_platform/app/services/voice_asr.py` | Local ASR wrapper around faster-whisper with lazy loading |
| `tests/test_voice_parser.py` | Unit tests for score phrase and command parsing |

### Modified Files
| File | Changes |
|------|---------|
| `tournament_platform/app/pages/voice_scorekeeper.py` | Add streamlit-webrtc section, wire parsed events into MatchManager, add UI feedback |
| `tournament_platform/services/match_manager.py` | Add `apply_voice_event()` method, extend `update_score()` to accept structured events |
| `tournament_platform/pyproject.toml` | Ensure `streamlit-webrtc` is in main dependencies or documented |
| `tournament_platform/requirements.txt` | Add `streamlit-webrtc`, `av`, `numpy` if missing |

---

## C. Implementation Phases

### Phase 1 — Voice Parser (`voice_parser.py`)

Create a new module with a `VoiceScoreEvent` dataclass and `VoiceParser` class.

**`VoiceScoreEvent` structure:**
```python
@dataclass
class VoiceScoreEvent:
    type: str  # "set_score", "increment", "undo", "unknown"
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    player: Optional[str] = None  # "A" or "B"
    raw_text: str = ""
    confidence: float = 0.0
```

**Supported score phrases:**
- `"five four"` → `set_score(5, 4)`
- `"six all"` → `set_score(6, 6)`
- `"ten eight"` → `set_score(10, 8)`
- `"eleven nine"` → `set_score(11, 9)`
- `"deuce"` → `set_score(equal_score)` only if current score allows deuce (both ≥ 10)
- `"set score seven five"` → `set_score(7, 5)`
- `"for two"` → `set_score(4, 2)` (ASR correction: "for" → "four")
- `"oh three"` / `"zero three"` / `"love three"` → `set_score(0, 3)`

**Supported commands:**
- `"undo"` → `undo`
- `"repeat"` → `unknown` (or repeat last action)
- `"last point to player one"` → `increment("A")`
- `"last point to player two"` → `increment("B")`
- `"point player one"` → `increment("A")`
- `"point player two"` → `increment("B")`
- `"stop listening"` → `unknown` (UI control, not a score event)

**Normalization rules:**
- `"for"` → `"four"` when used as a score number
- `"to"` / `"too"` / `"two"` → `"two"` when used as a score number
- `"oh"` / `"zero"` / `"love"` → `0`
- `"all"` → equal score
- Numeric digits in transcripts should work too (e.g., `"5 4"` → `set_score(5, 4)`)

**Parser logic:**
1. Normalize transcript: lowercase, strip whitespace
2. Apply ASR mistake corrections
3. Check for command patterns first (undo, point, etc.)
4. Check for score patterns (number word pairs, "all", "deuce")
5. Return `VoiceScoreEvent` with type and parsed values

### Phase 2 — Audio Buffering (`voice_audio.py`)

Create a module for receiving WebRTC audio frames and producing utterance chunks.

**Key components:**
- `AudioChunk` dataclass: `frames: List[bytes]`, `duration_ms: float`, `timestamp: float`
- `VoiceAudioBuffer` class:
  - `push_frame(frame: AudioFrame)` — convert to mono PCM 16kHz, append to buffer
  - `check_silence()` — simple amplitude thresholding or energy-based VAD
  - `emit_chunk()` — return complete chunk when silence detected or max duration reached
  - Thread-safe with `threading.Lock`

**Chunking strategy:**
- Target chunk duration: 1–3 seconds
- Max chunk duration: 5 seconds (to avoid excessive latency)
- Silence threshold: configurable, default based on RMS energy
- Min speech duration: 300ms before considering a chunk valid

**Frame conversion:**
- Input: `av.AudioFrame` from streamlit-webrtc (typically 48kHz stereo float32)
- Output: mono PCM 16kHz int16 bytes for faster-whisper

### Phase 3 — Local ASR Wrapper (`voice_asr.py`)

Create a module wrapping faster-whisper with lazy loading and configurable settings.

**`LocalASR` class:**
```python
class LocalASR:
    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._load_lock = threading.Lock()

    def _load_model(self) -> None:
        """Lazy load the WhisperModel."""
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                    )

    def transcribe_chunk(self, audio_bytes: bytes) -> str:
        """Transcribe a chunk of audio and return normalized text."""
        self._load_model()
        # Save to temp WAV, transcribe, return text
        ...

    def transcribe_with_vad(self, audio_bytes: bytes) -> str:
        """Transcribe with VAD filtering if available."""
        ...
```

**Environment variable overrides:**
- `VOICE_ASR_MODEL_SIZE` → default `"base.en"`
- `VOICE_ASR_DEVICE` → default `"cpu"`
- `VOICE_ASR_COMPUTE_TYPE` → default `"int8"`

**Error handling:**
- If model loading fails, raise a clear exception with setup instructions
- If transcription fails, return empty string and log error
- Never crash the Streamlit app — show warning in UI

### Phase 4 — streamlit-webrtc Integration

Add a new section to `voice_scorekeeper.py` for continuous listening.

**UI elements:**
- Toggle: "Enable Voice Scoring" (default off)
- Start Listening / Stop Listening buttons
- Listening status indicator (green dot when active)
- Last heard phrase (raw transcript)
- Parsed interpretation
- Last accepted score update
- Warnings for rejected/uncertain transcripts
- Debug expander with recent voice events and ASR timings

**WebRTC setup:**
```python
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase

class VoiceAudioProcessor(AudioProcessorBase):
    def __init__(self) -> None:
        self.audio_buffer = VoiceAudioBuffer()
        self.asr = LocalASR()
        self.parser = VoiceParser()
        self.queue = queue.Queue()

    def recv_audio(self, frames: List[AudioFrame]) -> None:
        for frame in frames:
            chunk = self.audio_buffer.push_frame(frame)
            if chunk:
                # Transcribe in background thread
                threading.Thread(
                    target=self._transcribe_chunk,
                    args=(chunk,),
                    daemon=True,
                ).start()

    def _transcribe_chunk(self, chunk: AudioChunk) -> None:
        text = self.asr.transcribe_chunk(chunk.to_pcm_bytes())
        if text:
            event = self.parser.parse(text)
            self.queue.put((text, event))
```

**Thread-safe queue between WebRTC callback and Streamlit UI:**
- Use `queue.Queue` for passing events from audio callback to UI
- In the main Streamlit loop, poll the queue and update `st.session_state`
- Never do ASR work directly inside `recv_audio()`

### Phase 5 — MatchManager Integration

Extend `MatchManager` to accept structured `VoiceScoreEvent` objects.

**New method:**
```python
def apply_voice_event(self, event: VoiceScoreEvent) -> Tuple[bool, str]:
    """Apply a parsed voice event to match state."""
    if event.type == "set_score":
        return self._set_score(event.score_a, event.score_b)
    elif event.type == "increment":
        return self._add_point(event.player)
    elif event.type == "undo":
        return self.undo_last_point()
    else:
        return False, "Unknown voice event"
```

**New method:**
```python
def _set_score(self, score_a: int, score_b: int) -> Tuple[bool, str]:
    """Set the current game score directly."""
    # Validate: no ties, non-negative, reasonable bounds
    if score_a == score_b:
        return False, "Scores cannot be tied"
    if score_a < 0 or score_b < 0:
        return False, "Scores cannot be negative"
    if score_a > 21 or score_b > 21:
        return False, "Score exceeds maximum"

    # Save history
    self.state.match_history.append({
        "action": "score_set",
        "previous_score_a": self.state.score_a,
        "previous_score_b": self.state.score_b,
        "previous_set": self.state.current_set,
        "previous_sets_a": self.state.sets_a,
        "previous_sets_b": self.state.sets_b,
    })

    self.state.score_a = score_a
    self.state.score_b = score_b
    return True, f"Score set to {score_a}-{score_b}"
```

**Game-winning detection:**
- After any score change, check if `score_a >= 11 or score_b >= 11` and `abs(score_a - score_b) >= 2`
- If game won, increment `sets_a` or `sets_b`, reset game score to 0-0, increment `current_set`
- If match won (best of 3 or 5, configurable), mark match complete

**History stack for undo:**
- Already exists in `MatchState.match_history`
- `undo_last_point()` already restores previous state
- Extend to handle `score_set` actions

### Phase 6 — UI Feedback

Add to `voice_scorekeeper.py`:

```python
# Voice scoring section
with st.expander("🎤 Voice Scoring", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        voice_enabled = st.toggle("Enable Voice Scoring", value=False)
    with col2:
        if voice_enabled:
            if st.button("Start Listening", type="primary"):
                start_webrtc()
            if st.button("Stop Listening"):
                stop_webrtc()

    if voice_enabled:
        st.caption("Listening for score commands...")

        # Show last transcript
        if st.session_state.get("last_voice_transcript"):
            st.info(f"Last heard: **{st.session_state.last_voice_transcript}**")

        # Show parsed interpretation
        if st.session_state.get("last_voice_event"):
            event = st.session_state.last_voice_event
            if event.type == "set_score":
                st.success(f"Parsed: Set score to {event.score_a}-{event.score_b}")
            elif event.type == "increment":
                st.success(f"Parsed: Point to Player {event.player}")
            elif event.type == "undo":
                st.success("Parsed: Undo last point")
            else:
                st.warning(f"Parsed: Unknown command")

        # Show last accepted update
        if st.session_state.get("last_voice_feedback"):
            st.caption(f"Last update: {st.session_state.last_voice_feedback}")

        # Debug expander
        with st.expander("🔍 Voice Debug"):
            if st.session_state.get("voice_event_log"):
                for entry in st.session_state.voice_event_log[-10:]:
                    st.json(entry)
```

### Phase 7 — Tests

**New test file: `tests/test_voice_parser.py`**

Test cases:
```python
class TestVoiceParser:
    def test_parse_five_four(self):
        event = parser.parse("five four")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4

    def test_parse_six_all(self):
        event = parser.parse("six all")
        assert event.type == "set_score"
        assert event.score_a == 6
        assert event.score_b == 6

    def test_parse_ten_eight(self):
        event = parser.parse("ten eight")
        assert event.type == "set_score"
        assert event.score_a == 10
        assert event.score_b == 8

    def test_parse_eleven_nine(self):
        event = parser.parse("eleven nine")
        assert event.type == "set_score"
        assert event.score_a == 11
        assert event.score_b == 9

    def test_parse_for_two(self):
        event = parser.parse("for two")
        assert event.type == "set_score"
        assert event.score_a == 4
        assert event.score_b == 2

    def test_parse_point_player_one(self):
        event = parser.parse("point player one")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_last_point_player_two(self):
        event = parser.parse("last point player two")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_undo(self):
        event = parser.parse("undo")
        assert event.type == "undo"

    def test_parse_set_score_seven_five(self):
        event = parser.parse("set score seven five")
        assert event.type == "set_score"
        assert event.score_a == 7
        assert event.score_b == 5

    def test_parse_oh_three(self):
        event = parser.parse("oh three")
        assert event.type == "set_score"
        assert event.score_a == 0
        assert event.score_b == 3

    def test_parse_numeric_digits(self):
        event = parser.parse("5 4")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4

    def test_parse_deuce_when_allowed(self):
        # Current score 10-10, deuce is valid
        event = parser.parse("deuce", current_score_a=10, current_score_b=10)
        assert event.type == "set_score"
        assert event.score_a == 10
        assert event.score_b == 10

    def test_parse_deuce_when_not_allowed(self):
        # Current score 5-3, deuce should be rejected
        event = parser.parse("deuce", current_score_a=5, current_score_b=3)
        assert event.type == "unknown"
```

### Phase 8 — Dependencies and Documentation

**Dependencies:**
- `streamlit-webrtc>=0.45.0` — already in `[project.optional-dependencies] live`, move to main or keep documented
- `av>=12.0.0` — already in `[project.optional-dependencies] video`
- `numpy>=1.24.0` — already in `[project.optional-dependencies] video`

**Documentation additions:**
- `VOICE_SCOREKEEPER.md` — new file with:
  - How to enable voice scoring
  - Required microphone permissions
  - Local deployment notes
  - Suggested model settings for CPU and GPU
  - Known limitations in noisy tournament environments
  - How to disable voice scoring
  - Troubleshooting faster-whisper installation

---

## D. Acceptance Criteria Mapping

| # | Criterion | Implementation |
|---|-----------|----------------|
| 1 | App runs without voice scoring enabled | Voice scoring is behind a toggle; all existing code paths unchanged |
| 2 | Manual scorekeeping still works | Manual buttons call `MatchManager._add_point()` directly |
| 3 | User can start voice listening from match screen | WebRTC section with Start/Stop buttons |
| 4 | "five four" updates score to 5-4 | `VoiceParser` → `VoiceScoreEvent(set_score, 5, 4)` → `MatchManager._set_score()` |
| 5 | "six all" updates score to 6-6 | Same path, normalized "all" → equal score |
| 6 | "Undo" rolls back most recent voice-applied change | `VoiceParser` → `VoiceScoreEvent(undo)` → `MatchManager.undo_last_point()` |
| 7 | "eleven eight" triggers game-completion logic | `_set_score()` checks win condition, increments sets, resets game |
| 8 | Match completion uses existing app logic | Game scores stored in `st.session_state.in_progress_game_scores`, submitted via existing API |
| 9 | If faster-whisper fails, app shows warning and manual scoring works | `LocalASR` catches import/model errors, shows warning in UI |
| 10 | ASR work does not block WebRTC callback | Transcription runs in background `threading.Thread` |
| 11 | Parser tests pass | `tests/test_voice_parser.py` with all sample cases |
| 12 | Code is modular and documented | New modules in `app/services/`, docstrings, type hints |

---

## E. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| streamlit-webrtc compatibility | Medium | Medium | Keep behind toggle; test on target Streamlit version |
| faster-whisper model download/load time | High | Low | Lazy loading with clear UI indicator |
| Audio format conversion issues | Medium | Medium | Extensive logging, fallback to st.audio_input |
| Thread safety in Streamlit | Medium | High | Use `queue.Queue` + session state polling, not shared mutable state |
| Breaking existing voice_scorekeeper.py | Low | High | Incremental changes, preserve all existing UI sections |

---

## F. Implementation Order

1. **`voice_parser.py`** — zero dependencies, pure logic, easy to test
2. **`tests/test_voice_parser.py`** — validate parser before wiring anything
3. **`voice_audio.py`** — audio processing, testable with synthetic frames
4. **`voice_asr.py`** — ASR wrapper, testable with mock model
5. **`match_manager.py`** — add `apply_voice_event()` and `_set_score()`
6. **`voice_scorekeeper.py`** — add WebRTC section, wire everything together
7. **Dependencies & docs** — final step

---

## G. File Summary

### New files to create:
- `tournament_platform/app/services/voice_parser.py`
- `tournament_platform/app/services/voice_audio.py`
- `tournament_platform/app/services/voice_asr.py`
- `tests/test_voice_parser.py`
- `VOICE_SCOREKEEPER.md` (documentation)

### Files to modify:
- `tournament_platform/services/match_manager.py` — add `apply_voice_event()`, `_set_score()`
- `tournament_platform/app/pages/voice_scorekeeper.py` — add WebRTC section, UI feedback
- `pyproject.toml` — document streamlit-webrtc dependency
- `requirements.txt` — add streamlit-webrtc, av, numpy if missing
