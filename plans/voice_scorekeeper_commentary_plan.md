# Voice Scorekeeper — Spoken Commentary Architecture Plan

## 1. Current Repo Findings

### 1.1 Voice Scorekeeper Page (`tournament_platform/app/pages/voice_scorekeeper.py`)
- **Length**: ~1,100 lines. Single-page Streamlit app combining voice input, manual scoring, and match reporting.
- **Scoring flow**:
  - Manual score buttons call `st.session_state.match_manager._add_point("A")` or `_add_point("B")` directly.
  - `_add_point` returns `(success, msg)` where `msg` is a plain string like `"Point for Player A. Score is now 5 to 3"`.
  - Undo buttons call `match_manager.undo_last_point()`.
  - Reset calls `match_manager.reset_match()`.
  - Game-by-game scoring uses `match_score.py` utilities (`validate_game_score`, `summarize_match`).
- **Session state keys**:
  - `match_manager` — `MatchManager` instance holding `MatchState`.
  - `last_feedback` — last action message string.
  - `last_audio_hash` — SHA-256 of last processed audio bytes (prevents duplicate voice processing).
  - `in_progress_game_scores` — dict keyed by `match_id` → list of `(score1, score2)` tuples.
  - `voice_selected_match_id`, `voice_selected_player1_name`, etc.
- **Existing TTS**:
  - `speak_text(text)` at line 75 uses `pyttsx3` in a **blocking** fashion (`engine.runAndWait()`).
  - Called directly inside button handlers (e.g., after `_add_point`, after undo, after reset).
  - No rerun deduplication: every Streamlit rerun that re-executes the button block would re-speak if the button state persists.
  - No settings/controls for enabling/disabling commentary, voice style, or verbosity.

### 1.2 MatchManager (`tournament_platform/services/match_manager.py`)
- `MatchState` dataclass holds `score_a`, `score_b`, `sets_a`, `sets_b`, `current_set`, `match_history`.
- `_add_point(player)`:
  - Appends history entry.
  - Increments score.
  - Checks `score >= 11` and `abs(diff) >= 2` but does **nothing** with that info (pass).
  - Returns generic message: `"Point for {name}. Score is now {a} to {b}"`.
- `undo_last_point()`: restores previous state from history.
- `reset_match()`: resets to initial `MatchState`.
- **No detection of**: deuce, advantage, game point, match point, game won, match won.

### 1.3 Match Score Utilities (`tournament_platform/app/services/match_score.py`)
- `parse_game_score(text)` — parses game scores from text.
- `validate_game_score(score1, score2)` — validates table tennis game rules (winner >= 11, lead >= 2, no ties).
- `summarize_match(game_scores)` — returns `player1_games`, `player2_games`, `winner_side`, `is_complete`, `score_string`.
- **No point-level commentary logic**.

### 1.4 Existing TTS / Audio Dependencies
- `pyproject.toml` and `requirements.txt` already include:
  - `pyttsx3>=2.90` — offline TTS (used by current `speak_text`).
  - `RealtimeTTS>=0.4.1` — streaming TTS (used by `UmpireEngine` with `GTTSEngine`).
  - `faster-whisper>=1.0.0` — local STT.
  - `SpeechRecognition>=3.10.0`, `PyAudio>=0.2.11` — audio capture.
- `tournament_platform/services/settings.py` has:
  - `ENABLE_SPOKEN_CONFIRMATION: bool = _get_env_bool("ENABLE_SPOKEN_CONFIRMATION", False)` — **already exists but unused in voice_scorekeeper**.
- `tournament_platform/config/__init__.py` has TTS-related settings (`TTS_SAMPLE_RATE`, `TTS_CHUNK_SIZE`).

### 1.5 UmpireEngine (`tournament_platform/services/umpire_engine.py`)
- Real-time voice commentary engine using `faster-whisper` + `Ollama` + `RealtimeTTS`.
- Uses `GTTSEngine` (Google TTS) by default — requires internet.
- Designed for continuous real-time mode, not for discrete score-click events.
- **Not suitable for MVP** because:
  - Requires Ollama running.
  - Requires internet for Google TTS.
  - Overkill for short deterministic commentary lines.

### 1.6 Existing Plans
- `plans/voice_scorekeeper_coaching_plan.md` — focuses on coaching mode, intent classification, RAG.
- `plans/voice_scorekeeper_realtime_plan.md` — real-time umpire commentary.
- `plans/voice_scorekeeper_dataset_training_plan.md` — dataset-backed training.
- None of these address the specific need for **deterministic, low-latency spoken commentary on score button clicks**.

