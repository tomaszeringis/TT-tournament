"""
Events & Draws page for Tournament Platform.

This page handles tournament creation, bracket generation, standings, and participant management.
"""

import logging
from typing import Optional

import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import math
from sqlalchemy.orm import selectinload

from tournament_platform.models import SessionLocal, Player, Match, Tournament, TournamentParticipant, MatchStatus, TournamentType, Event, EventType, Entry, Stage
from tournament_platform.services.tournament_engine import TournamentFactory, TournamentContext, KnockoutStrategy, RoundRobinStrategy, GroupsKnockoutStrategy, SwissStrategy
from tournament_platform.services.bracket_manager import TournamentState
from tournament_platform.app.components.interactive_bracket import interactive_bracket
from tournament_platform.app.components.participants_panel import render_participants_panel, get_all_players
from tournament_platform.app.components.empty_state import render_empty_state
from tournament_platform.app.components.loading_animation import render_loading_animation
from tournament_platform.app.components.pairing_explanation_component import render_pairing_expander
from tournament_platform.app.utils import render_status_badge
from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.app.components.tour import render_tour
from tournament_platform.config import settings

logger = logging.getLogger(__name__)

# brackets-viewer / brackets-model match status codes.
# See https://drarig29.github.io/brackets-docs/reference/model/enums/Status.html
#   Locked = 0, Waiting = 1, Ready = 2, Running = 3, Completed = 4, Archived = 5
BRACKET_STATUS_COMPLETED = 4
BRACKET_STATUS_READY = 2


def calculate_bracket_size(participant_count: int) -> int:
    """
    Calculate the appropriate bracket size based on participant count.
    
    Returns the next power of two for the given participant count.
    Supports 4, 8, 16, 32, 64, etc.
    
    Args:
        participant_count: Number of participants in the tournament.
        
    Returns:
        The bracket size (power of two) to use.
    """
    if participant_count <= 0:
        return 4  # Default minimum
    if participant_count <= 4:
        return 4
    if participant_count <= 8:
        return 8
    if participant_count <= 16:
        return 16
    if participant_count <= 32:
        return 32
    if participant_count <= 64:
        return 64
    if participant_count <= 128:
        return 128
    # For very large tournaments, cap at 128
    return 128


def _get_tournament_selector_for_participants() -> Optional[int]:
    """Render a tournament selector and return the selected tournament id, or None."""
    try:
        db = SessionLocal()
        tournaments = db.query(Tournament).order_by(Tournament.name.asc()).all()
        db.close()
    except Exception as e:
        st.error(f"Error loading tournaments: {e}")
        return None

    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        return None

    options = {f"{t.name} (ID {t.id})": t.id for t in tournaments}
    selected = st.selectbox(
        "Select Tournament",
        options=list(options.keys()),
        key="participants_tournament_select_events",
    )
    return options[selected]


