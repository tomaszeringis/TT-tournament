"""
TT-specific template phrase bank for the local commentary engine.

Structure
---------
``TEMPLATE_BANK[event_type][language][style][commentary_type] -> List[str]``

Languages: ``lt``, ``en``.
Styles: ``neutral``, ``professional``, ``coach``, ``announcer``, ``short``.
Commentary types: ``play_by_play``, ``tactical``, ``coaching``, ``momentum``,
                   ``summary``.

Missing slots fall back to the legacy ``tournament_platform.services.commentary_templates``
phrase bank so existing coverage remains intact.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from tournament_platform.services.commentary_templates import (
    looks_english_in_lithuanian,
    normalize_language,
    normalize_style,
    render_template,
    select_event_template,
    _LT_FORBIDDEN_EN_FRAGMENTS,
    _SafeDict,
)

from tournament_platform.app.services.commentary.event_schema import TTEventType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUPPORTED_STYLES = {"neutral", "professional", "coach", "announcer", "short"}
_SUPPORTED_COMMENTARY_TYPES = {"play_by_play", "tactical", "coaching", "momentum", "summary"}
_SHORT_ALIAS = {"short", "minimal", "kids"}

_COMMENTARY_TYPE_ALIASES = {
    "pbp": "play_by_play",
    "tactical": "tactical",
    "coach": "coaching",
    "coaching": "coaching",
    "momentum": "momentum",
    "summary": "summary",
}


def normalize_commentary_type(ct_type: Any) -> str:
    if hasattr(ct_type, "value"):
        ct_type = ct_type.value
    s = str(ct_type or "play_by_play").strip().lower()
    return _COMMENTARY_TYPE_ALIASES.get(s, "play_by_play")


def _fmt_rally(rally_length: Optional[int]) -> str:
    if rally_length is None:
        return ""
    if rally_length >= 9:
        return "ilgas"
    if rally_length <= 3:
        return "trumpas"
    return "vidutinis"


# ---------------------------------------------------------------------------
# Template bank
# ---------------------------------------------------------------------------

_TEMPLATE_BANK: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {
    TTEventType.POINT_WON.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Taškas {winner}. {score}.",
                    "{winner} laimi tašką. {score}.",
                ],
                "coaching": [
                    "Gerai, {winner}. {score}.",
                    "Taškas {winner}. Išlaikyk tempą.",
                ],
            },
            "professional": {
                "play_by_play": [
                    "{winner} laimi tašką, rezultatas {score}.",
                    "Taškas žaidėjui {winner}, rezultatas {score}.",
                ],
            },
            "coach": {
                "coaching": [
                    "{winner} laimi tašką, {score}. Tęsk taip toliau.",
                    "Gerai, {winner}. {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Taškas {winner}! {score}.",
                    "{winner} pelno tašką, {score}!",
                ],
            },
            "short": {
                "play_by_play": [
                    "Taškas {winner}.",
                ],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Point {winner}. {score}.",
                    "{winner} takes it. {score}.",
                ],
                "coaching": [
                    "Good point, {winner}. {score}.",
                    "Nice one, {winner}. {score}.",
                ],
            },
            "professional": {
                "play_by_play": [
                    "{winner} takes the point and moves ahead, {score}.",
                    "Point to {winner}, now {score}.",
                ],
            },
            "coach": {
                "coaching": [
                    "{winner} wins the point, {score}. Keep the same rhythm next serve.",
                    "Good point, {winner}. {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "And {winner} takes the point, {score}!",
                    "{winner} with the point, {score}.",
                ],
            },
            "short": {
                "play_by_play": [
                    "Point {winner}.",
                ],
            },
        },
    },
    TTEventType.POINT_LOST.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Taškas {opponent}. {score}.",
                ],
                "coaching": [
                    "Praleidai tašką, {player}. {score}. Susitelk.",
                ],
            },
            "short": {
                "play_by_play": ["{player} prarado tašką."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Point {opponent}. {score}.",
                ],
                "coaching": [
                    "You lost that one, {player}. {score}. Stay focused.",
                ],
            },
            "short": {
                "play_by_play": ["{player} lost the point."],
            },
        },
    },
    TTEventType.SERVE_POINT.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Servuoja {serving_player}. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Servas {serving_player}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Serve to {serving_player}. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Serve {serving_player}."],
            },
        },
    },
    TTEventType.RALLY_POINT.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Taškas {winner} po {rally_length} smūgių. {score}.",
                    "{winner} laimėjo {rally_length} smūgių mainus. {score}.",
                ],
                "tactical": [
                    "{rally_length} smūgių mainai — {winner} laimėjo.",
                    "Vidutinė mainų serija. {winner} pirmauja, {score}.",
                ],
            },
            "short": {
                "play_by_play": ["{winner} laimėjo {rally_length} smūgių mainus."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Point {winner} after {rally_length} shots. {score}.",
                    "{winner} wins the {rally_length}-shot rally. {score}.",
                ],
                "tactical": [
                    "{rally_length}-shot rally — {winner} takes it.",
                    "Medium rally. {winner} leads, {score}.",
                ],
            },
            "short": {
                "play_by_play": ["{winner} wins the {rally_length}-shot rally."],
            },
        },
    },
    TTEventType.NET_ERROR.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Tinklo klaida. {score}.",
                    "{player} per klaidą tinkle. {score}.",
                ],
                "tactical": [
                    "Klaida prie tinklo — {player}. {score}.",
                    "Tinklo klaida. {player}, būk atsargus. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Tinklo klaida."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Net error. {score}.",
                    "{player} hits the net. {score}.",
                ],
                "tactical": [
                    "Net error by {player}. {score}.",
                    "Error at the net — {player}. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Net error."],
            },
        },
    },
    TTEventType.EDGE_OR_LUCKY_POINT.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Sėkmė — {winner} laimi tašką. {score}.",
                    "Staigmena! {winner} laimėjo. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Sėkmė! {winner} laimėjo."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Lucky point for {winner}. {score}.",
                    "Edge ball — {winner} takes it. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Lucky point — {winner}."],
            },
        },
    },
    TTEventType.FOREHAND_WINNER.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Smūgis dešine pergalė — {winner}. {score}.",
                    "{winner} laimėjo dešiniuoju smūgiu. {score}.",
                ],
                "tactical": [
                    "Pergalingas dešinysis smūgis! {winner} rodo galią, {score}.",
                    "Dešinysis smūgis laimėjo — {winner}. {score}.",
                ],
            },
            "coach": {
                "tactical": [
                    "Geras dešinysis smūgis, {winner}. {score}.",
                    "{winner} su dešiniuoju — tęsk taip. {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Dešinysis smūgis! {winner}! {score}!",
                    "Pergalingas dešinys — {winner}! {score}!",
                ],
            },
            "short": {
                "play_by_play": ["{winner} dešiniuoju!"],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Forehand winner by {winner}. {score}.",
                    "{winner} closes it with a forehand. {score}.",
                ],
                "tactical": [
                    "Forehand winner! {winner} shows the power, {score}.",
                    "{winner} puts it away with the forehand. {score}.",
                ],
            },
            "coach": {
                "tactical": [
                    "Nice forehand, {winner}. {score}.",
                    "Keep attacking with the forehand, {winner}. {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Forehand! {winner}! {score}!",
                    "What a forehand — {winner}! {score}!",
                ],
            },
            "short": {
                "play_by_play": ["Forehand winner by {winner}."],
            },
        },
    },
    TTEventType.BACKHAND_WINNER.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Atgalinis smūgis pergalė — {winner}. {score}.",
                    "{winner} laimėjo atgaliniuoju smūgiu. {score}.",
                ],
                "tactical": [
                    "Atgalinis smūgis laimėjo! {winner}. {score}.",
                    "Pergalingas atgalinysis — {winner}. {score}.",
                ],
            },
            "coach": {
                "tactical": [
                    "Geras atgalinysis smūgis, {winner}. {score}.",
                    "{winner} su atgaliniuoju — gerai. {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Atgalinysis smūgis! {winner}! {score}!",
                    "Pergalingas atgalinys — {winner}! {score}!",
                ],
            },
            "short": {
                "play_by_play": ["{winner} atgaliniuoju!"],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Backhand winner by {winner}. {score}.",
                    "{winner} finishes with a backhand. {score}.",
                ],
                "tactical": [
                    "Backhand winner! {winner}. {score}.",
                    "{winner} puts it away cross-court backhand. {score}.",
                ],
            },
            "coach": {
                "tactical": [
                    "Nice backhand, {winner}. {score}.",
                    "Good backhand shot, {winner}. {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Backhand! {winner}! {score}!",
                    "What a backhand — {winner}! {score}!",
                ],
            },
            "short": {
                "play_by_play": ["Backhand winner by {winner}."],
            },
        },
    },
    TTEventType.FOREHAND_ERROR.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Klaida dešiniuoju — {player}. {score}.",
                    "{player} per klaidą dešiniuoju. {score}.",
                ],
                "tactical": [
                    "Klaida dešiniuoju smūgiu. {player}, kontroliuok. {score}.",
                    "Dešinysis smūgis per klaidą — {player}. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Klaida dešiniuoju."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Forehand error by {player}. {score}.",
                    "{player} misses the forehand. {score}.",
                ],
                "tactical": [
                    "Forehand error — {player}. {score}.",
                    "{player} goes for too much on the forehand. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Forehand error by {player}."],
            },
        },
    },
    TTEventType.BACKHAND_ERROR.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Klaida atgaliniuoju — {player}. {score}.",
                    "{player} per klaidą atgaliniuoju. {score}.",
                ],
                "tactical": [
                    "Klaida atgaliniuoju smūgiu. {player}. {score}.",
                    "Atgalinysis per klaidą — {player}. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Klaida atgaliniuoju."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Backhand error by {player}. {score}.",
                    "{player} misses the backhand. {score}.",
                ],
                "tactical": [
                    "Backhand error — {player}. {score}.",
                    "{player} overhits the backhand. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Backhand error by {player}."],
            },
        },
    },
    TTEventType.LONG_RALLY.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Ilgi mainai — {rally_length} smūgiai. {winner} laimi. {score}.",
                    "{rally_length} smūgių mainų serija. {winner} pirmauja, {score}.",
                ],
                "tactical": [
                    "Ilgas mainų tauras — {rally_length} smūgiai. {winner} laimėjo.",
                    "Endurance test: {rally_length} smūgiai. {winner} pirmauja, {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Ilgi mainai! {rally_length} smūgių! {winner}! {score}!",
                ],
            },
            "short": {
                "play_by_play": ["Ilgi mainai — {winner} laimėjo."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Long rally — {rally_length} shots. {winner} takes it. {score}.",
                    "{rally_length}-shot exchange. {winner} leads, {score}.",
                ],
                "tactical": [
                    "Long rally, {rally_length} shots. {winner} prevails.",
                    "Endurance test: {rally_length} shots. {winner} leads, {score}.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "What a rally! {rally_length} shots! {winner}! {score}!",
                ],
            },
            "short": {
                "play_by_play": ["Long rally — {winner} takes it."],
            },
        },
    },
    TTEventType.SHORT_RALLY.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Trumpi mainai — {rally_length} smūgiai. {winner} laimi. {score}.",
                    "Greitas taškas po {rally_length} smūgių. {winner}, {score}.",
                ],
                "tactical": [
                    "Greitas taškas, {rally_length} smūgiai. {winner} laimėjo.",
                    "Trumpi mainai — {winner} užbaigė greitai. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Greitas taškas — {winner}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Short rally — {rally_length} shots. {winner} takes it. {score}.",
                    "Quick point, {rally_length} shots. {winner}, {score}.",
                ],
                "tactical": [
                    "Short rally, {rally_length} shots. {winner} finishes fast.",
                    "Quick point — {winner} ends it early. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Quick point — {winner}."],
            },
        },
    },
    TTEventType.DEUCE.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Lygiosios. {score}.",
                    "Rezultatas lygus.",
                ],
            },
            "short": {
                "play_by_play": ["Lygiosios."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Deuce. {score}.",
                    "Back to deuce.",
                ],
            },
            "short": {
                "play_by_play": ["Deuce."],
            },
        },
    },
    TTEventType.ADVANTAGE.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Pranašumas {winner}. {score}.",
                    "{winner} turi pranašumą. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Pranašumas {winner}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Advantage {winner}. {score}.",
                    "{winner} has advantage. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Advantage {winner}."],
            },
        },
    },
    TTEventType.GAME_POINT.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Geimo taškas {winner}. {score}.",
                    "{winner} turi geimo tašką. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Geimo taškas {winner}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Game point {winner}. {score}.",
                    "{winner} has game point. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Game point {winner}."],
            },
        },
    },
    TTEventType.MATCH_POINT.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Mačo taškas {winner}. {score}.",
                    "{winner} turi mačo tašką. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Mačo taškas {winner}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Match point {winner}. {score}.",
                    "{winner} has match point. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Match point {winner}."],
            },
        },
    },
    TTEventType.GAME_WON.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Geimą laimi {winner}, {game_score}.",
                    "{winner} laimi {game_number} geimą.",
                ],
                "summary": [
                    "Geimas baigtas. {winner} laimi {game_score}.",
                    "{winner} užbaigia geimą, {game_score}.",
                ],
                "coaching": [
                    "Geimą laimi {winner}, {game_score}. Gerai sužaista.",
                    "{winner} laimi geimą. Ruoškis kitam.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Geimas {winner}! {game_score}!",
                    "Štai geimas žaidėjui {winner}!",
                ],
            },
            "short": {
                "play_by_play": ["Geimas {winner}."],
                "summary": ["Geimas {winner}, {game_score}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Game to {winner}, {game_score}.",
                    "{winner} takes game {game_number}, {game_score}.",
                ],
                "summary": [
                    "Game over. {winner} wins {game_score}.",
                    "{winner} closes out the game, {game_score}.",
                ],
                "coaching": [
                    "Game to {winner}, {game_score}. Well played.",
                    "{winner} takes game {game_number}. Regroup for the next one.",
                ],
            },
            "announcer": {
                "play_by_play": [
                    "Game {winner}! {game_score}!",
                    "That's the game for {winner}!",
                ],
            },
            "short": {
                "play_by_play": ["Game {winner}."],
                "summary": ["Game {winner}, {game_score}."],
            },
        },
    },
    TTEventType.MATCH_WON.value: {
        "lt": {
            "neutral": {
                "summary": [
                    "Mačą laimi {winner}, {match_score}.",
                    "Pergalė — {winner}. Rezultatas {match_score}.",
                ],
            },
            "short": {
                "summary": ["Mačas {winner}, {match_score}."],
            },
        },
        "en": {
            "neutral": {
                "summary": [
                    "{winner} wins the match, {match_score}.",
                    "Match complete. {winner} wins, {match_score}.",
                ],
            },
            "short": {
                "summary": ["Match {winner}, {match_score}."],
            },
        },
    },
    TTEventType.COMEBACK.value: {
        "lt": {
            "neutral": {
                "momentum": [
                    "{winner} atsigavo iš atsilikimo ir išlygino rezultatą.",
                    "Puikus sugrįžimas — {winner}. {score}.",
                ],
                "play_by_play": [
                    "{winner} grįžta į kovą.",
                    "Rezultatas vėl lygus.",
                ],
            },
            "short": {
                "play_by_play": ["Vėl lygu."],
                "momentum": ["Sugrįžimas! {winner} išlygino."],
            },
        },
        "en": {
            "neutral": {
                "momentum": [
                    "{winner} fought back from behind to level the score.",
                    "What a comeback from {winner} — back on terms!",
                ],
                "play_by_play": [
                    "{winner} pulls it back level.",
                    "Comeback! {winner} levels it up!",
                ],
            },
            "short": {
                "play_by_play": ["Level again."],
                "momentum": ["Comeback! {winner} levels it up!"],
            },
        },
    },
    TTEventType.DOMINANT_LEAD.value: {
        "lt": {
            "neutral": {
                "momentum": [
                    "{winner} tvirtai pirmauja, {score}.",
                    "Didelis pranašumas — {winner}, {score}.",
                ],
                "play_by_play": [
                    "{winner} tvirtai pirmauja.",
                    "Pranašumas {winner}, {score}.",
                ],
            },
            "short": {
                "play_by_play": ["{winner} tvirtai pirmauja."],
            },
        },
        "en": {
            "neutral": {
                "momentum": [
                    "{winner} is in total control, {score}.",
                    "Dominant lead for {winner}, {score}.",
                ],
                "play_by_play": [
                    "{winner} is running away with this, {score}.",
                    "{winner} is firmly in front, {score}.",
                ],
            },
            "short": {
                "play_by_play": ["{winner} in complete control."],
            },
        },
    },
    TTEventType.MOMENTUM_SHIFT.value: {
        "lt": {
            "neutral": {
                "momentum": [
                    "Iniciatyva perima {winner}! {score}.",
                    "Momentumas keičiasi — dabar pirmauja {winner}, {score}.",
                ],
                "play_by_play": [
                    "Iniciatyva perima {winner}.",
                    "{winner} perima iniciatyvą, {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Momentumas — {winner}."],
            },
        },
        "en": {
            "neutral": {
                "momentum": [
                    "Momentum swings to {winner}! {score}.",
                    "The tide turns — {winner} takes charge, {score}.",
                ],
                "play_by_play": [
                    "Momentum shift — {winner} takes over.",
                    "{winner} grabs the initiative, {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Momentum — {winner}."],
            },
        },
    },
    TTEventType.TIMEOUT_OR_PAUSE.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Pertrauka.",
                    "Tarpinis poilsis.",
                ],
            },
            "short": {
                "play_by_play": ["Pertrauka."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Timeout.",
                    "Short break.",
                ],
            },
            "short": {
                "play_by_play": ["Timeout."],
            },
        },
    },
    TTEventType.MANUAL_SCORE_CHANGE.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Rezultatas atnaujintas. {score}.",
                    "Taškas pridėtas. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Atnaujinta: {score}."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Score updated. {score}.",
                    "Point added. {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Updated: {score}."],
            },
        },
    },
    TTEventType.VOICE_SCORE_CONFIRMED.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Patvirtinta. {score}.",
                    "Taškas pridėtas. Rezultatas {score}.",
                ],
            },
            "short": {
                "play_by_play": ["Patvirtinta."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Confirmed. {score}.",
                    "Score updated.",
                ],
            },
            "short": {
                "play_by_play": ["Confirmed."],
            },
        },
    },
    TTEventType.VOICE_SCORE_REJECTED.value: {
        "lt": {
            "neutral": {
                "play_by_play": [
                    "Komanda atmesta. Pakartokite.",
                    "Rezultatas nepakeistas. Pakartokite.",
                ],
            },
            "short": {
                "play_by_play": ["Komanda atmesta."],
            },
        },
        "en": {
            "neutral": {
                "play_by_play": [
                    "Command rejected. Please repeat.",
                    "Score unchanged. Try again.",
                ],
            },
            "short": {
                "play_by_play": ["Command rejected."],
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Selection with deduplication
# ---------------------------------------------------------------------------

_RECENT_WINDOW = 4


def get_templates(
    event_type: str,
    language: str,
    style: str,
    commentary_type: str = "play_by_play",
) -> List[str]:
    """Return templates from the TT bank, falling back to the legacy bank."""
    lang = normalize_language(language)
    nstyle = normalize_style(style)
    nct = normalize_commentary_type(commentary_type)

    # Try TT bank first.
    bank = _TEMPLATE_BANK.get(event_type, {}).get(lang, {}).get(nstyle, {})
    candidates = bank.get(nct)
    if candidates:
        return list(candidates)

    # If no exact commentary_type match, try play_by_play fallback.
    if nct != "play_by_play":
        candidates = bank.get("play_by_play")
        if candidates:
            return list(candidates)

    # Legacy fallback via category mapping.
    from tournament_platform.app.services.commentary.event_schema import (
        legacy_category_to_tt_event_type,
        tt_event_type_to_legacy_category,
    )
    try:
        legacy_cat = tt_event_type_to_legacy_category(TTEventType(event_type))
    except ValueError:
        legacy_cat = "point_won"

    # Map commentary_type to a legacy verbosity-ish hint when possible.
    legacy_verbosity = "normal" if nct in ("play_by_play", "tactical") else "normal"
    if nct == "summary":
        legacy_verbosity = "rich"
    if nct == "momentum":
        legacy_verbosity = "normal"

    try:
        _, text, _ = select_event_template(
            legacy_cat, lang, nstyle, legacy_verbosity, variables={}, recent_store=None
        )
        if text:
            return [text]
    except Exception:
        pass

    return []


def select_template_with_dedup(
    language: str,
    style: str,
    category: str,
    commentary_type: str,
    variables: Optional[Dict[str, Any]],
    recent_keys: Optional[List[str]] = None,
    rng: Optional[random.Random] = None,
) -> Tuple[Optional[str], str, List[str]]:
    """Select a template and render it, avoiding recent repeats.

    Returns ``(template, rendered_text, new_recent)``.
    """
    candidates = get_templates(category, language, style, commentary_type)
    if not candidates:
        return None, "", list(recent_keys or [])

    recent = list(recent_keys or [])
    available = [c for c in candidates if c not in recent]
    if not available:
        available = list(candidates)

    if rng is not None:
        chosen = rng.choice(available)
    else:
        chosen = available[0]

    text = render_template(chosen, variables)
    new_recent = (recent + [chosen])[-_RECENT_WINDOW:]
    return chosen, text, new_recent


# ---------------------------------------------------------------------------
# Match summary generator
# ---------------------------------------------------------------------------

def _classify_game_label(score_a: int, score_b: int, points_to_win: int = 11) -> str:
    diff = abs(score_a - score_b)
    if diff >= 6:
        return "dominant"
    if diff <= 2 and max(score_a, score_b) >= points_to_win - 1:
        return "close"
    return "normal"


def generate_match_summary(
    match_context: "MatchContext",  # noqa: F821
    language: str = "lt",
    style: str = "announcer",
) -> str:
    """Generate a local prose match summary from a completed ``MatchContext``."""
    lang = normalize_language(language)
    nstyle = normalize_style(style)

    sets_a = match_context.games_won_a
    sets_b = match_context.games_won_b
    winner = match_context.player_a if sets_a > sets_b else match_context.player_b
    loser = match_context.player_b if sets_a > sets_b else match_context.player_a

    if lang == "lt":
        score_sep = "–"
        sets_sep = " : "
        game_label = "Geimas"
    else:
        score_sep = "-"
        sets_sep = " to "
        game_label = "Game"

    match_score = f"{sets_a}{sets_sep}{sets_b}"

    games_list = match_context.completed_games or []
    games_str = ", ".join(games_list) if games_list else match_score

    parts: List[str] = []
    parts.append(f"{winner} {('laimėjo' if lang == 'lt' else 'wins')} {match_score}.")
    parts.append(f"{game_label}s: {games_str}.")

    if games_list:
        labels = []
        for g in games_list:
            try:
                a_str, b_str = g.split(score_sep)
                a, b = int(a_str), int(b_str)
            except (ValueError, AttributeError):
                labels.append("")
                continue
            lbl = _classify_game_label(a, b, match_context.points_to_win)
            if lang == "lt":
                if lbl == "dominant":
                    labels.append(f"{a}:{b} — tvirta pergalė")
                elif lbl == "close":
                    labels.append(f"{a}:{b} — arti")
                else:
                    labels.append(f"{a}:{b}")
            else:
                if lbl == "dominant":
                    labels.append(f"{a}-{b} — dominant")
                elif lbl == "close":
                    labels.append(f"{a}-{b} — close")
                else:
                    labels.append(f"{a}-{b}")

        if lang == "lt":
            summary = "Geimai: " + "; ".join(l for l in labels if l) + "."
        else:
            summary = "Games: " + "; ".join(l for l in labels if l) + "."
        parts.append(summary)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_template_bank() -> List[str]:
    problems: List[str] = []
    for event_type, lang_map in _TEMPLATE_BANK.items():
        for lang, style_map in lang_map.items():
            if lang != "lt":
                continue
            for style, ct_map in style_map.items():
                for commentary_type, templates in ct_map.items():
                    for tmpl in templates:
                        if looks_english_in_lithuanian(tmpl):
                            problems.append(f"lt/{event_type}/{style}/{commentary_type}: {tmpl}")
    return problems


_BANK_PROBLEMS = validate_template_bank()
if _BANK_PROBLEMS:  # pragma: no cover - defensive
    logger.warning(
        "TT template bank contains English fragments in Lithuanian templates: %s",
        _BANK_PROBLEMS,
    )