---

## 2. Product Behavior — Commentary Events

| Event | Example Commentary | Priority |
|-------|-------------------|----------|
| Point to Player A | "Point to Anna." | Normal |
| Point to Player B | "Point to Mark." | Normal |
| Score correction / undo | "Point removed from Anna." | Normal |
| Deuce (10–10, 11–11, etc.) | "Deuce." | High |
| Advantage Player A | "Advantage Anna." | High |
| Advantage Player B | "Advantage Mark." | High |
| Game point Player A | "Game point, Anna." | High |
| Game point Player B | "Game point, Mark." | High |
| Game won Player A | "Game to Anna, 11–8." | High |
| Game won Player B | "Game to Mark, 11–9." | High |
| Match won Player A | "Match complete. Anna wins 3 games to 1." | High |
| Match won Player B | "Match complete. Mark wins 3 games to 1." | High |
| Invalid score action | "Invalid score." | Low |
| Score reset | "Match reset. Score is 0 to 0." | Normal |
| Match submitted | "Match result submitted." | Normal |

### Commentary Style Rules
- **Short**: 3–8 words for normal events, up to 12 words for match-end.
- **Natural**: conversational, not robotic.
- **Non-annoying**: no repeated exclamations, no auto-play on page load.
- **Optional**: user can disable entirely.
- **Configurable**: voice style and verbosity selectors.
- **Deterministic by default**: hand-written templates, no LLM required.
- **Safe for tournaments**: no external API calls, no data leaves the machine.

---

## 3. Human Interaction Requirements

1. **Trigger on explicit user action**: commentary speaks only when the user clicks a score control or confirms a score action.
2. **No auto-play on page load**: do not speak when the page first renders.
3. **No duplicate speech on reruns**: Streamlit reruns the entire script on every interaction. We must deduplicate.
4. **No stale events after refresh**: session state is ephemeral; commentary must not replay old events.
5. **Respect disable setting**: if commentary is disabled, no TTS payload is generated or rendered.

---

## 4. UX Controls

Add a **Commentary Settings** section in the Voice Scorekeeper page, above the score controls:

```python
# Session state defaults
if "commentary_enabled" not in st.session_state:
    st.session_state.commentary_enabled = False  # OFF by default for safety
if "commentary_style" not in st.session_state:
    st.session_state.commentary_style = "neutral"  # neutral | coach | announcer | minimal
if "commentary_verbosity" not in st.session_state:
    st.session_state.commentary_verbosity = "standard"  # minimal | standard | expressive
if "commentary_voice" not in st.session_state:
    st.session_state.commentary_voice = "default"
if "commentary_language" not in st.session_state:
    st.session_state.commentary_language = "en"
if "last_commentary_event_id" not in st.session_state:
    st.session_state.last_commentary_event_id = None
if "pending_commentary" not in st.session_state:
    st.session_state.pending_commentary = None
```

### Controls
| Control | Type | Default | Options |
|---------|------|---------|---------|
| Spoken commentary | `st.toggle` | `False` | On / Off |
| Voice style | `st.selectbox` | `Neutral` | Neutral, Coach, Announcer, Minimal |
| Verbosity | `st.selectbox` | `Standard` | Minimal, Standard, Expressive |
| Mute | `st.button` (toggles state) | Unmuted | Mute / Unmute |
| Replay last | `st.button` | — | Replays `pending_commentary` |
| Language | `st.selectbox` | `English` | English (extensible) |

### Default Policy
- **Commentary is OFF by default** to avoid unexpected audio in tournament environments.
- When enabled, default style is `Neutral`, verbosity is `Standard`.
- Mute button temporarily suppresses speech without changing the enabled state.

---

## 5. Commentary Generation Architecture

### 5.1 New Service: `tournament_platform/services/commentary_service.py`

Pure-Python module. No Streamlit imports. No network calls. Deterministic templates.

#### Proposed Functions

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

class ScoreMoment(Enum):
    POINT_A = "point_a"
    POINT_B = "point_b"
    UNDO = "undo"
    DEUCE = "deuce"
    ADVANTAGE_A = "advantage_a"
    ADVANTAGE_B = "advantage_b"
    GAME_POINT_A = "game_point_a"
    GAME_POINT_B = "game_point_b"
    GAME_WON_A = "game_won_a"
    GAME_WON_B = "game_won_b"
    MATCH_WON_A = "match_won_a"
    MATCH_WON_B = "match_won_b"
    INVALID = "invalid"
    RESET = "reset"
    MATCH_SUBMITTED = "match_submitted"