def render_tournament_creation_wizard():
    """
    Render a full-width guided tournament creation flow.
    Step 1: basics (name, description)
    Step 2: format (Single Elimination / Round Robin)
    Step 3: participants
    Step 4: review and create
    """
    st.subheader("🏆 Create New LIT_IT Tournament")
    
    # Initialize session state for wizard
    if 'wizard_step' not in st.session_state:
        st.session_state['wizard_step'] = 1
    if 'tournament_name' not in st.session_state:
        st.session_state['tournament_name'] = ""
    if 'tournament_desc' not in st.session_state:
        st.session_state['tournament_desc'] = ""
    if 'tournament_format' not in st.session_state:
        st.session_state['tournament_format'] = "Single Elimination"
    if 'tournament_participants' not in st.session_state:
        st.session_state['tournament_participants'] = []
    if 'tournament_seeding' not in st.session_state:
        st.session_state['tournament_seeding'] = "random"
    if 'tournament_event_date' not in st.session_state:
        st.session_state['tournament_event_date'] = None
    if 'tournament_venue' not in st.session_state:
        st.session_state['tournament_venue'] = ""
    
    # Get all players for selection
    db = SessionLocal()
    all_players = db.query(Player).all()
    player_names = [p.name for p in all_players]
    db.close()
    
    # Progress indicator
    WIZARD_STEPS = ["Basics", "Format", "Players", "Review"]
    cols = st.columns(4)
    for i, label in enumerate(WIZARD_STEPS, start=1):
        with cols[i-1]:
            if st.session_state['wizard_step'] >= i:
                st.markdown(f"**{i}. {label}**")
            else:
                st.markdown(f"{i}. {label}")
    
    st.divider()
    
    # Step 1: Basics
    if st.session_state['wizard_step'] == 1:
        st.write("**Basics**")
        st.session_state['tournament_name'] = st.text_input(
            "Tournament Name",
            value=st.session_state['tournament_name'],
            help="Enter a unique name for your tournament"
        )
        st.session_state['tournament_desc'] = st.text_area(
            "Description",
            value=st.session_state['tournament_desc'],
            help="Optional description of the tournament format or rules"
        )
        
        col1, col2 = st.columns([1, 1])
        with col2:
            if st.button("Next →", use_container_width=True, key="wizard_step1_next"):
                if st.session_state['tournament_name']:
                    st.session_state['wizard_step'] = 2
                    st.rerun()
                else:
                    st.error("Please enter a tournament name")
    
    # Step 2: Format
    elif st.session_state['wizard_step'] == 2:
        st.write("**Format**")
        st.session_state['tournament_format'] = st.radio(
            "Choose the competition structure",
            options=["Single Elimination", "Round Robin", "Groups → Knockout", "Swiss"],
            index=0 if st.session_state['tournament_format'] == "Single Elimination" else (1 if st.session_state['tournament_format'] == "Round Robin" else (2 if st.session_state['tournament_format'] == "Groups → Knockout" else 3)),
            help="Single Elimination: knockout bracket. Round Robin: everyone plays everyone. Groups → Knockout: round-robin groups, then knockout. Swiss: players paired each round based on performance."
        )
        
        # Format limitation transparency
        st.info(
            "Currently implemented: **Single Elimination**, **Round Robin**, **Groups → Knockout**, **Swiss**. "
            "Planned (not yet available): Double Elimination, Doubles/Mixed Doubles."
        )
        
        # Seeding options
        st.write("**Seeding Options**")
        st.session_state['tournament_seeding'] = st.selectbox(
            "How to seed players in the bracket",
            options=["random", "rating", "manual"],
            index=0,
            format_func=lambda x: {"random": "Random", "rating": "By Rating (highest vs lowest)", "manual": "Manual Selection"}[x],
            help="Random: players randomly assigned. Rating: higher-rated players distributed across bracket. Manual: you choose the order."
        )
        
        # Event metadata
        st.write("**Event Details**")
        col1, col2 = st.columns(2)
        with col1:
            st.session_state['tournament_event_date'] = st.date_input(
                "Event Date (optional)",
                value=None,
                help="When is this tournament taking place?"
            )
        with col2:
            st.session_state['tournament_venue'] = st.text_input(
                "Venue (optional)",
                value="",
                help="Where is this tournament being held?"
            )
        
        # Groups → Knockout configuration
        if st.session_state['tournament_format'] == "Groups → Knockout":
            st.write("**Groups Configuration**")
            col1, col2 = st.columns(2)
            with col1:
                st.session_state['num_groups'] = st.number_input(
                    "Number of Groups",
                    min_value=2,
                    max_value=8,
                    value=st.session_state.get('num_groups', 2),
                    key="num_groups_input"
                )
            with col2:
                st.session_state['qualifiers_per_group'] = st.number_input(
                    "Qualifiers per Group",
                    min_value=1,
                    max_value=4,
                    value=st.session_state.get('qualifiers_per_group', 2),
                    key="qualifiers_per_group_input"
                )
            st.caption(
                f"With {st.session_state.get('num_groups', 2)} groups and {st.session_state.get('qualifiers_per_group', 2)} qualifiers per group, "
                f"the knockout stage will have {st.session_state.get('num_groups', 2) * st.session_state.get('qualifiers_per_group', 2)} players."
            )
        
        # Swiss configuration
        if st.session_state['tournament_format'] == "Swiss":
            st.write("**Swiss Configuration**")
            st.session_state['swiss_rounds'] = st.number_input(
                "Number of Rounds",
                min_value=3,
                max_value=10,
                value=st.session_state.get('swiss_rounds', 5),
                key="swiss_rounds_input",
                help="Swiss system pairs players with similar records each round"
            )
            st.caption(
                f"With {st.session_state.get('swiss_rounds', 5)} rounds, each player will play approximately {st.session_state.get('swiss_rounds', 5)} matches."
            )
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("← Back", use_container_width=True, key="wizard_step2_back"):
                st.session_state['wizard_step'] = 1
                st.rerun()
        with col2:
            if st.button("Next →", use_container_width=True, key="wizard_step2_next"):
                st.session_state['wizard_step'] = 3
                st.rerun()
    
    # Step 3: Participants
    elif st.session_state['wizard_step'] == 3:
        st.write("**Players**")

        if not player_names:
            st.warning("No players registered yet. Use the **Participants** tab to register players first.")
            st.session_state['tournament_participants'] = []
        else:
            st.session_state['tournament_participants'] = st.multiselect(
                "Choose at least 2 players",
                options=player_names,
                default=st.session_state['tournament_participants'],
                help="Select players to participate in this tournament"
            )

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("← Back", use_container_width=True, key="wizard_step3_back"):
                st.session_state['wizard_step'] = 2
                st.rerun()
        with col2:
            if st.button("Next →", use_container_width=True, key="wizard_step3_next"):
                if len(st.session_state['tournament_participants']) >= 2:
                    st.session_state['wizard_step'] = 4
                    st.rerun()
                else:
                    st.error("Please select at least 2 players")
    
    # Step 4: Review and Create
    elif st.session_state['wizard_step'] == 4:
        st.write("**Review**")
        
        # Participant count validation
        participant_count = len(st.session_state['tournament_participants'])
        if participant_count < 2:
            st.error("⚠️ You need at least 2 players to create a tournament.")
        elif participant_count > 128:
            st.error("⚠️ Maximum 128 players supported for a single tournament.")
        else:
            st.success(f"✅ {participant_count} players selected (valid range: 2-128)")
        
        st.info(f"**Name:** {st.session_state['tournament_name']}")
        st.info(f"**Description:** {st.session_state['tournament_desc'] or 'No description'}")
        st.info(f"**Format:** {st.session_state['tournament_format']}")
        st.info(f"**Seeding:** {st.session_state.get('tournament_seeding', 'random')}")
        
        # Event details
        if st.session_state.get('tournament_event_date'):
            st.info(f"**Event Date:** {st.session_state['tournament_event_date']}")
        if st.session_state.get('tournament_venue'):
            st.info(f"**Venue:** {st.session_state['tournament_venue']}")
        
        st.info(f"**Participants:** {participant_count} players")
        
        # Setup preview
        st.write("**Setup Preview**")
        st.caption(f"Bracket will have {calculate_bracket_size(participant_count)} slots with {participant_count} players")
        if st.session_state.get('tournament_seeding') == 'rating':
            st.caption("Players will be seeded by rating (highest-rated distributed across bracket)")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("← Back", use_container_width=True, key="wizard_step4_back"):
                st.session_state['wizard_step'] = 3
                st.rerun()
        with col2:
            if st.button("🏆 Create Tournament", use_container_width=True, type="primary", key="wizard_step4_create"):
                try:
                    db = SessionLocal()
                    
                    # Check if tournament name already exists
                    existing = db.query(Tournament).filter(
                        Tournament.name == st.session_state['tournament_name']
                    ).first()
                    
                    if existing:
                        st.error(f"Tournament '{st.session_state['tournament_name']}' already exists!")
                    else:
                        # Determine tournament type
                        if st.session_state['tournament_format'] == "Single Elimination":
                            t_type = TournamentType.knockout
                        elif st.session_state['tournament_format'] == "Round Robin":
                            t_type = TournamentType.round_robin
                        else:
                            t_type = TournamentType.knockout  # Groups → Knockout uses knockout as base
                        
                        new_tournament = Tournament(
                            name=st.session_state['tournament_name'],
                            description=st.session_state['tournament_desc'],
                            tournament_type=t_type
                        )
                        db.add(new_tournament)
                        db.flush()
                        
                        # Generate matches
                        if st.session_state['tournament_format'] == "Groups → Knockout":
                            num_groups = st.session_state.get('num_groups', 2)
                            qualifiers_per_group = st.session_state.get('qualifiers_per_group', 2)
                            selected_strategy = GroupsKnockoutStrategy(
                                num_groups=num_groups,
                                qualifiers_per_group=qualifiers_per_group
                            )
                        elif st.session_state['tournament_format'] == "Swiss":
                            num_rounds = st.session_state.get('swiss_rounds', 5)
                            selected_strategy = SwissStrategy(num_rounds=num_rounds)
                        else:
                            strategies = {
                                "Single Elimination": KnockoutStrategy(),
                                "Round Robin": RoundRobinStrategy()
                            }
                            selected_strategy = strategies[st.session_state['tournament_format']]
                        
                        context = TournamentContext(selected_strategy)
                        with st.status("Building bracket...", expanded=False):
                            render_loading_animation("Building bracket...", size=120)
                            context.run_generation(st.session_state['tournament_participants'], new_tournament.id, db)
                            db.commit()
                        st.toast(f"✅ Tournament '{st.session_state['tournament_name']}' created!", icon="🏆")
                        
                        # Reset wizard
                        st.session_state['wizard_step'] = 1
                        st.session_state['tournament_name'] = ""
                        st.session_state['tournament_desc'] = ""
                        st.session_state['tournament_format'] = "Single Elimination"
                        st.session_state['tournament_participants'] = []
                        st.rerun()
                except Exception as e:
                    st.error(f"Error creating tournament: {e}")
                finally:
                    db.close()


