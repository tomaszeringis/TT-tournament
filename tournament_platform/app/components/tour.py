"""
Getting Started Tours — single source of truth.

Each page calls ``render_tour("<key>")`` once after its title.  The tour
framework renders a collapsible expander ("Getting started") and, when the
user clicks through, a step-by-step ``st.dialog`` guide.
"""

import streamlit as st

# ---------------------------------------------------------------------------
# Tour content registry
# ---------------------------------------------------------------------------

TOUR_CONTENT: dict[str, dict] = {
    "home": {
        "title": "Your tournament command center",
        "intro": (
            "The Home page is your starting point for every tournament workflow "
            "— create events, register players, run matches, and track results. "
            "First action: Create Tournament or Resume Current Event."
        ),
        "steps": [
            {
                "title": "Welcome",
                "icon": "🏠",
                "content": (
                    "Home is your tournament command center. From here you can "
                    "create tournaments, resume events, view live operations, and track progress."
                ),
            },
            {
                "title": "Create Tournament",
                "icon": "🏆",
                "content": (
                    "Start by creating a tournament in Events & Draws. Choose a format "
                    "(Single Elimination, Round Robin, Groups → Knockout, or Swiss) "
                    "and select at least 2 players."
                ),
            },
            {
                "title": "Register Players",
                "icon": "👥",
                "content": (
                    "Use the Participants tab to register players before generating brackets. "
                    "At least 2 players are required to create a tournament."
                ),
            },
            {
                "title": "Run Matches",
                "icon": "🎛️",
                "content": (
                    "Use the Operator Console (Admin) or Voice Scorekeeper to call, start, "
                    "and score matches during tournament day. Manual scoring is always available."
                ),
            },
            {
                "title": "View Results",
                "icon": "📺",
                "content": (
                    "The Public Board shows live match status for spectators. "
                    "Check the Dashboard for analytics, rankings, and match insights."
                ),
            },
        ],
    },
    "tournament": {
        "title": "Create and manage tournaments",
        "intro": (
            "Events & Draws is where you build tournaments, manage participants, "
            "and view active brackets. First action: Create a new tournament or open an existing one."
        ),
        "steps": [
            {
                "title": "Tournament Wizard",
                "icon": "🏆",
                "content": (
                    "Use the 4-step wizard to create a tournament: basics, format, "
                    "participants, and review. Supports Single Elimination, Round Robin, "
                    "Groups → Knockout, and Swiss."
                ),
            },
            {
                "title": "Participants",
                "icon": "👥",
                "content": (
                    "Register and manage players in the Participants tab. "
                    "Players must exist before you can add them to a tournament."
                ),
            },
            {
                "title": "Active Tournaments",
                "icon": "📊",
                "content": (
                    "View all tournaments, their brackets, and standings. "
                    "Generate brackets for tournaments that don't have matches yet."
                ),
            },
            {
                "title": "Regenerate Draws",
                "icon": "⚠️",
                "content": (
                    "Regenerating draws discards in-progress brackets and match results. "
                    "Confirm before proceeding."
                ),
                "danger": True,
            },
        ],
    },
    "voice_scorekeeper": {
        "title": "Voice-controlled match scoring",
        "intro": (
            "The Voice Scorekeeper lets you update match scores using voice commands, "
            "with manual fallback always available. First action: Select an active match."
        ),
        "steps": [
            {
                "title": "Select Match",
                "icon": "🎯",
                "content": (
                    "Choose a tournament and match from the selectors. "
                    "Only active or pending matches can be scored."
                ),
            },
            {
                "title": "Start Listening",
                "icon": "🎤",
                "content": (
                    "Enable voice scoring to start listening. "
                    "The system uses local transcription — no audio leaves your machine."
                ),
            },
            {
                "title": "Voice Commands",
                "icon": "🗣️",
                "content": (
                    "Speak commands like 'Player A scores' or 'Undo last point'. "
                    "The confirmation gate prevents accidental updates."
                ),
            },
            {
                "title": "Confirmations",
                "icon": "✅",
                "content": (
                    "Low-confidence or critical commands require explicit confirmation "
                    "before the score updates."
                ),
            },
            {
                "title": "Dataset Recording",
                "icon": "⚠️",
                "content": (
                    "Dataset recording is opt-in. Audio is stored locally for model improvement. "
                    "Enable in settings if you want to contribute."
                ),
                "danger": True,
            },
        ],
    },
    "ai_assistant": {
        "title": "Ask anything about tournaments",
        "intro": (
            "The AI Assistant answers tournament rules, standings, and operations questions "
            "using RAG. First action: Ask a rules or setup question."
        ),
        "steps": [
            {
                "title": "Tournament Assistant",
                "icon": "🤖",
                "content": (
                    "Ask general questions about tournaments, standings, and match status. "
                    "Answers are grounded in your data."
                ),
            },
            {
                "title": "Rules Q&A",
                "icon": "📜",
                "content": (
                    "Ask specific rules questions. Responses cite source documents so you can verify."
                ),
            },
            {
                "title": "Voice Input",
                "icon": "🎤",
                "content": (
                    "Use the voice input button to ask questions hands-free (Rules Q&A tab only)."
                ),
            },
            {
                "title": "Experimental",
                "icon": "⚠️",
                "content": (
                    "This assistant provides information only. Verify critical answers against "
                    "official rules, especially for match disputes."
                ),
                "danger": True,
            },
        ],
    },
    "admin": {
        "title": "Database, operator console, and system health",
        "intro": (
            "The Admin / Operator Console gives you full visibility into the database, "
            "match queue, table status, and system health. First action depends on your role: "
            "admins start with Database Overview, operators with Match Queue."
        ),
        "steps": [
            {
                "title": "Database Overview",
                "icon": "📊",
                "content": (
                    "View counts for players, matches, tournaments, and completed matches. "
                    "Detailed player statistics are available below."
                ),
            },
            {
                "title": "Match Management",
                "icon": "🎾",
                "content": (
                    "Filter matches by status or tournament. Quick actions include Refresh Data "
                    "and Clear All Cache."
                ),
            },
            {
                "title": "Operator Console",
                "icon": "🎛️",
                "content": (
                    "Call matches, assign tables, start/complete/delay/reschedule matches. "
                    "The Match Queue and Table Status tabs organize live operations."
                ),
            },
            {
                "title": "Schedule Board",
                "icon": "📅",
                "content": (
                    "Embedded schedule view for planning matches by date and time."
                ),
            },
            {
                "title": "System Health",
                "icon": "💚",
                "content": (
                    "Check database, API, Ollama AI, and optional integrations (Teams, Azure). "
                    "View runtime versions and environment warnings."
                ),
            },
            {
                "title": "Danger Zone",
                "icon": "⚠️",
                "content": (
                    "Maintenance actions like clear/reseed/reset are destructive and cannot be undone. "
                    "Only test/demo data is affected. The audit log records all changes."
                ),
                "danger": True,
            },
        ],
    },
    "dataset_catalog": {
        "title": "Browse datasets for multimodal AI",
        "intro": (
            "The Dataset Catalog lists registered datasets with modality, license, and size. "
            "First action: Explore a dataset or check a combination's license compliance."
        ),
        "steps": [
            {
                "title": "All Datasets",
                "icon": "📊",
                "content": (
                    "Browse all registered datasets. Check the license_status column for "
                    "commercial use restrictions."
                ),
            },
            {
                "title": "By Modality",
                "icon": "🎛️",
                "content": (
                    "Filter datasets by modality: audio, video, sensor, text, or trajectory."
                ),
            },
            {
                "title": "Combinations",
                "icon": "🔗",
                "content": (
                    "View predefined dataset combinations (voice_core, coaching_core, etc.). "
                    "License compliance is validated automatically."
                ),
            },
            {
                "title": "License Warnings",
                "icon": "⚠️",
                "content": (
                    "Non-commercial and research-only licenses restrict commercial use. "
                    "Check license_status before downloading."
                ),
                "danger": True,
            },
        ],
    },
    "coaching_lab": {
        "title": "Analyze sessions and get coaching feedback",
        "intro": (
            "The Coaching Lab analyzes table tennis sessions and provides AI-powered feedback. "
            "First action: Run a sample analysis or classify an intent."
        ),
        "steps": [
            {
                "title": "Session Analysis",
                "icon": "📊",
                "content": (
                    "Create a session and run analysis. Options include ASR, stroke analysis, "
                    "trajectory, and recommendations."
                ),
            },
            {
                "title": "Intent Classification",
                "icon": "🏷️",
                "content": (
                    "Classify transcribed text into coaching intents. "
                    "Adjust the confidence threshold to tune sensitivity."
                ),
            },
            {
                "title": "Recommendations",
                "icon": "💡",
                "content": (
                    "View coaching recommendations generated from session analysis. "
                    "Categories include Technique, Footwork, and Timing."
                ),
            },
        ],
    },
    "experiment_dashboard": {
        "title": "Track ML/ASR experiments",
        "intro": (
            "The Experiment Dashboard tracks model training and evaluation experiments. "
            "First action: View existing experiments or create a new one."
        ),
        "steps": [
            {
                "title": "All Experiments",
                "icon": "🧪",
                "content": (
                    "Browse experiments with status, dataset combination, and creation date."
                ),
            },
            {
                "title": "Create Experiment",
                "icon": "➕",
                "content": (
                    "Define a new experiment with name, dataset combination, and model config JSON."
                ),
            },
            {
                "title": "Evaluation Results",
                "icon": "📈",
                "content": (
                    "Add and view evaluation metrics (WER, mAP, Accuracy) for each experiment."
                ),
            },
        ],
    },
    "public_board": {
        "title": "Spectator view for live tournament action",
        "intro": (
            "The Public Board is a read-only display for TV or projector viewing. "
            "It auto-refreshes every 15 seconds. First action: Pick a tournament to follow."
        ),
        "steps": [
            {
                "title": "Now Playing",
                "icon": "🔴",
                "content": (
                    "See live and called matches with real-time status. "
                    "The board updates automatically."
                ),
            },
            {
                "title": "Coming Up",
                "icon": "⏭️",
                "content": (
                    "View the next scheduled matches. Countdown timers show time until the next match."
                ),
            },
            {
                "title": "Rankings",
                "icon": "📊",
                "content": (
                    "Standings update as matches complete. Sorted by wins and points differential."
                ),
            },
            {
                "title": "Recent Results",
                "icon": "📋",
                "content": (
                    "Review completed matches with scores and winners."
                ),
            },
            {
                "title": "Kiosk Mode",
                "icon": "📺",
                "content": (
                    "Enable Kiosk Mode in the sidebar to hide UI chrome for clean TV display. "
                    "The page auto-refreshes every 10 seconds in kiosk mode."
                ),
            },
        ],
    },
    "schedule_board": {
        "title": "Calendar view of upcoming matches",
        "intro": (
            "The Schedule Board shows matches organized by date for planning and logistics. "
            "First action: Choose a tournament and date range."
        ),
        "steps": [
            {
                "title": "Select Tournament",
                "icon": "🏆",
                "content": (
                    "Pick a tournament to view its schedule."
                ),
            },
            {
                "title": "Date Range",
                "icon": "📅",
                "content": (
                    "Set the start date and number of days to show. "
                    "Matches are grouped by day."
                ),
            },
            {
                "title": "Match Details",
                "icon": "📋",
                "content": (
                    "Each match shows time, players, table location, and call status "
                    "with color-coded indicators."
                ),
            },
            {
                "title": "Export",
                "icon": "📤",
                "content": (
                    "Download the schedule as CSV for printing or external planning tools."
                ),
            },
        ],
    },
    "video_scorekeeper": {
        "title": "AI-assisted video scoring",
        "intro": (
            "The Video Scorekeeper analyzes video clips to suggest point winners "
            "with human confirmation. First action: Grant camera permission and select a match."
        ),
        "steps": [
            {
                "title": "Select Match",
                "icon": "🎯",
                "content": (
                    "Choose a tournament and match from the selectors."
                ),
            },
            {
                "title": "Upload Video",
                "icon": "📹",
                "content": (
                    "Upload a short rally clip (max 30 seconds recommended). "
                    "The system analyzes it for point-winning events."
                ),
            },
            {
                "title": "Review Suggestion",
                "icon": "💡",
                "content": (
                    "The AI suggests a point winner with confidence and evidence. "
                    "Low-confidence suggestions require manual review."
                ),
            },
            {
                "title": "Confirm or Override",
                "icon": "✅",
                "content": (
                    "Accept the suggestion, reject it, or override to the other player. "
                    "All changes are applied immediately."
                ),
            },
            {
                "title": "Calibration",
                "icon": "📐",
                "content": (
                    "Optional table calibration improves accuracy by defining "
                    "camera perspective and net position."
                ),
            },
            {
                "title": "Experimental",
                "icon": "⚠️",
                "content": (
                    "This is an experimental feature. Manual correction is still required "
                    "for close calls. OpenCV is required for video analysis."
                ),
                "danger": True,
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Session-state helpers (all namespaced with gs_tour_ prefix)
# ---------------------------------------------------------------------------

def _get_tour_state_keys(tour_key: str) -> tuple[str, str, str]:
    return (
        f"gs_tour_{tour_key}_show",
        f"gs_tour_{tour_key}_step",
        f"gs_tour_{tour_key}_done",
    )


def _ensure_tour_defaults(tour_key: str) -> None:
    show_key, step_key, done_key = _get_tour_state_keys(tour_key)
    if show_key not in st.session_state:
        st.session_state[show_key] = False
    if step_key not in st.session_state:
        st.session_state[step_key] = 1
    if done_key not in st.session_state:
        st.session_state[done_key] = False


def is_tour_completed(tour_key: str) -> bool:
    """Return True if the user has finished (or skipped) this tour."""
    _ensure_tour_defaults(tour_key)
    done_key = _get_tour_state_keys(tour_key)[2]
    return bool(st.session_state.get(done_key, False))


def reset_tour(tour_key: str) -> None:
    """Reset a tour so it can be replayed from step 1."""
    show_key, step_key, done_key = _get_tour_state_keys(tour_key)
    st.session_state[show_key] = False
    st.session_state[step_key] = 1
    st.session_state[done_key] = False


# ---------------------------------------------------------------------------
# Public render API
# ---------------------------------------------------------------------------

def render_tour(tour_key: str) -> None:
    """Render the tour expander and (if active) the tour dialog."""
    _ensure_tour_defaults(tour_key)
    render_tour_expander(tour_key)
    render_tour_dialog(tour_key)


def render_tour_expander(tour_key: str) -> None:
    """Render the collapsible 'Getting started' expander for a page."""
    content = TOUR_CONTENT.get(tour_key)
    if not content:
        return

    _ensure_tour_defaults(tour_key)
    done_key = _get_tour_state_keys(tour_key)[2]
    done = bool(st.session_state.get(done_key, False))

    expander_label = "❓ Getting started" + (" ✅" if done else "")

    with st.expander(expander_label, expanded=False):
        st.markdown(f"**What this page is for:** {content['intro']}")
        st.markdown("**Steps:**")
        for step in content["steps"]:
            icon = step.get("icon", "•")
            danger = " ⚠️" if step.get("danger") else ""
            st.markdown(f"- {icon} **{step['title']}**{danger}")

        if done:
            if st.button("🔄 Replay tour", key=f"replay_tour_{tour_key}"):
                reset_tour(tour_key)
                show_key = _get_tour_state_keys(tour_key)[0]
                st.session_state[show_key] = True
                st.rerun()
        else:
            if st.button(
                "▶️ Start guided tour",
                key=f"start_tour_{tour_key}",
                type="primary",
            ):
                show_key, step_key, _ = _get_tour_state_keys(tour_key)
                st.session_state[show_key] = True
                st.session_state[step_key] = 1
                st.rerun()


def render_tour_dialog(tour_key: str) -> None:
    """Render the step-by-step tour dialog (only when active)."""
    content = TOUR_CONTENT.get(tour_key)
    if not content:
        return

    _ensure_tour_defaults(tour_key)
    show_key, step_key, _ = _get_tour_state_keys(tour_key)
    show = bool(st.session_state.get(show_key, False))
    if not show:
        return

    step_idx = int(st.session_state.get(step_key, 1)) - 1
    steps = content["steps"]
    if step_idx < 0 or step_idx >= len(steps):
        return

    current = steps[step_idx]
    total = len(steps)

    @st.dialog(f"Getting started — {content['title']}", width="large")
    def _tour_dialog():
        st.markdown(f"### {current['icon']} {current['title']}")
        if current.get("danger"):
            st.warning(current["content"])
        else:
            st.write(current["content"])

        st.progress((step_idx + 1) / total)

        col_back, col_skip, col_next = st.columns(3)
        with col_back:
            if step_idx > 0:
                if st.button("← Back", use_container_width=True, key=f"tour_back_{tour_key}"):
                    st.session_state[step_key] = step_idx
                    st.rerun()
        with col_skip:
            if st.button("Skip", use_container_width=True, key=f"tour_skip_{tour_key}"):
                st.session_state[show_key] = False
                done_key = _get_tour_state_keys(tour_key)[2]
                st.session_state[done_key] = True
                st.rerun()
        with col_next:
            if step_idx < total - 1:
                if st.button("Next →", use_container_width=True, type="primary", key=f"tour_next_{tour_key}"):
                    st.session_state[step_key] = step_idx + 2
                    st.rerun()
            else:
                if st.button("Finish", use_container_width=True, type="primary", key=f"tour_finish_{tour_key}"):
                    st.session_state[show_key] = False
                    done_key = _get_tour_state_keys(tour_key)[2]
                    st.session_state[done_key] = True
                    st.rerun()
                if st.button("Replay", use_container_width=True, key=f"tour_replay_{tour_key}"):
                    reset_tour(tour_key)
                    st.session_state[show_key] = True
                    st.rerun()

    _tour_dialog()


def render_sidebar_launcher() -> None:
    """Render a global 'Getting Started Tour' button in the sidebar."""
    with st.sidebar:
        st.divider()
        if st.button("❓ Getting Started Tour", use_container_width=True):
            reset_tour("home")
            show_key = _get_tour_state_keys("home")[0]
            st.session_state[show_key] = True
            st.rerun()