class CommentaryStyle(str, Enum):
    NEUTRAL = "neutral"
    COACH = "coach"
    ANNOUNCER = "announcer"
    MINIMAL = "minimal"

class CommentaryVerbosity(str, Enum):
    MINIMAL = "minimal"      # only deuce/game/match
    STANDARD = "standard"    # point + score
    EXPRESSIVE = "expressive" # adds short rally-style phrases

@dataclass
class CommentaryLine:
    text: str
    event_type: str
    priority: int          # 1=low, 2=normal, 3=high
    should_speak: bool
    dedupe_key: str
    event_id: str
    ssml_text: Optional[str] = None

@dataclass
class SpokenScoreState:
    score_a: int
    score_b: int
    sets_a: int
    sets_b: int
    current_set: int
    player_a: str
    player_b: str
    player_a_id: Optional[int]
    player_b_id: Optional[int]
    match_history: List[Dict]

class CommentaryService:
    def classify_score_moment(self, state: SpokenScoreState, previous_state: Optional[SpokenScoreState] = None) -> ScoreMoment:
        ...

    def format_score_spoken(self, state: SpokenScoreState) -> str:
        ...

    def get_commentary_templates(self, style: CommentaryStyle, moment: ScoreMoment, verbosity: CommentaryVerbosity) -> List[str]:
        ...

    def choose_commentary_template(self, templates: List[str]) -> str:
        ...

    def build_score_commentary(
        self,
        event_type: str,
        state: SpokenScoreState,
        settings: dict,
        event_id: str,
    ) -> CommentaryLine:
        ...

    def should_speak_commentary(self, last_event_id: Optional[str], current_event_id: str, settings: dict) -> bool:
        ...
```

#### Template Examples

```python
TEMPLATES = {
    (ScoreMoment.POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Point to {player_a}. {score}.",
        "{player_a} scores. {score}.",
    ],
    (ScoreMoment.DEUCE, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Deuce.",
    ],
    (ScoreMoment.ADVANTAGE_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Advantage {player_a}.",
    ],
    (ScoreMoment.GAME_POINT_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Game point, {player_a}. {score}.",
    ],
    (ScoreMoment.GAME_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Game to {player_a}, {score}.",
    ],
    (ScoreMoment.MATCH_WON_A, CommentaryStyle.NEUTRAL, CommentaryVerbosity.STANDARD): [
        "Match complete. {player_a} wins {sets_a} games to {sets_b}.",
    ],
}
```

### 5.2 Score Moment Detection Logic

```python
def classify_score_moment(self, state: SpokenScoreState, previous_state: Optional[SpokenScoreState] = None) -> ScoreMoment:
    a, b = state.score_a, state.score_b
    prev_a = previous_state.score_a if previous_state else a
    prev_b = previous_state.score_b if previous_state else b

    # Determine who scored
    if a > prev_a:
        scorer = "A"
    elif b > prev_b:
        scorer = "B"
    else:
        scorer = None  # undo or reset

    # Game won detection (first to 11, win by 2)
    if (a >= 11 or b >= 11) and abs(a - b) >= 2:
        if scorer == "A":
            # Check match won
            if state.sets_a >= 3:
                return ScoreMoment.MATCH_WON_A
            return ScoreMoment.GAME_WON_A
        elif scorer == "B":
            if state.sets_b >= 3:
                return ScoreMoment.MATCH_WON_B
            return ScoreMoment.GAME_WON_B

    # Game point detection (10 to opponent's <= 9, or 10-10 with scorer at 10)
    if scorer == "A" and a >= 10 and b <= 9:
        return ScoreMoment.GAME_POINT_A
    if scorer == "B" and b >= 10 and a <= 9:
        return ScoreMoment.GAME_POINT_B

    # Advantage detection (10-10 or higher, one point ahead)
    if a >= 10 and b >= 10:
        if a > b:
            return ScoreMoment.ADVANTAGE_A
        elif b > a:
            return ScoreMoment.ADVANTAGE_B
        else:
            return ScoreMoment.DEUCE

    # Deuce detection (10-10)
    if a == 10 and b == 10:
        return ScoreMoment.DEUCE

    # Normal point
    if scorer == "A":
        return ScoreMoment.POINT_A
    elif scorer == "B":
        return ScoreMoment.POINT_B

    return ScoreMoment.INVALID