def build_bracket_data(tournament, players):
    """
    Build a brackets-viewer-compatible data structure from a tournament's matches.

    Unlike the previous implementation, participants are derived only from the
    tournament's actual entrants (the players referenced by its matches) rather
    than every player in the database. This keeps the bracket size proportional
    to the tournament and guarantees that every ``opponent.id`` referenced by a
    match also exists in ``participants`` (a data-shape invariant that
    brackets-viewer relies on — a dangling reference makes it throw).

    Args:
        tournament: The Tournament object (uses ``.matches``).
        players: List of Player objects, used to resolve names to stable ids.

    Returns:
        A dict with ``stages``/``matches``/``participants`` keys suitable for
        brackets-viewer, or ``None`` if the tournament has no matches.
    """
    matches = list(tournament.matches) if tournament and tournament.matches else []
    if not matches:
        return None

    # Stable name -> id lookup from the DB players (real, positive ids).
    players_by_name = {
        p.name: p.id for p in (players or []) if getattr(p, "name", None) is not None
    }

    participants = []
    participant_ids = set()
    name_to_id = {}
    # Synthetic ids for entrants without a DB id. Negative so they never clash
    # with real (positive) player ids.
    next_synthetic_id = [-1]

    def resolve_id(fk_id, name):
        """Return a stable id for an opponent, or None for byes/TBD/blank."""
        if not name or name == "TBD":
            return None
        if fk_id is not None:
            name_to_id.setdefault(name, fk_id)
            return name_to_id[name]
        if name in name_to_id:
            return name_to_id[name]
        if name in players_by_name:
            name_to_id[name] = players_by_name[name]
            return name_to_id[name]
        # Unknown player: synthesize a stable id so the reference stays valid.
        synthetic = next_synthetic_id[0]
        next_synthetic_id[0] -= 1
        name_to_id[name] = synthetic
        return synthetic

    def ensure_participant(pid, name):
        if pid is None or name is None:
            return
        if pid not in participant_ids:
            participant_ids.add(pid)
            participants.append({"id": pid, "name": name})

    matches_data = []
    for m in matches:
        p1_id = resolve_id(getattr(m, "player1_id", None), getattr(m, "player1", None))
        p2_id = resolve_id(getattr(m, "player2_id", None), getattr(m, "player2", None))
        ensure_participant(p1_id, getattr(m, "player1", None))
        ensure_participant(p2_id, getattr(m, "player2", None))

        status_val = getattr(m, "status", None)
        if hasattr(status_val, "value"):
            status_val = status_val.value
        status_val = str(status_val or "pending")

        match_entry = {
            "id": getattr(m, "id", None),
            "number": getattr(m, "bracket_index", None) or 0,
            "stageId": 0,
            "groupId": 0,
            "roundId": (getattr(m, "round_number", None) or 1) - 1,
            "status": int(BRACKET_STATUS_COMPLETED) if status_val == "completed" else int(BRACKET_STATUS_READY),
            "opponent1": {"id": p1_id, "score": None},
            "opponent2": {"id": p2_id, "score": None},
        }
        if status_val == "completed" and getattr(m, "score", None):
            try:
                s1, s2 = map(int, str(m.score).split("-"))
                match_entry["opponent1"]["score"] = int(s1)
                match_entry["opponent2"]["score"] = int(s2)
            except (ValueError, AttributeError):
                pass
        matches_data.append(match_entry)

    # Bracket size is based on the tournament's actual entrant count, not the
    # global player count.
    bracket_size = calculate_bracket_size(len(participants))

    return {
        "stages": [
            {
                "id": 0,
                "name": "Main Stage",
                "type": "single_elimination",
                "settings": {"size": bracket_size},
            }
        ],
        "matches": matches_data,
        "participants": participants,
    }


def normalize_bracket_matches(matches, players=None, db=None):
    """
    Normalize raw ``Match`` objects into a predictable list of plain dicts.

    This is the single source of truth used by both the native (fallback)
    renderer and diagnostics. It never raises on missing/optional fields and
    always fills required fields with safe defaults so the UI can always render.

    Args:
        matches: Iterable of Match objects (or anything with the expected attrs).
        players: Optional list of Player objects (unused today, accepted for a
            stable signature / future name resolution).
        db: Optional SQLAlchemy session used to batch-load Entry seed positions.

    Returns:
        List of dicts with keys: ``id``, ``round``, ``bracket_index``,
        ``player1``, ``player2``, ``winner``, ``score``, ``status``,
        ``table``, ``valid``, ``bye``, ``seed1``, ``seed2``,
        ``stage_type``, ``group_name``.
    """
    _seed_map = {}
    _stage_event_ids = set()

    if db is not None:
        for m in matches or []:
            stage = getattr(m, "stage", None)
            event = getattr(stage, "event", None) if stage else None
            event_id = getattr(event, "id", None)
            if event_id is not None:
                _stage_event_ids.add(event_id)

        if _stage_event_ids:
            entries = (
                db.query(Entry)
                .filter(Entry.event_id.in_(_stage_event_ids))
                .filter(Entry.seed_position.is_not(None))
                .all()
            )
            _seed_map = {e.player1_id: e.seed_position for e in entries}

    normalized = []
    for m in (matches or []):
        status = getattr(m, "status", None)
        status_str = getattr(status, "value", None) or (str(status) if status else "pending")

        raw_player1 = getattr(m, "player1", None)
        raw_player2 = getattr(m, "player2", None)
        player1 = raw_player1 or "TBD"
        player2 = raw_player2 or "TBD"
        round_number = getattr(m, "round_number", None) or 1

        stage = getattr(m, "stage", None)
        stage_type = None
        group_name = None
        if stage is not None:
            stage_type = getattr(stage, "stage_type", None)
            try:
                groups = getattr(stage, "groups", None)
                if groups:
                    group_name = getattr(groups[0], "name", None) if groups else None
            except Exception:
                group_name = None

        is_bye = bool(
            not raw_player2
            or str(raw_player2).strip().upper() == "BYE"
        )

        p1_id = getattr(m, "player1_id", None)
        p2_id = getattr(m, "player2_id", None)
        seed1 = _seed_map.get(p1_id) if p1_id else None
        seed2 = _seed_map.get(p2_id) if p2_id else None

        entry = {
            "id": getattr(m, "id", None),
            "round": round_number,
            "bracket_index": getattr(m, "bracket_index", None) or 0,
            "player1": player1,
            "player2": player2,
            "winner": getattr(m, "winner", None),
            "score": getattr(m, "score", None),
            "status": status_str,
            "table": getattr(m, "location", None),
            "bye": is_bye,
            "seed1": seed1,
            "seed2": seed2,
            "stage_type": stage_type,
            "group_name": group_name,
        }
        # A match is "valid" (fully renderable) when it has an id and at least
        # one real (non-TBD) player.
        entry["valid"] = bool(
            entry["id"] is not None
            and (player1 != "TBD" or player2 != "TBD")
        )
        normalized.append(entry)

    # Stable ordering: by round, then bracket position.
    normalized.sort(key=lambda e: (e["round"] or 0, e["bracket_index"] or 0))
    return normalized


def _render_match_card(match):
    """Render a single match as a readable, theme-aware bordered card."""
    status = (match.get("status") or "pending").lower()
    status_label = {
        "completed": "✅ Completed",
        "active": "🔴 Live",
        "pending": "⏳ Pending",
    }.get(status, f"• {status.title()}")

    winner = match.get("winner")
    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    p1_disp = f"**{p1}** 🏆" if winner and winner == p1 else p1
    p2_disp = f"**{p2}** 🏆" if winner and winner == p2 else p2

    seed1 = match.get("seed1")
    seed2 = match.get("seed2")
    if seed1 and p1 != "TBD":
        p1_disp = f"**{p1}** 🏆" if winner and winner == p1 else p1
        p1_disp = f"[S{seed1}] {p1_disp}"
    if seed2 and p2 != "TBD":
        p2_disp = f"**{p2}** 🏆" if winner and winner == p2 else p2
        p2_disp = f"[S{seed2}] {p2_disp}"

    bye_label = "BYE" if match.get("bye") else None

    # st.container(border=True) is theme-aware (readable in dark mode) and does
    # not depend on any custom HTML/JS/CDN, so it can never render blank.
    with st.container(border=True):
        if bye_label:
            st.markdown(f"**{p1_disp}**  \n*{bye_label}*")
        else:
            st.markdown(f"{p1_disp}  \n{p2_disp}")
        meta = [status_label]
        if match.get("score"):
            meta.insert(0, f"Score: {match['score']}")
        if match.get("table"):
            meta.append(f"Table {match['table']}")
        if match.get("group_name"):
            meta.append(f"Group: {match['group_name']}")
        st.caption(" · ".join(meta))
        render_pairing_expander(match)