```

**Note**: The current `MatchManager._add_point` does not track previous score state in a structured way. We will either:
- (a) Add a `previous_state` snapshot to `MatchState` before each point, or
- (b) Compute the moment from `match_history` (which already stores `previous_score_a/b`).

Option (b) is safer and requires fewer changes to `MatchManager`.

---

## 6. Data Structures

### 6.1 `CommentarySettings` (dataclass)
```python
@dataclass
class CommentarySettings:
    enabled: bool = False
    style: CommentaryStyle = CommentaryStyle.NEUTRAL
    verbosity: CommentaryVerbosity = CommentaryVerbosity.STANDARD
    voice: str = "default"
    language: str = "en"
    muted: bool = False
```

### 6.2 `CommentaryEvent`
```python
@dataclass
class CommentaryEvent:
    event_id: str           # UUID or hash
    event_type: str         # "point_a", "undo", "game_won", etc.
    timestamp: float        # time.monotonic()
    state_snapshot: SpokenScoreState
    previous_state_snapshot: Optional[SpokenScoreState]
```

### 6.3 `CommentaryLine`
```python
@dataclass
class CommentaryLine:
    text: str
    event_type: str
    priority: int
    should_speak: bool
    dedupe_key: str
    event_id: str
    ssml_text: Optional[str] = None
```

### 6.4 `SpokenScoreState`
```python
@dataclass
class SpokenScoreState:
    score_a: int
    score_b: int
    sets_a: int
    sets_b: int
    current_set: int
    player_a: str
    player_b: str
    player_a_id: Optional[int]
    player_b_id: Optional[int]
```

---

## 7. TTS Implementation Options

### 7.1 Recommended MVP Approach: Browser-Native Speech Synthesis via Streamlit Component

**Why browser-native?**
- No Python-side blocking (`pyttsx3.runAndWait()` blocks the Streamlit script).
- No external API required.
- No heavy dependencies.
- Works offline (browser has built-in voices).
- Low latency for short phrases.

**Implementation**:
- Create a tiny custom Streamlit component: `tournament_platform/app/components/spoken_commentary.py`.
- The component renders an invisible `<div>` and uses `window.speechSynthesis.speak()` via JavaScript.
- Python side passes the text to the component via `component_value`.
- Component returns `spoken: bool` to confirm playback.

```python
# spoken_commentary.py
import streamlit as st

def speak_commentary(text: str, key: str, voice: str = "default", lang: str = "en-US") -> bool:
    """
    Render a hidden Streamlit component that triggers browser speech synthesis.
    Returns True if the browser reported speech start, False otherwise.
    """
    import streamlit.components.v1 as components

    html = f"""
    <div id="speak-{key}" style="display:none;"></div>
    <script>
    (function() {{
        const text = {repr(text)};
        const lang = {repr(lang)};
        const voiceName = {repr(voice)};
        if ('speechSynthesis' in window) {{
            const utter = new SpeechSynthesisUtterance(text);
            utter.lang = lang;
            if (voiceName && voiceName !== 'default') {{
                const voices = speechSynthesis.getVoices();
                const match = voices.find(v => v.name === voiceName || v.name.includes(voiceName));
                if (match) utter.voice = match;
            }}
            utter.rate = 1.0;
            utter.pitch = 1.0;
            speechSynthesis.speak(utter);
            window.parent.postMessage({{type: 'streamlit:speechSpoken', key: {repr(key)}}}, '*');
        }} else {{
            window.parent.postMessage({{type: 'streamlit:speechUnsupported', key: {repr(key)}}}, '*');
        }}
    }})();
    </script>
    """
    components.html(html, height=0, width=0)
    return False  # We cannot reliably get the return value from components.html in Streamlit
```

**Caveat**: `components.html` is fire-and-forget. We cannot reliably get a callback. Instead, we use a **dedupe + render** pattern:
1. Python computes the commentary text.
2. Python stores it in `st.session_state.pending_commentary`.
3. At the bottom of the page, if `pending_commentary` exists and settings allow, render the component.
4. After rendering, clear `pending_commentary` so it doesn't render again on rerun.

### 7.2 Fallback: `pyttsx3` (Existing)
- Keep `speak_text()` as a fallback for environments where browser speech is unavailable.
- Make it non-blocking by running in a thread:
  ```python
  import threading
  def speak_text_async(text: str) -> None:
      threading.Thread(target=lambda: _speak_text_blocking(text), daemon=True).start()
  ```
- **Do not use as primary** because:
  - Blocks Python GIL (even in thread, can interfere with Streamlit).
  - No voice selection on some platforms.
  - No language support.

### 7.3 Future: `RealtimeTTS` / Local TTS
- Already in `requirements.txt`.
- Could be used for higher-quality voices.
- Requires more setup; defer to Phase 5+.

### 7.4 No Cloud APIs
- Do not use Google TTS, Azure TTS, or ElevenLabs in MVP.
- No internet required at runtime.

---

## 8. Streamlit Rerun Safety Mechanism

### 8.1 Problem
Streamlit reruns the entire script on every widget interaction. Without deduplication, every rerun would re-speak the last commentary.

### 8.2 Solution: Event-ID-Based Dedupe

```python
import uuid