def render_bracket_fallback(matches):
    """
    Reliable, Streamlit-native bracket renderer (no custom HTML/JS/CDN).

    Groups matches by round and renders each round as a column of match cards.
    This is used as the always-visible primary view so the Interactive Bracket
    section can never appear blank.

    Args:
        matches: A list of normalized match dicts (see ``normalize_bracket_matches``).
    """
    if not matches:
        st.info("No matches to display.")
        return

    grouped = {}
    for m in matches:
        grouped.setdefault(m["round"], []).append(m)

    rounds = sorted(grouped.keys())

    # Knockout-style side-by-side columns when there are few rounds; otherwise
    # (e.g. round-robin with many rounds) stack them so nothing gets squashed.
    if 1 <= len(rounds) <= 6:
        cols = st.columns(len(rounds))
        for col, rnd in zip(cols, rounds):
            with col:
                st.markdown(f"**Round {rnd}**")
                for match in grouped[rnd]:
                    _render_match_card(match)
    else:
        for rnd in rounds:
            st.markdown(f"**Round {rnd}**")
            round_cols = st.columns(min(len(grouped[rnd]), 4) or 1)
            for i, match in enumerate(grouped[rnd]):
                with round_cols[i % len(round_cols)]:
                    _render_match_card(match)


def _detect_tournament_format(matches):
    """Detect tournament format from match/stage data.

    Returns one of: "knockout", "groups", "swiss", "round_robin", "unknown".
    """
    if not matches:
        return "unknown"

    stage_types = set()
    for m in matches:
        stage = getattr(m, "stage", None)
        if stage is not None:
            stype = getattr(stage, "stage_type", None)
            if stype:
                stage_types.add(stype)

    if "group" in stage_types:
        return "groups"
    if "swiss" in stage_types:
        return "swiss"
    if "knockout" in stage_types:
        return "knockout"

    all_have_rounds = all(getattr(m, "round_number", None) is not None for m in matches)
    if all_have_rounds:
        return "knockout"

    return "unknown"


def build_safe_bracket_payload(matches, tournament_format: str) -> dict:
    """Build a JSON-safe payload for the interactive bracket component."""
    safe_matches = []
    for m in matches:
        status = getattr(m, "status", None)
        if hasattr(status, "value"):
            status = status.value
        status = str(status or "pending")

        score = getattr(m, "score", None)
        score = str(score or "")

        safe_matches.append({
            "id": int(getattr(m, "id", 0) or 0),
            "round": int(getattr(m, "round_number", None) or 1),
            "match_number": int(getattr(m, "bracket_index", None) or 0),
            "player1": str(getattr(m, "player1", None) or "TBD"),
            "player2": str(getattr(m, "player2", None) or "TBD"),
            "score": score,
            "game_scores": [],
            "status": status,
            "winner": str(getattr(m, "winner", None) or ""),
            "table": str(getattr(m, "location", None) or ""),
            "is_bye": bool(
                not getattr(m, "player2", None)
                or str(getattr(m, "player2", None)).strip().upper() == "BYE"
            ),
        })

    return {
        "stages": [
            {
                "id": 0,
                "name": "Main Stage",
                "type": tournament_format,
                "settings": {"size": calculate_bracket_size(len(safe_matches))},
            }
        ],
        "matches": safe_matches,
        "participants": [],
    }


def _validate_bracket_payload(payload: dict) -> None:
    """Raise if payload contains non-JSON-safe values."""
    import json
    json.dumps(payload)


def render_bracket(tournament, all_players):
    """
    Render the Interactive Bracket section for a tournament.

    Guarantees the section is never blank by always rendering a reliable,
    Streamlit-native bracket (grouped by round). The richer interactive visual
    component is offered as an opt-in enhancement inside a collapsed expander,
    because an iframe that fails to load produces a silent zero-height frame
    that Python cannot detect via try/except.

    Rendered states:
      * No tournament -> empty state.
      * Tournament but no matches -> "no bracket yet" state + generate CTA.
      * Matches present -> native bracket (always visible) + optional visual
        bracket + diagnostics.

    Args:
        tournament: The Tournament object to render
        all_players: List of all Player objects
    """
    st.subheader("📊 Interactive Bracket")

    if tournament is None:
        render_empty_state(
            icon="🗂️",
            title="No tournament selected",
            description="No tournament selected. Choose or create a tournament to view the bracket.",
        )
        return

    matches = list(getattr(tournament, "matches", None) or [])
    if not matches:
        render_empty_state(
            icon="🗂️",
            title="No bracket has been generated yet",
            description=(
                "No bracket has been generated yet. Generate draws or add "
                "participants to build the bracket."
            ),
            cta_label="Generate Draws",
            cta_key=f"generate_draws_{tournament.id}",
        )
        return

    tournament_format = _detect_tournament_format(matches)

    # --- Reassemble tournament object from session to avoid detached-instance
    #     errors when `normalize_bracket_matches` accesses lazy relationships.
    db = SessionLocal()
    try:
        db_tournament = db.query(Tournament).get(getattr(tournament, "id", None))
        if db_tournament is not None:
            from sqlalchemy.orm import selectinload
            db_matches = db.query(Match).options(
                selectinload(Match.stage).selectinload(Stage.groups)
            ).filter(Match.tournament_id == db_tournament.id).all()
            db_tournament.matches = db_matches
            matches = db_matches
            tournament = db_tournament

        normalized = normalize_bracket_matches(matches, all_players, db=db)
    finally:
        db.close()

    # --- Format-aware routing ------------------------------------------------
    if tournament_format == "groups":
        rounds = sorted({m["round"] for m in normalized})
        st.markdown("**Group stage matches**")
        render_bracket_fallback(normalized)
        st.caption(
            "Knockout bracket will appear after the group stage is completed."
        )
        return

    if tournament_format == "swiss":
        st.markdown("**Swiss pairings**")
        render_bracket_fallback(normalized)
        st.caption(
            "Swiss standings update after each round. Knockout bracket will "
            "appear if a knockout stage is generated later."
        )
        return

    if tournament_format == "round_robin":
        st.markdown("**Round-robin fixtures**")
        render_bracket_fallback(normalized)
        return

    # --- Knockout: native fallback first (always visible) --------------------
    try:
        render_bracket_fallback(normalized)
    except Exception as exc:  # noqa: BLE001 - native fallback must never crash the page
        logger.exception(
            "Native bracket renderer failed for tournament %s", getattr(tournament, "id", None)
        )
        st.warning("Interactive bracket unavailable. Showing native bracket view.")
        try:
            render_bracket_fallback(normalized)
        except Exception:
            st.error("The bracket could not be displayed. Please try refreshing.")
            if st.button("🔄 Refresh bracket", key=f"refresh_bracket_{getattr(tournament, 'id', None)}"):
                st.rerun()

    # --- Interactive visual bracket (knockout only) --------------------------
    if tournament_format != "knockout":
        return

    with st.expander("🎯 Interactive visual bracket (beta)", expanded=False):
        st.caption(
            "Requires the bracket libraries to load. If this appears blank, "
            "use the match list above."
        )
        try:
            payload = build_safe_bracket_payload(matches, tournament_format)
            _validate_bracket_payload(payload)

            if payload and payload.get("matches"):
                clicked = interactive_bracket(payload, key=f"bracket_{getattr(tournament, 'id', None)}")
                if clicked:
                    st.session_state['selected_match_from_bracket'] = clicked
                    st.toast("Match selected!")
            else:
                st.info("No bracket data available to visualize.")
        except Exception as exc:  # noqa: BLE001 - interactive bracket is optional
            logger.exception(
                "Interactive visual bracket failed for tournament %s", getattr(tournament, "id", None)
            )
            st.warning("Interactive bracket unavailable. Showing native bracket view.")
            st.caption(f"Details: {type(exc).__name__}")

    # --- Diagnostics (collapsed; unobtrusive for normal users) -------------
    with st.expander("🔧 Bracket diagnostics", expanded=False):
        try:
            rounds = sorted({m["round"] for m in normalized})
            payload = build_safe_bracket_payload(matches, tournament_format)
            try:
                import json
                json.dumps(payload)
                json_ok = True
            except Exception:
                json_ok = False

            st.write(
                {
                    "tournament_id": getattr(tournament, "id", None),
                    "tournament_name": getattr(tournament, "name", None),
                    "tournament_format": tournament_format,
                    "match_count": len(normalized),
                    "round_count": len(rounds),
                    "rounds": rounds,
                    "valid_matches": sum(1 for m in normalized if m.get("valid")),
                    "payload_json_safe": json_ok,
                    "interactive_attempted": tournament_format == "knockout",
                    "renderer": "native fallback (primary) + interactive (beta, knockout only)",
                }
            )
        except Exception:  # noqa: BLE001 - diagnostics must never break the page
            st.caption("Diagnostics unavailable.")


def render_standings(tournament):
    """
    Render the round-robin standings for a tournament.
    
    Args:
        tournament: The Tournament object to show standings for
    """
    st.subheader("🏆 Round-Robin Standings")
    
    db = SessionLocal()
    all_players = db.query(Player).all()
    matches_data = []
    for m in tournament.matches:
        match_entry = {
            "id": m.id,
            "number": m.bracket_index or 0,
            "stageId": 0,
            "groupId": 0,
            "roundId": (m.round_number or 1) - 1,
            "status": 4 if m.status == MatchStatus.completed else 2,
            "opponent1": {"id": None, "score": None},
            "opponent2": {"id": None, "score": None}
        }
        p1 = next((p for p in all_players if p.name == m.player1), None)
        p2 = next((p for p in all_players if p.name == m.player2), None)
        if p1:
            match_entry["opponent1"]["id"] = p1.id
        if p2:
            match_entry["opponent2"]["id"] = p2.id
        if m.status == MatchStatus.completed:
            try:
                s1, s2 = map(int, m.score.split('-'))
                match_entry["opponent1"]["score"] = s1
                match_entry["opponent2"]["score"] = s2
            except:
                pass
        matches_data.append(match_entry)
    
    # Calculate dynamic bracket size based on participant count
    bracket_size = calculate_bracket_size(len(all_players))
    
    bracket_data = {
        "stages": [{"id": 0, "name": "Main Stage", "type": "single_elimination", "settings": {"size": bracket_size}}],
        "matches": matches_data,
        "participants": [{"id": p.id, "name": p.name} for p in all_players]
    }
    
    ts = TournamentState(data=bracket_data)
    standings = ts.calculate_standings()
    
    if standings:
        standings_df = pd.DataFrame(standings)
        standings_df = standings_df.rename(columns={
            "name": "Player",
            "wins": "W",
            "losses": "L",
            "matches_played": "MP",
            "points_for": "PF",
            "points_against": "PA"
        })
        standings_df = standings_df[["Player", "MP", "W", "L", "PF", "PA"]]
        st.table(standings_df)
        
        # Add tie-break explanation
        st.caption(
            "Standings: sorted by Wins (descending), then Points For - Points Against (descending). "
            "Note: Round-robin tie-breaks (head-to-head, etc.) are not yet implemented."
        )
    else:
        st.info("No completed matches yet to calculate standings.")
    
    db.close()