# In voice_scorekeeper.py, when a score button is clicked:
if st.button("➕", key="add_point_a", use_container_width=True):
    # 1. Generate unique event ID BEFORE mutating state
    event_id = str(uuid.uuid4())
    prev_state = copy.deepcopy(st.session_state.match_manager.state)

    # 2. Mutate state
    success, msg = st.session_state.match_manager._add_point("A")
    new_state = st.session_state.match_manager.state

    # 3. Build commentary
    commentary = commentary_service.build_score_commentary(
        event_type="point_a",
        state=SpokenScoreState.from_match_state(new_state),
        previous_state=SpokenScoreState.from_match_state(prev_state),
        settings=current_settings,
        event_id=event_id,
    )

    # 4. Store pending commentary ONLY if this event hasn't been spoken
    if commentary_service.should_speak_commentary(
        last_event_id=st.session_state.get("last_commentary_event_id"),
        current_event_id=event_id,
        settings=current_settings,
    ):
        st.session_state.pending_commentary = commentary
        st.session_state.last_commentary_event_id = event_id
    else:
        st.session_state.pending_commentary = None

    st.session_state.last_feedback = msg
    st.toast(msg, icon="✅")
    st.rerun()
```

### 8.3 Rendering the Commentary (Bottom of Page)

```python
# At the very end of voice_scorekeeper.py, after all UI:
if st.session_state.get("pending_commentary") and st.session_state.get("commentary_enabled", False):
    commentary = st.session_state.pending_commentary
    if not st.session_state.get("commentary_muted", False):
        # Render browser speech component
        spoken = speak_commentary(
            text=commentary.text,
            key=f"commentary_{commentary.event_id}",
            voice=st.session_state.commentary_voice,
            lang=st.session_state.commentary_language,
        )
        # Show text preview
        st.caption(f"🔊 {commentary.text}")
    # Clear after rendering so it doesn't repeat on next rerun
    st.session_state.pending_commentary = None
```

### 8.4 Replay Button Bypass
```python
if st.button("🔊 Replay", key="replay_commentary"):
    last = st.session_state.get("last_commentary_text")
    if last:
        st.session_state.pending_commentary = CommentaryLine(
            text=last,
            event_type="replay",
            priority=2,
            should_speak=True,
            dedupe_key=f"replay_{uuid.uuid4()}",
            event_id=str(uuid.uuid4()),
        )
        st.rerun()
```

---

## 9. Dataset Strategy

### 9.1 MVP: Hand-Written Templates
- All commentary lines are hand-written in `commentary_service.py`.
- No dataset download, no model training.
- Deterministic, safe, instant.

### 9.2 Future Inspiration (Not MVP)
- **SoccerNet-Echoes**: Public sports-commentary dataset (soccer). Can inspire phrasing style (e.g., "Great comeback!", "What a match!") but **do not use verbatim** — domain mismatch.
- **OpenTTGames / T3Set**: Table-tennis datasets focused on video, ball tracking, strokes. Useful for future **event context** (e.g., "after a long rally") but not for spoken commentary training.
- **Future feature flag**: `ENABLE_DATASET_BACKED_COMMENTARY` (default `False`).
  - When enabled, could expand template pool or add style variation.
  - Would require offline preprocessing, not runtime generation.

### 9.3 Potential Future Dataset-Backed Features
- Commentary template expansion (more natural variation).
- Style classification (neutral vs. coach vs. announcer).
- Rally-context commentary (after long rallies, after aces).
- Multilingual commentary.
- Coaching-style feedback.

---

## 10. Integration with Scoring

### 10.1 Point Click Flow
```python
# voice_scorekeeper.py — add_point_a button
if st.button("➕", key="add_point_a", use_container_width=True):
    event_id = str(uuid.uuid4())
    prev_state = copy_state(st.session_state.match_manager.state)

    success, msg = st.session_state.match_manager._add_point("A")
    new_state = st.session_state.match_manager.state

    # Build commentary using existing score state
    commentary = commentary_service.build_score_commentary(
        event_type="point_a",
        state=new_state,
        previous_state=prev_state,
        settings=get_commentary_settings(),
        event_id=event_id,
    )

    if should_speak(commentary):
        st.session_state.pending_commentary = commentary
        st.session_state.last_commentary_event_id = event_id

    st.session_state.last_feedback = msg
    st.toast(msg, icon="✅")
    st.rerun()