def render_group_standings(tournament, all_players):
    """
    Render the group standings for a Groups → Knockout tournament.
    
    Args:
        tournament: The Tournament object to show group standings for
        all_players: List of all Player objects
    """
    st.subheader("📊 Group Standings")
    
    # Get matches grouped by stage
    group_matches = [m for m in tournament.matches if m.stage and m.stage.stage_type == "group"]
    
    if not group_matches:
        st.info("No group matches yet. Generate the tournament first.")
        return
    
    # Group matches by group name
    groups_data = {}
    for match in group_matches:
        group_name = match.stage.name if match.stage else "Group A"
        if group_name not in groups_data:
            groups_data[group_name] = []
        groups_data[group_name].append(match)
    
    # Render each group's standings
    for group_name, matches in groups_data.items():
        with st.expander(f"📌 {group_name}", expanded=True):
            # Build bracket data for this group
            participants = [{"id": p.id, "name": p.name} for p in all_players]
            matches_data = []
            
            for m in matches:
                match_entry = {
                    "id": m.id,
                    "number": m.bracket_index or 0,
                    "stageId": 0,
                    "groupId": 0,
                    "roundId": (m.round_number or 1) - 1,
                    "status": 4 if m.status == MatchStatus.completed else 2,
                    "opponent1": {"id": None, "score": None},
                    "opponent2": {"id": None, "score": None}
                }
                p1 = next((p for p in all_players if p.name == m.player1), None)
                p2 = next((p for p in all_players if p.name == m.player2), None)
                if p1:
                    match_entry["opponent1"]["id"] = p1.id
                if p2:
                    match_entry["opponent2"]["id"] = p2.id
                if m.status == MatchStatus.completed:
                    try:
                        s1, s2 = map(int, m.score.split('-'))
                        match_entry["opponent1"]["score"] = s1
                        match_entry["opponent2"]["score"] = s2
                    except:
                        pass
                matches_data.append(match_entry)
            
            bracket_data = {
                "stages": [{"id": 0, "name": group_name, "type": "round_robin", "settings": {"size": len(participants)}}],
                "matches": matches_data,
                "participants": participants
            }
            
            ts = TournamentState(data=bracket_data)
            standings = ts.calculate_standings()
            
            if standings:
                standings_df = pd.DataFrame(standings)
                standings_df = standings_df.rename(columns={
                    "name": "Player",
                    "wins": "W",
                    "losses": "L",
                    "matches_played": "MP",
                    "points_for": "PF",
                    "points_against": "PA"
                })
                standings_df = standings_df[["Player", "MP", "W", "L", "PF", "PA"]]
                st.table(standings_df)
                
                st.caption(
                    "Standings: sorted by Wins (descending), then Points For - Points Against (descending). "
                    "Top qualifiers advance to knockout stage."
                )
            else:
                st.info("No completed matches yet in this group.")


def render_tournament_generation(tournament):
    """
    Render the tournament generation controls for a tournament without matches.
    
    Args:
        tournament: The Tournament object to generate matches for
    """
    st.write("**Generate Tournament Bracket**")
    db = SessionLocal()
    all_players = db.query(Player).all()
    player_names = [p.name for p in all_players]

    # Build participant-sourced player name lists if self-registration is enabled
    participant_options = []
    checked_in_options = []
    if settings.ENABLE_SELF_REGISTRATION:
        participants = (
            db.query(TournamentParticipant)
            .filter(TournamentParticipant.tournament_id == tournament.id)
            .all()
        )
        participant_options = sorted({p.display_name for p in participants if p.display_name})
        checked_in_participants = [p for p in participants if p.checked_in]
        checked_in_options = sorted({p.display_name for p in checked_in_participants if p.display_name})

        pending_count = sum(1 for p in participants if p.duplicate_status == "pending_review")
        if pending_count > 0:
            st.warning(
                f"{pending_count} participant(s) have pending duplicate reviews "
                "and will be excluded from bracket generation by default."
            )
    db.close()

    bracket_source = "manual"
    if settings.ENABLE_SELF_REGISTRATION and (participant_options or checked_in_options):
        bracket_source = st.radio(
            "Bracket Source",
            options=["manual", "registered", "checked_in"],
            format_func=lambda x: {
                "manual": "Manually selected (all players)",
                "registered": "All registered participants",
                "checked_in": "Checked-in only",
            }[x],
            horizontal=True,
            key=f"bracket_source_{tournament.id}",
            help="Choose which players to include in the bracket.",
        )

    if bracket_source == "manual":
        available_names = player_names
    elif bracket_source == "registered":
        available_names = participant_options
    else:
        available_names = checked_in_options

    if not available_names:
        st.info("No players available for the selected bracket source.")
        return

    default_selection = available_names[:8] if len(available_names) >= 8 else available_names
    selected_players = st.multiselect(
        f"Select players for {tournament.name}",
        options=available_names,
        default=default_selection,
        key=f"players_{tournament.id}",
    )
    
    default_format = "Knockout" if tournament.tournament_type == TournamentType.knockout else "Round-Robin"
    tournament_format = st.selectbox(
        "Tournament Format",
        options=["Knockout", "Round-Robin", "Groups → Knockout"],
        index=0 if default_format == "Knockout" else (1 if default_format == "Round-Robin" else 2),
        key=f"format_{tournament.id}"
    )
    
    # Groups → Knockout configuration
    num_groups = 2
    qualifiers_per_group = 2
    if tournament_format == "Groups → Knockout":
        col1, col2 = st.columns(2)
        with col1:
            num_groups = st.number_input(
                "Number of Groups",
                min_value=2,
                max_value=8,
                value=2,
                key=f"num_groups_gen_{tournament.id}"
            )
        with col2:
            qualifiers_per_group = st.number_input(
                "Qualifiers per Group",
                min_value=1,
                max_value=4,
                value=2,
                key=f"qualifiers_gen_{tournament.id}"
            )
    
    if ui.button(f"🏆 Generate {tournament_format}", key=f"gen_{tournament.id}"):
        if len(selected_players) < 2:
            st.toast("Please select at least 2 players", icon="⚠️")
        else:
            try:
                if tournament_format == "Groups → Knockout":
                    selected_strategy = GroupsKnockoutStrategy(
                        num_groups=num_groups,
                        qualifiers_per_group=qualifiers_per_group
                    )
                else:
                    strategies = {
                        "Knockout": KnockoutStrategy(),
                        "Round-Robin": RoundRobinStrategy()
                    }
                    selected_strategy = strategies[tournament_format]
                context = TournamentContext(selected_strategy)
                context.run_generation(selected_players, tournament.id, db)
                
                st.toast("✅ Tournament generated successfully!", icon="🏆")
                st.rerun()
            except Exception as e:
                st.error(f"Error generating tournament: {e}")
            finally:
                db.close()