```

### 10.2 Undo Flow
```python
if st.button("↩️ Undo Last Point", use_container_width=True):
    event_id = str(uuid.uuid4())
    prev_state = copy_state(st.session_state.match_manager.state)

    success, msg = st.session_state.match_manager.undo_last_point()
    new_state = st.session_state.match_manager.state

    commentary = commentary_service.build_score_commentary(
        event_type="undo",
        state=new_state,
        previous_state=prev_state,
        settings=get_commentary_settings(),
        event_id=event_id,
    )

    if should_speak(commentary):
        st.session_state.pending_commentary = commentary
        st.session_state.last_commentary_event_id = event_id

    st.session_state.last_feedback = msg
    st.toast(msg, icon="↩️")
    st.rerun()
```

### 10.3 Game-Won Detection
The current `MatchManager._add_point` does not advance sets or detect game wins. For MVP:
- **Option A**: Add game-won detection to `MatchManager._add_point` and return a richer message.
- **Option B**: Let `commentary_service` detect game/match wins from `match_history` and current state.

**Recommended: Option B** — keeps `MatchManager` focused on state mutation, and `commentary_service` handles presentation logic.

```python
# In commentary_service.py
def _detect_game_won(self, state: SpokenScoreState, previous_state: SpokenScoreState) -> Optional[str]:
    a, b = state.score_a, state.score_b
    prev_a, prev_b = previous_state.score_a, previous_state.score_b

    # Game just finished
    if (a >= 11 or b >= 11) and abs(a - b) >= 2:
        if a > prev_a or b > prev_b:  # point was just added
            if a > b:
                return "game_won_a"
            else:
                return "game_won_b"
    return None
```

### 10.4 Match-Won Detection
```python
def _detect_match_won(self, state: SpokenScoreState) -> Optional[str]:
    if state.sets_a >= 3:
        return "match_won_a"
    if state.sets_b >= 3:
        return "match_won_b"
    return None
```

**Note**: The current `MatchManager` does not track sets properly (it has `sets_a`/`sets_b` but never increments them). For MVP commentary, we can:
- Use `in_progress_game_scores` from session state (game-by-game section) to determine match winner.
- Or, for the manual point-scoring section, assume a single game and only announce game-level events.

**MVP Scope Decision**: Commentary for manual point scoring covers **point-level** and **game-level** events within the current game. Match-level commentary is handled in the **game-by-game scoring section** when a match is completed.

---

## 11. Feature Flags / Settings

### 11.1 Environment Variable
```python
# tournament_platform/services/settings.py
ENABLE_SPOKEN_COMMENTARY: bool = _get_env_bool("ENABLE_SPOKEN_COMMENTARY", False)
```

### 11.2 Session-Level Settings
Stored in `st.session_state`:
- `commentary_enabled`
- `commentary_style`
- `commentary_verbosity`
- `commentary_voice`
- `commentary_language`
- `commentary_muted`
- `last_commentary_event_id`
- `pending_commentary`
- `last_commentary_text` (for replay)

### 11.3 Graceful Degradation
```python
def get_commentary_settings() -> dict:
    return {
        "enabled": st.session_state.get("commentary_enabled", False),
        "style": st.session_state.get("commentary_style", "neutral"),
        "verbosity": st.session_state.get("commentary_verbosity", "standard"),
        "voice": st.session_state.get("commentary_voice", "default"),
        "language": st.session_state.get("commentary_language", "en"),
        "muted": st.session_state.get("commentary_muted", False),
    }