def render_active_tournaments():
    """
    Render the active tournaments tab with bracket visualization and standings.
    """
    st.subheader("🏆 Active Tournaments")
    
    db = SessionLocal()
    tournaments = db.query(Tournament).options(
        selectinload(Tournament.matches).selectinload(Match.stage)
    ).order_by(Tournament.name.asc()).all()
    db.close()

    if "active_tournament_id" not in st.session_state:
        st.session_state["active_tournament_id"] = tournaments[0].id if tournaments else None

    if not tournaments:
        st.info("No tournaments created yet.")
        if st.button("Create Tournament", type="primary"):
            st.session_state['wizard_step'] = 1
            st.switch_page("pages/events_draws.py")
        return

    tournament_options = {t.name: t.id for t in tournaments}
    current = st.session_state.get("active_tournament_id")
    if current not in tournament_options.values():
        current = tournaments[0].id
        st.session_state["active_tournament_id"] = current

    active_name = next((n for n, tid in tournament_options.items() if tid == current), tournaments[0].name)
    selected_name = st.selectbox(
        "Active tournament",
        options=list(tournament_options.keys()),
        index=list(tournament_options.keys()).index(active_name),
        key="events_active_tournament_select",
    )
    st.session_state["active_tournament_id"] = tournament_options[selected_name]

    tournament = next((t for t in tournaments if t.id == tournament_options[selected_name]), None)
    if tournament is None:
        st.info("No tournaments created yet.")
        return

    with st.expander(f"📌 {tournament.name}", expanded=True):
        st.write(f"**Type:** {tournament.tournament_type.value.title()}")
        st.write(f"**Description:** {tournament.description or 'No description'}")
        st.write(f"**Created:** {tournament.created_at.strftime('%Y-%m-%d')}")
        
        # Show matches in tournament
        if tournament.matches:
            st.write("**Matches:**")
            sorted_matches = sorted(tournament.matches, key=lambda m: (m.round_number or 0, m.bracket_index or 0))
            for match in sorted_matches:
                cols = st.columns([4, 1])
                with cols[0]:
                    st.write(
                        f"Round {match.round_number or '?'}: {match.player1} vs {match.player2} | "
                        f"Winner: {match.winner or 'TBD'}"
                    )
                with cols[1]:
                    render_status_badge(match.status.value, key=f"status_{match.id}")
            
            # Bracket Visualization
            st.space("medium")
            all_players = db.query(Player).all()
            render_bracket(tournament, all_players)
            
            # Show Standings for Round-Robin
            if tournament.tournament_type == TournamentType.round_robin:
                st.space("medium")
                render_standings(tournament)
            
            # Show Group Standings for Groups → Knockout
            if tournament.matches and any(m.stage and m.stage.stage_type == "group" for m in tournament.matches):
                st.space("medium")
                all_players = db.query(Player).all()
                render_group_standings(tournament, all_players)
        else:
            st.write("No matches yet")
            st.space("medium")
            render_tournament_generation(tournament)
    
    db.close()


def render_events_draws():
    """Render the main Events & Draws page."""
    st.set_page_config(page_title="LIT_IT Events & Draws", page_icon="🎫", layout="wide")
    apply_global_styles()

    from tournament_platform.app.components.page_header import render_page_header

    render_page_header(
        title="LIT_IT Events & Draws",
        icon_name="tournament",
    )
    render_tour("tournament")

    tab_create, tab_participants, tab_draws = st.tabs(["Create Tournament", "Participants", "Active Tournaments"])

    with tab_create:
        render_tournament_creation_wizard()

    with tab_participants:
        tournament_id_for_participants = None
        if settings.ENABLE_SELF_REGISTRATION:
            if "active_tournament_id" in st.session_state and st.session_state["active_tournament_id"] is not None:
                tournament_id_for_participants = st.session_state["active_tournament_id"]
            else:
                st.caption("Select a tournament to manage registration and check-in.")
                tournament_id_for_participants = _get_tournament_selector_for_participants()
        render_participants_panel(tournament_id=tournament_id_for_participants)

    with tab_draws:
        render_active_tournaments()


# This allows the page to be run directly or via Streamlit's multi-page app
if __name__ == "__main__":
    render_events_draws()