```

If browser speech is unsupported, the component silently fails and the app continues normally.

---

## 12. Test Plan

### 12.1 Unit Tests (`tests/test_multimodal/test_commentary_service.py`)

| Test | Description |
|------|-------------|
| `test_point_commentary_text` | Verify point commentary templates render correctly with player names and scores. |
| `test_deuce_detection` | Score 10–10 triggers `ScoreMoment.DEUCE`. |
| `test_advantage_detection_a` | Score 11–10 triggers `ScoreMoment.ADVANTAGE_A`. |
| `test_advantage_detection_b` | Score 10–11 triggers `ScoreMoment.ADVANTAGE_B`. |
| `test_game_point_detection_a` | Score 10–8 with point to A triggers `ScoreMoment.GAME_POINT_A`. |
| `test_game_point_detection_b` | Score 8–10 with point to B triggers `ScoreMoment.GAME_POINT_B`. |
| `test_game_won_commentary` | Score 11–8 triggers `ScoreMoment.GAME_WON_A`. |
| `test_match_won_commentary` | `sets_a=3, sets_b=1` triggers `ScoreMoment.MATCH_WON_A`. |
| `test_undo_commentary` | Undo event generates correct undo commentary. |
| `test_invalid_score_action` | Invalid action generates `ScoreMoment.INVALID`. |
| `test_no_duplicate_speech_on_rerun` | Same `event_id` spoken twice returns `should_speak=False`. |
| `test_commentary_disabled_means_no_speech` | When `enabled=False`, `should_speak` is `False`. |
| `test_missing_tts_does_not_break_scoring` | TTS failure is caught; scoring continues. |
| `test_style_variation` | Neutral vs. Coach vs. Announcer templates differ. |
| `test_verbosity_minimal` | Minimal verbosity suppresses point commentary, keeps deuce/game/match. |
| `test_verbosity_standard` | Standard verbosity includes point + score. |
| `test_verbosity_expressive` | Expressive adds rally-style phrases. |

### 12.2 Integration Tests
- Test that clicking `add_point_a` button stores `pending_commentary` in session state.
- Test that `pending_commentary` is cleared after rendering.
- Test that replay button sets a new `pending_commentary`.
- Test that mute button suppresses speech but still shows text preview.

### 12.3 Existing Test File
- `tests/test_multimodal/test_voice_scorekeeper.py` — keep existing tests intact.
- Add new test file: `tests/test_multimodal/test_commentary_service.py`.

---

## 13. File-by-File Implementation Plan

### 13.1 New Files

| File | Purpose |
|------|---------|
| `tournament_platform/services/commentary_service.py` | Core commentary generation logic. Pure Python, no Streamlit. |
| `tournament_platform/app/components/spoken_commentary.py` | Streamlit component wrapper for browser speech synthesis. |
| `tests/test_multimodal/test_commentary_service.py` | Unit tests for commentary service. |

### 13.2 Modified Files

| File | Changes |
|------|---------|
| `tournament_platform/app/pages/voice_scorekeeper.py` | Add commentary settings UI, wire score buttons to commentary service, render pending commentary at bottom. |
| `tournament_platform/services/settings.py` | Add `ENABLE_SPOKEN_COMMENTARY` flag (already exists, verify it's used). |
| `tournament_platform/app/settings.py` | No changes needed. |
| `pyproject.toml` | No new dependencies for MVP. |
| `requirements.txt` | No new dependencies for MVP. |

### 13.3 Detailed Changes

#### `tournament_platform/services/commentary_service.py`
- New file (~300 lines).
- Contains `ScoreMoment`, `CommentaryStyle`, `CommentaryVerbosity`, `CommentaryLine`, `SpokenScoreState`, `CommentaryService`.
- All templates are class-level dictionaries.
- `classify_score_moment` uses `match_history` to determine previous state.

#### `tournament_platform/app/components/spoken_commentary.py`
- New file (~50 lines).
- `speak_commentary(text, key, voice, lang)` renders a `components.html` block.
- Handles unsupported browsers gracefully.

#### `tournament_platform/app/pages/voice_scorekeeper.py`
- Add session state initialization for commentary settings (~15 lines).
- Add Commentary Settings UI section (~30 lines).
- Modify `add_point_a`, `add_point_b`, `undo`, `reset` button handlers to:
  - Generate `event_id`.
  - Capture previous state.
  - Call `commentary_service.build_score_commentary`.
  - Store in `pending_commentary` if `should_speak`.
- Add bottom-of-page rendering block for `pending_commentary` (~20 lines).
- Add replay button (~10 lines).

#### `tournament_platform/services/settings.py`
- Verify `ENABLE_SPOKEN_COMMENTARY` exists (it does at line 49).

---

## 14. Implementation Phases

### Phase 0: Inspection (Current)
- [x] Inspect `voice_scorekeeper.py`, `MatchManager`, `match_score.py`.
- [x] Inspect TTS dependencies and existing `speak_text`.
- [x] Inspect session state patterns.
- [x] Inspect existing plans and tests.

### Phase 1: Deterministic Commentary Service
- Create `tournament_platform/services/commentary_service.py`.
- Implement `ScoreMoment` detection.
- Implement template selection for `Neutral` / `Standard` verbosity.
- Write unit tests.

### Phase 2: Streamlit UI Controls
- Add commentary settings to `voice_scorekeeper.py`.
- Add session state initialization.
- Add settings UI (toggle, style, verbosity, mute, replay).

### Phase 3: Browser Speech Synthesis Component
- Create `tournament_platform/app/components/spoken_commentary.py`.
- Implement `speak_commentary` with `components.html`.
- Add graceful fallback for unsupported browsers.

### Phase 4: Wire Commentary to Score Clicks
- Modify score button handlers in `voice_scorekeeper.py`.
- Implement event-ID-based dedupe.
- Implement `pending_commentary` render-and-clear pattern.
- Add replay button.

### Phase 5: Style / Verbosity Templates
- Add `Coach`, `Announcer`, `Minimal` style templates.
- Add `Minimal` and `Expressive` verbosity variants.
- Test all combinations.

### Phase 6: Dataset-Backed Commentary (Future)
- Feature flag: `ENABLE_DATASET_BACKED_COMMENTARY`.
- Research SoccerNet-Echoes for style inspiration.
- Research OpenTTGames/T3Set for event context.
- Keep behind feature flag; no runtime dependency.

---

## 15. MVP Acceptance Criteria

- [ ] Voice Scorekeeper page loads and functions normally with commentary disabled (default).
- [ ] User can enable spoken commentary via toggle.
- [ ] Clicking a score button produces exactly one spoken line.
- [ ] The same event is **not** spoken repeatedly on Streamlit reruns.
- [ ] Commentary correctly announces point winner and current score.
- [ ] Deuce, advantage, game point, game won, and match won are detected and announced.
- [ ] User can mute commentary without disabling the feature.
- [ ] Scoring and match submission continue normally if TTS fails or is unsupported.
- [ ] No cloud API or dataset download is required for MVP.
- [ ] All new code has unit tests with >90% coverage for `commentary_service.py`.

---

## 16. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `pyttsx3` blocks Streamlit | Do not use as primary. Use browser-native speech. Keep `pyttsx3` only as fallback in a daemon thread. |
| Browser speech unsupported | Graceful degradation: show text preview only, no crash. |
| Streamlit reruns cause duplicate speech | Event-ID dedupe + `pending_commentary` clear-after-render pattern. |
| `MatchManager` lacks game/match detection | `commentary_service` reads `match_history` and `in_progress_game_scores` to detect events without modifying `MatchManager`. |
| Tournament environment audio issues | Default OFF. Mute button. No auto-play. |
| Voice selection varies by browser/OS | Use `default` voice by default. Allow user selection but fall back gracefully. |
| `components.html` cannot return callback | Use session-state-based render-and-clear instead of callback. |

---

## 17. Assumptions

1. **Browser support**: Target browsers are modern Chrome/Edge/Firefox/Safari with `SpeechSynthesis` API.
2. **Single-game focus for manual scoring**: The manual point-scoring section (`➕`/`➖` buttons) tracks a single game. Match-level commentary is handled in the game-by-game section.
3. **No LLM required**: All commentary is template-driven. No Ollama or external API calls.
4. **Offline-first**: No internet required for MVP commentary.
5. **Existing `ENABLE_SPOKEN_CONFIRMATION` flag**: We will reuse or extend this pattern rather than inventing a new config system.
6. **`MatchManager` remains unchanged for MVP**: Commentary service reads state; it does not mutate `MatchManager`.

---

## 18. Open Questions

1. Should the commentary service also handle **voice-command** feedback (e.g., after `process_voice_command`), or only manual button clicks?
   - **Recommendation**: MVP covers manual clicks only. Voice-command feedback can reuse the same service in Phase 5.

2. Should we add set/game tracking to `MatchManager` now, or defer?
   - **Recommendation**: Defer. Use `in_progress_game_scores` for match-level events.

3. Should `commentary_style` affect only word choice, or also voice parameters (rate, pitch)?
   - **Recommendation**: MVP affects only text. Voice parameters can be added later.

4. Should we support multiple languages in MVP?
   - **Recommendation**: No. Add `language` selector as a stub for future extensibility.

---

## 19. Summary

This plan adds a **safe, incremental, reviewable** spoken commentary layer to the Voice Scorekeeper:

- **New service** (`commentary_service.py`) generates deterministic commentary from existing score state.
- **New component** (`spoken_commentary.py`) uses browser-native `SpeechSynthesis` — no blocking, no cloud.
- **Rerun-safe** via event-ID dedupe and `pending_commentary` render-and-clear.
- **User-controlled** via toggle, style, verbosity, mute, and replay.
- **Offline, no new dependencies, no LLM required** for MVP.
- **Tested** with unit tests covering all score moments and rerun safety.

The work is broken into 6 small phases, each independently reviewable and mergeable.
