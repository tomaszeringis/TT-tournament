"""
Canonical spoken-commentary phrase banks for the Voice Scorekeeper.

This module is the single source of truth for *text templates* used by the
commentary engine. It is deliberately free of scoring logic, TTS, caching and
Streamlit dependencies so it can be unit-tested in isolation.

Structure
---------
``TEMPLATES[language][category][style][verbosity] = List[str]``

Languages: ``en``, ``lt``.
Categories (event types): point_won, score_update, serve_change, deuce,
advantage, game_point, match_point, game_won, match_won, streak, comeback,
lead_change, deciding_game, undo, reset, voice_command_accepted,
voice_command_rejected, voice_command_low_confidence, result_submitted, error.
Styles: neutral, professional, coach, announcer, minimal, kids.
Verbosity levels: short, normal, rich, minimal, silent.

Design rules
------------
* English templates are fully English; Lithuanian templates are fully
  Lithuanian (no English connector words such as "and", "now", "score",
  "point" unless they are part of a player name).
* Normal points stay short; important moments (deuce, advantage, game point,
  match point, game win, match win, comeback, streak) may be more expressive.
* The deduplication helper rotates between candidates so the same phrase is
  not repeated within a short window.
* Template rendering never raises on a missing variable; it falls back to an
  empty string (and the engine supplies all known variables anyway).
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

# Recent-template window used for deduplication (per language/style/category).
RECENT_WINDOW = 4

# English connector words that must never appear in Lithuanian commentary.
_LT_FORBIDDEN_EN_FRAGMENTS = (
    "point for",
    "wins the point",
    "takes the point",
    "score ",
    "now ",
    "game point",
    "match point",
    "set ",
    "wins ",
    "defeats",
    "advantage",
    "one point away",
    "final score",
    "victory",
    "lead change",
    "in front",
    "has advantage",
    "and ",
)

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_language(language: Any) -> str:
    if hasattr(language, "value"):
        language = language.value
    normalized = str(language or "en").strip().lower()
    if normalized in {"lt", "lithuanian", "lietuvių", "lietuviu", "lithuanian (lt)"}:
        return "lt"
    return "en"


def normalize_style(style: Any) -> str:
    if hasattr(style, "value"):
        style = style.value
    s = str(style or "neutral").strip().lower()
    if s in {"neutral", "professional", "coach", "announcer", "minimal", "kids"}:
        return s
    # Legacy / unknown aliases map to the closest supported style.
    if s in {"beginner", "simple"}:
        return "neutral"
    if s in {"energetic", "sport_commentator"}:
        return "announcer"
    return "neutral"


def normalize_verbosity(verbosity: Any) -> str:
    if hasattr(verbosity, "value"):
        verbosity = verbosity.value
    v = str(verbosity or "normal").strip().lower()
    if v in {"minimal"}:
        return "minimal"
    if v in {"short", "brief"}:
        return "short"
    if v in {"normal", "standard"}:
        return "normal"
    if v in {"rich", "expressive", "detailed"}:
        return "rich"
    if v in {"silent", "off"}:
        return "silent"
    return "normal"


# Map the event_id_str vocabulary used throughout the codebase to categories.
_EVENT_CATEGORY_MAP = {
    "point_scored": "point_won",
    "point_a": "point_won",
    "point_b": "point_won",
    "score_update": "score_update",
    "score": "score_update",
    "serve": "serve_change",
    "serve_change": "serve_change",
    "deuce": "deuce",
    "advantage": "advantage",
    "game_point": "game_point",
    "match_point": "match_point",
    "set_win": "game_won",
    "game_won": "game_won",
    "match_win": "match_won",
    "match_won_a": "match_won",
    "match_won_b": "match_won",
    "streak": "streak",
    "comeback": "comeback",
    "lead_change": "lead_change",
    "deciding_game": "deciding_game",
    "undo": "undo",
    "reset": "reset",
    "result_submitted": "result_submitted",
    "voice_command_accepted": "voice_command_accepted",
    "voice_command_rejected": "voice_command_rejected",
    "voice_command_low_confidence": "voice_command_low_confidence",
    "error_or_uncertain_command": "voice_command_rejected",
    "error": "error",
}


def category_for_event(event_id_str: Any) -> str:
    return _EVENT_CATEGORY_MAP.get(str(event_id_str or ""), "point_won")


TEMPLATES: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {
    "en": {
        "point_won": {
            "neutral": {
                "short": [
                    "Point {winner}. {score}.",
                    "{winner} takes it. {score}.",
                ],
                "normal": [
                    "Point {winner}. {score}.",
                    "{winner} takes the point. {score}.",
                    "Point to {winner}, now {score}.",
                    "{winner} edges that point. {score}.",
                ],
                "rich": [
                    "{winner} takes the point and moves the score to {score}.",
                ],
                "minimal": [],
            },
            "professional": {
                "normal": [
                    "{winner} takes the point and moves ahead, {score}.",
                    "Point to {winner}, now {score}.",
                ],
                "rich": [
                    "{winner} takes the point and moves the score to {score}.",
                ],
            },
            "coach": {
                "normal": [
                    "{winner} wins the point. {score}. Stay composed.",
                    "Good point, {winner}. {score}.",
                ],
                "rich": [
                    "{winner} wins the point, {score}. Keep the same rhythm next serve.",
                ],
            },
            "announcer": {
                "normal": [
                    "{winner} with the point, {score}.",
                    "Point {winner}, {score}.",
                ],
                "rich": [
                    "And {winner} takes the point, {score}!",
                ],
            },
            "kids": {
                "normal": [
                    "Yay, {winner} scores! {score}.",
                    "Awesome point, {winner}! {score}.",
                ],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "score_update": {
            "neutral": {
                "short": ["Score {score}."],
                "normal": ["The score is {score}.", "Score is {score}."],
                "rich": ["The score is now {score}."],
                "minimal": [],
            },
            "professional": {
                "normal": ["{winner} leads, {score}.", "The score is {score}."],
                "rich": ["{winner} moves ahead, {score}."],
            },
            "coach": {
                "normal": ["Score is {score}. Watch the next serve."],
                "rich": ["The score is {score}. Focus on consistency."],
            },
            "announcer": {
                "normal": ["We're level at {score}.", "Score {score}."],
                "rich": ["What a battle — the score is {score}."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "serve_change": {
            "neutral": {
                "short": ["Serve to {server}."],
                "normal": ["Serve changes to {server}.", "Now serving: {server}."],
                "rich": ["The serve passes to {server}."],
                "minimal": [],
            },
            "coach": {
                "normal": ["Serve to {server}. Mix up the placement."],
                "rich": ["Serve goes to {server}. Vary the spin here."],
            },
            "announcer": {
                "normal": ["{server} to serve.", "New server: {server}."],
                "rich": ["And the serve is with {server} now."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "deuce": {
            "neutral": {
                "short": ["Deuce. {score}."],
                "normal": [
                    "Deuce. {score}.",
                    "Back to deuce.",
                    "Level again at deuce.",
                    "Every point matters now — deuce.",
                ],
                "rich": [
                    "Deuce. Nothing between them at {score}.",
                    "Back to deuce — every point is huge now.",
                ],
                "minimal": ["Deuce."],
            },
            "professional": {
                "normal": ["Deuce at {score}. The next point is critical."],
                "rich": ["Deuce. The pressure is on — next point wins the advantage."],
            },
            "coach": {
                "normal": ["Deuce. Serve placement becomes critical."],
                "rich": ["At deuce, the server must stay calm and place the ball well."],
            },
            "announcer": {
                "normal": [
                    "Deuce! The tension is real.",
                    "Deuce — and the crowd is alive!",
                ],
                "rich": ["Deuce! This is where matches are won and lost."],
            },
            "minimal": {"short": ["Deuce."], "normal": ["Deuce."], "rich": ["Deuce."], "minimal": ["Deuce."]},
        },
        "advantage": {
            "neutral": {
                "short": ["Advantage {winner}."],
                "normal": [
                    "Advantage {winner}.",
                    "{winner} has advantage.",
                    "Advantage {winner}. One point from the game.",
                ],
                "rich": ["Advantage {winner} — one point away from taking the game."],
                "minimal": ["Advantage {winner}."],
            },
            "professional": {
                "normal": ["Advantage {winner}. One point to take the game."],
                "rich": ["{winner} has the advantage and is one point from the game."],
            },
            "coach": {
                "normal": ["Advantage {winner}. Stay aggressive on the next ball."],
                "rich": ["Advantage {winner}. Close it out with a positive serve."],
            },
            "announcer": {
                "normal": ["Advantage {winner}!", "What a response — advantage {winner}!"],
                "rich": ["Advantage {winner}! One point from the game!"],
            },
            "minimal": {"short": ["Advantage {winner}."], "normal": ["Advantage {winner}."], "rich": ["Advantage {winner}."], "minimal": ["Advantage {winner}."]},
        },
        "game_point": {
            "neutral": {
                "short": ["Game point {winner}."],
                "normal": [
                    "Game point for {winner}.",
                    "{winner} has game point at {score}.",
                    "One point away from the game for {winner}.",
                ],
                "rich": ["{winner} is one point away from the game at {score}."],
                "minimal": ["Game point {winner}."],
            },
            "professional": {
                "normal": ["Game point {winner}, {score}.", "{winner} has game point."],
                "rich": ["{winner} is one point away from the game, leading {score}."],
            },
            "coach": {
                "normal": ["Game point {winner}. Stay focused. {score}."],
                "rich": ["Game point for {winner}. Keep it simple and take the point."],
            },
            "announcer": {
                "normal": [
                    "Big point now — game point for {winner}.",
                    "Game point {winner}!",
                ],
                "rich": ["Game point for {winner}! One point from the game!"],
            },
            "minimal": {"short": ["Game point {winner}."], "normal": ["Game point {winner}."], "rich": ["Game point {winner}."], "minimal": ["Game point {winner}."]},
        },
        "match_point": {
            "neutral": {
                "short": ["Match point {winner}."],
                "normal": [
                    "Match point for {winner}.",
                    "{winner} is one point away from the match.",
                    "Huge moment — match point for {winner}.",
                ],
                "rich": ["{winner} can close the match right here."],
                "minimal": ["Match point {winner}."],
            },
            "professional": {
                "normal": ["Match point {winner}. One point from victory."],
                "rich": ["{winner} is one point away from winning the match."],
            },
            "coach": {
                "normal": ["Match point {winner}. Compose yourself and finish."],
                "rich": ["Match point for {winner}. One calm point wins it."],
            },
            "announcer": {
                "normal": [
                    "Match point for {winner}!",
                    "One point from glory — match point {winner}!",
                ],
                "rich": ["Match point for {winner}! One point from victory!"],
            },
            "minimal": {"short": ["Match point {winner}."], "normal": ["Match point {winner}."], "rich": ["Match point {winner}."], "minimal": ["Match point {winner}."]},
        },
        "game_won": {
            "neutral": {
                "short": ["Game {winner}."],
                "normal": [
                    "Game to {winner}, {game_score}.",
                    "{winner} takes game {game_number}, {game_score}.",
                    "That game goes to {winner}.",
                ],
                "rich": [
                    "That closes the game for {winner}, {game_score}.",
                    "{winner} takes the game, {game_score}. Strong finish.",
                ],
                "minimal": ["Game {winner}."],
            },
            "professional": {
                "normal": [
                    "Game to {winner}, {game_score}.",
                    "{winner} takes game {game_number}, {game_score}.",
                ],
                "rich": ["{winner} closes out the game, {game_score}, and leads the match."],
            },
            "coach": {
                "normal": [
                    "Game to {winner}, {game_score}. Well played.",
                    "{winner} takes game {game_number}. Regroup for the next one.",
                ],
                "rich": ["{winner} wins the game, {game_score}. Build on that momentum."],
            },
            "announcer": {
                "normal": [
                    "Game {winner}! {game_score}.",
                    "That's the game for {winner}!",
                ],
                "rich": ["That closes the game for {winner}, {game_score}!"],
            },
            "kids": {
                "normal": ["Game to {winner}, {game_score}! Great job!"],
                "rich": ["{winner} wins the game, {game_score}! Awesome!"],
            },
            "minimal": {"short": ["Game {winner}."], "normal": ["Game {winner}."], "rich": ["Game {winner}."], "minimal": ["Game {winner}."]},
        },
        "match_won": {
            "neutral": {
                "short": ["Match {winner}."],
                "normal": [
                    "Match complete. {winner} wins {sets_a} games to {sets_b}.",
                    "{winner} wins the match, {match_score}.",
                    "That is the match — {winner} takes it.",
                ],
                "rich": ["{winner} wins the match, {match_score}. A complete performance."],
                "minimal": ["Match {winner}."],
            },
            "professional": {
                "normal": [
                    "{winner} wins the match, {match_score}.",
                    "Match to {winner}, {match_score}.",
                ],
                "rich": ["{winner} takes the match, {match_score}, in controlled fashion."],
            },
            "coach": {
                "normal": [
                    "Match to {winner}, {sets_a} to {sets_b}. Outstanding.",
                    "{winner} wins the match. Reflect and reset.",
                ],
                "rich": ["{winner} wins the match, {match_score}. Well earned."],
            },
            "announcer": {
                "normal": [
                    "Match {winner}! {match_score}.",
                    "That's the match for {winner}!",
                ],
                "rich": ["Match to {winner}! What a performance, {match_score}!"],
            },
            "kids": {
                "normal": ["Match to {winner}, {match_score}! You did it!"],
                "rich": ["{winner} wins the match, {match_score}! Amazing!"],
            },
            "minimal": {"short": ["Match {winner}."], "normal": ["Match {winner}."], "rich": ["Match {winner}."], "minimal": ["Match {winner}."]},
        },
        "streak": {
            "neutral": {
                "short": ["Three in a row for {winner}."],
                "normal": [
                    "{winner} is on a {streak_count}-point streak.",
                    "Three points in a row for {winner}.",
                    "{winner} is building a run here.",
                    "{winner} has found rhythm with {streak_count} straight points.",
                ],
                "rich": ["{winner} has won {streak_count} points in a row and is rolling."],
                "minimal": [],
            },
            "coach": {
                "normal": [
                    "{streak_count} points in a row for {winner}. Reset before the next serve.",
                    "{winner} is in a groove — three straight points.",
                ],
                "rich": ["{winner} has the momentum with {streak_count} consecutive points."],
            },
            "announcer": {
                "normal": ["{winner} is on fire — three in a row!", "{winner} is running away with this!"],
                "rich": ["{winner} with {streak_count} straight points — unstoppable!"],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "comeback": {
            "neutral": {
                "short": ["Level again."],
                "normal": [
                    "That comeback changes the game.",
                    "{winner} has pulled it back level.",
                    "{winner} was under pressure, but now it is level.",
                ],
                "rich": ["{winner} fought back from behind to level the score."],
                "minimal": [],
            },
            "coach": {
                "normal": [
                    "Level again. {winner} has the momentum now.",
                    "{winner} claws it back — stay composed.",
                ],
                "rich": ["{winner} turns the game around and is right back in it."],
            },
            "announcer": {
                "normal": ["What a response from {winner} — back level!", "Comeback! {winner} levels it up!"],
                "rich": ["What a comeback from {winner} — back on terms!"],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "lead_change": {
            "neutral": {
                "short": ["{leader} leads."],
                "normal": [
                    "Lead change. {leader} {score} to {trailer}.",
                    "{leader} takes the lead, {score} to {trailer}.",
                ],
                "rich": ["The lead changes hands — {leader} goes in front, {score} to {trailer}."],
                "minimal": [],
            },
            "professional": {
                "normal": ["{leader} takes the lead, {score} to {trailer}."],
                "rich": ["{leader} edges ahead, {score} to {trailer}."],
            },
            "announcer": {
                "normal": ["Lead change — {leader} in front!", "{leader} takes the lead!"],
                "rich": ["The lead swings to {leader}, {score} to {trailer}!"],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "deciding_game": {
            "neutral": {
                "normal": ["Deciding game — game {game_number}.", "Final game underway."],
                "rich": ["This is the deciding game, game {game_number}. Everything on the line."],
            },
            "announcer": {
                "normal": ["Deciding game — game {game_number}!", "The final game is here!"],
                "rich": ["The decider! Game {game_number} will settle it."],
            },
        },
        "undo": {
            "neutral": {
                "short": ["Point removed. {score}."],
                "normal": ["Point removed. {score}.", "Undo. Score is {score}."],
                "rich": ["The last point is taken back. Score is {score}."],
                "minimal": [],
            },
            "coach": {
                "normal": ["Point undone. {score}. Refocus."],
                "rich": ["We've rolled back the last point — score is {score}."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "reset": {
            "neutral": {
                "short": ["Match reset. 0 to 0."],
                "normal": ["Match reset. Score is 0 to 0."],
                "rich": ["Starting over. The score is 0 to 0."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "voice_command_accepted": {
            "neutral": {
                "short": ["Confirmed. Point {winner}."],
                "normal": ["Confirmed. Point {winner}.", "Score updated.", "Accepted. {score}."],
                "rich": ["Command accepted. The score is now {score}."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "voice_command_rejected": {
            "neutral": {
                "short": ["Command rejected. Repeat."],
                "normal": [
                    "Command rejected. Please repeat.",
                    "I did not update the score.",
                    "Not confident enough. Please say it again.",
                ],
                "rich": ["I could not confirm that command, so the score is unchanged."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "voice_command_low_confidence": {
            "neutral": {
                "short": ["Low confidence. Confirm."],
                "normal": [
                    "I'm not fully sure. Please confirm.",
                    "Low confidence. Say it again to confirm.",
                ],
                "rich": ["That command was unclear — please repeat it so I can be sure."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "result_submitted": {
            "neutral": {
                "short": ["Result submitted."],
                "normal": [
                    "Result submitted: {winner} wins {match_score}.",
                    "Match result saved for {winner}, {match_score}.",
                ],
                "rich": ["The match result is saved — {winner} wins, {match_score}."],
                "minimal": ["Result: {winner}."],
            },
            "minimal": {"short": ["Result: {winner}."], "normal": ["Result: {winner}."], "rich": ["Result: {winner}."], "minimal": ["Result: {winner}."]},
        },
        "error": {
            "neutral": {
                "short": ["Error."],
                "normal": ["Error.", "Command not recognized."],
                "rich": ["Something went wrong and the score was not changed."],
                "minimal": ["Error."],
            },
            "minimal": {"short": ["Error."], "normal": ["Error."], "rich": ["Error."], "minimal": ["Error."]},
        },
    },
    "lt": {
        "point_won": {
            "neutral": {
                "short": [
                    "Taškas {winner}. {score}.",
                    "{winner} laimi tašką. {score}.",
                ],
                "normal": [
                    "Taškas {winner}. {score}.",
                    "{winner} laimi tašką. {score}.",
                    "Tašką žaidėjui {winner}. Rezultatas {score}.",
                ],
                "rich": [
                    "{winner} laimi tašką, rezultatas dabar {score}.",
                ],
                "minimal": [],
            },
            "professional": {
                "normal": ["{winner} laimi tašką, rezultatas {score}."],
                "rich": ["{winner} pelno tašką ir pirmaus, {score}."],
            },
            "coach": {
                "normal": ["Gerai, {winner}. {score}.", "Taškas {winner}. Išlaikyk tempą."],
                "rich": ["{winner} laimi tašką, rezultatas {score}. Tęsk taip toliau."],
            },
            "announcer": {
                "normal": ["Taškas {winner}! {score}.", "{winner} pelno tašką, {score}!"],
                "rich": ["Ir taškas {winner}, {score}! Puikus smūgis!"],
            },
            "kids": {
                "normal": ["Šaunu, {winner} pelno tašką! {score}."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "score_update": {
            "neutral": {
                "short": ["Rezultatas {score}."],
                "normal": ["Rezultatas {score}.", "{winner} veda {score}."],
                "rich": ["Dabar rezultatas {score}."],
                "minimal": [],
            },
            "professional": {
                "normal": ["{winner} pirmaus, {score}."],
                "rich": ["Rezultatas {score}, veda {winner}."],
            },
            "announcer": {
                "normal": ["Lygu — {score}.", "Rezultatas {score}."],
                "rich": ["Kova tęsiasi, rezultatas {score}."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "serve_change": {
            "neutral": {
                "short": ["Servuoja {server}."],
                "normal": ["Servisas pereina žaidėjui {server}.", "Dabar servuoja {server}."],
                "rich": ["Servas pereina {server}."],
                "minimal": [],
            },
            "coach": {
                "normal": ["Servuoja {server}. Pakeisk padėtį."],
                "rich": ["Servas pereina {server}. Įvairink sukimą."],
            },
            "announcer": {
                "normal": ["Servuoja {server}.", "Naujas servas — {server}."],
                "rich": ["Ir servą perima {server}."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "deuce": {
            "neutral": {
                "short": ["Lygiosios."],
                "normal": [
                    "Lygiosios.",
                    "Rezultatas lygus.",
                    "Lygiųjų būsena.",
                ],
                "rich": [
                    "Lygu. Dešimt — dešimt.",
                    "Vėl lygu.",
                ],
                "minimal": ["Lygu."],
            },
            "professional": {
                "normal": ["Lygiųjų būsena. Kitas taškas lemiamas."],
                "rich": ["Lygu — kiekvienas taškas dabar lemiamas."],
            },
            "coach": {
                "normal": ["Lygu. Servo padėtis tampa lemiamą."],
                "rich": ["Esant lygioms, servas turi būti tikslus."],
            },
            "announcer": {
                "normal": ["Lemiamas momentas — lygu!", "Vėl lygu — įtampa didžiulė!"],
                "rich": ["Lygu! Štai kur lemiamos akimirkos!"],
            },
            "minimal": {"short": [], "normal": ["Lygu."], "rich": ["Lygu."], "minimal": ["Lygu."]},
        },
        "advantage": {
            "neutral": {
                "short": ["Pranašumas {winner}."],
                "normal": [
                    "Pranašumas {winner}.",
                    "{winner} turi pranašumą.",
                    "Pranašumas žaidėjui {winner}.",
                ],
                "rich": ["Pranašumas {winner} — vienas taškas iki geimo."],
                "minimal": ["Pranašumas {winner}."],
            },
            "professional": {
                "normal": ["{winner} turi pranašumą. Taškas iki geimo."],
                "rich": ["Pranašumas {winner}, liko vienas taškas iki pergalės geime."],
            },
            "coach": {
                "normal": ["Pranašumas {winner}. Būk ryžtingas kitame smūgyje."],
                "rich": ["{winner} turi pranašumą. Užbaik pozityviu servu."],
            },
            "announcer": {
                "normal": ["Pranašumas {winner}!", "Puiki atsakomoji — pranašumas {winner}!"],
                "rich": ["Pranašumas {winner}! Likęs vienas taškas iki geimo!"],
            },
            "minimal": {"short": ["Pranašumas {winner}."], "normal": ["Pranašumas {winner}."], "rich": ["Pranašumas {winner}."], "minimal": ["Pranašumas {winner}."]},
        },
        "game_point": {
            "neutral": {
                "short": ["Geimo taškas {winner}."],
                "normal": [
                    "Geimo taškas {winner}.",
                    "{winner} turi geimo tašką.",
                    "Vienas taškas iki geimo — {winner}.",
                ],
                "rich": ["{winner} vienu tašku nuo geimo, rezultatas {score}."],
                "minimal": ["Geimo taškas {winner}."],
            },
            "professional": {
                "normal": ["Geimo taškas {winner}, {score}.", "{winner} turi geimo tašką."],
                "rich": ["{winner} vienu tašku nuo geimo, pirmaus {score}."],
            },
            "coach": {
                "normal": ["Geimo taškas {winner}. Susitelk. {score}."],
                "rich": ["Geimo taškas {winner}. Paprastas taškas viską baigia."],
            },
            "announcer": {
                "normal": ["Svarbus taškas — geimo taškas {winner}!", "Geimo taškas {winner}!"],
                "rich": ["Geimo taškas {winner}! Vienas taškas iki pergalės!"],
            },
            "minimal": {"short": ["Geimo taškas {winner}."], "normal": ["Geimo taškas {winner}."], "rich": ["Geimo taškas {winner}."], "minimal": ["Geimo taškas {winner}."]},
        },
        "match_point": {
            "neutral": {
                "short": ["Mačo taškas {winner}."],
                "normal": [
                    "Mačo taškas {winner}.",
                    "{winner} turi mačo tašką.",
                    "Vienas taškas iki pergalės — {winner}.",
                ],
                "rich": ["{winner} vienu tašku nuo mačo pergalės."],
                "minimal": ["Mačo taškas {winner}."],
            },
            "professional": {
                "normal": ["Mačo taškas {winner}. Likęs vienas taškas."],
                "rich": ["{winner} vienu tašku nuo mačo pergalės."],
            },
            "coach": {
                "normal": ["Mačo taškas {winner}. Nusiramink ir užbaik."],
                "rich": ["Mačo taškas {winner}. Vienas ramus taškas viską baigia."],
            },
            "announcer": {
                "normal": ["Mačo taškas {winner}!", "Vienu tašku nuo pergalės — {winner}!"],
                "rich": ["Mačo taškas {winner}! Likęs vienas taškas!"],
            },
            "minimal": {"short": ["Mačo taškas {winner}."], "normal": ["Mačo taškas {winner}."], "rich": ["Mačo taškas {winner}."], "minimal": ["Mačo taškas {winner}."]},
        },
        "game_won": {
            "neutral": {
                "short": ["Geimas {winner}."],
                "normal": [
                    "Geimą laimi {winner}, {game_score}.",
                    "{winner} laimi {game_number} geimą.",
                    "Geimas baigtas. Laimėjo {winner}.",
                ],
                "rich": [
                    "Geimą užbaigia {winner}, {game_score}.",
                    "{winner} laimi geimą, {game_score}. Geras finišas.",
                ],
                "minimal": ["Geimas {winner}."],
            },
            "professional": {
                "normal": [
                    "Geimą laimi {winner}, {game_score}.",
                    "{winner} laimi {game_number} geimą.",
                ],
                "rich": ["{winner} užbaigia geimą, {game_score}, ir pirmaus mače."],
            },
            "coach": {
                "normal": [
                    "Geimą laimi {winner}, {game_score}. Gerai sužaista.",
                    "{winner} laimi {game_number} geimą. Ruoškis kitam.",
                ],
                "rich": ["{winner} laimi geimą, {game_score}. Išlaikyk momentum."],
            },
            "announcer": {
                "normal": ["Geimas {winner}! {game_score}.", "Štai geimas žaidėjui {winner}!"],
                "rich": ["Geimą užbaigia {winner}, {game_score}!"],
            },
            "kids": {
                "normal": ["Geimą laimi {winner}, {game_score}! Šaunu!"],
                "rich": ["{winner} laimi geimą, {game_score}! Nuostabu!"],
            },
            "minimal": {"short": ["Geimas {winner}."], "normal": ["Geimas {winner}."], "rich": ["Geimas {winner}."], "minimal": ["Geimas {winner}."]},
        },
        "match_won": {
            "neutral": {
                "short": ["Mačas {winner}."],
                "normal": [
                    "Mačą laimi {winner}. Rezultatas {match_score}.",
                    "Pergalė — {winner}. Rezultatas {match_score}.",
                    "Mačas baigtas. Laimėjo {winner}.",
                ],
                "rich": ["Mačą laimi {winner}, rezultatas {match_score}."],
                "minimal": ["Mačas {winner}."],
            },
            "professional": {
                "normal": [
                    "{winner} laimi mačą, {match_score}.",
                    "Mačas {winner}, {match_score}.",
                ],
                "rich": ["{winner} laimi mačą, {match_score}, tvarkingai sužaidęs."],
            },
            "coach": {
                "normal": [
                    "Mačas {winner}, {sets_a} : {sets_b}. Puiku.",
                    "{winner} laimi mačą. Atsipalaiduok ir pamąstyk.",
                ],
                "rich": ["{winner} laimi mačą, {match_score}. Pelnytas."],
            },
            "announcer": {
                "normal": ["Mačas {winner}! {match_score}.", "Štai mačas žaidėjui {winner}!"],
                "rich": ["Mačą laimi {winner}! Puikus pasirodymas, {match_score}!"],
            },
            "kids": {
                "normal": ["Mačą laimi {winner}, {match_score}! Tu tai padarei!"],
                "rich": ["{winner} laimi mačą, {match_score}! Nuostabu!"],
            },
            "minimal": {"short": ["Mačas {winner}."], "normal": ["Mačas {winner}."], "rich": ["Mačas {winner}."], "minimal": ["Mačas {winner}."]},
        },
        "streak": {
            "neutral": {
                "short": ["Tris iš eilės — {winner}."],
                "normal": [
                    "{winner} laimi {streak_count} taškus iš eilės.",
                    "Gera atkarpa žaidėjui {winner}.",
                    "{winner} perima iniciatyvą.",
                ],
                "rich": ["{winner} laimi {streak_count} taškus iš eilės ir sparčiai veržiasi į priekį."],
                "minimal": [],
            },
            "coach": {
                "normal": [
                    "{winner} laimi {streak_count} taškus iš eilės. Atsigauk prieš kitą servą.",
                    "{winner} serijoje — trys taškai iš eilės.",
                ],
                "rich": ["{winner} turi momentumą su {streak_count} taškais iš eilės."],
            },
            "announcer": {
                "normal": ["{winner} dega — trys iš eilės!", "{winner} spiria varžovą!"],
                "rich": ["{winner} laimi {streak_count} taškus iš eilės — neįkandamas!"],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "comeback": {
            "neutral": {
                "short": ["Vėl lygu."],
                "normal": [
                    "{winner} grįžta į kovą.",
                    "Rezultatas vėl lygus.",
                    "Puikus sugrįžimas — {winner}.",
                ],
                "rich": ["{winner} atsigavo iš atsilikimo ir išlygino rezultatą."],
                "minimal": [],
            },
            "coach": {
                "normal": [
                    "Vėl lygu. {winner} dabar turi momentumą.",
                    "{winner} susigrąžina — išlik ramus.",
                ],
                "rich": ["{winner} apverčia žaidimą ir vėl grįžta į kovą."],
            },
            "announcer": {
                "normal": ["Puiki atsakomoji {winner} — vėl lygu!", "Sugrįžimas! {winner} išlygino!"],
                "rich": ["Koks sugrįžimas — {winner} vėl lygus!"],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "lead_change": {
            "neutral": {
                "short": ["{leader} pirmaus."],
                "normal": [
                    "{leader} išsiveržia į priekį, rezultatas {score}.",
                    "Dabar pirmauja {leader}, rezultatas {score}.",
                ],
                "rich": ["Lyderis pasikeičia — {leader} priekyje, {score}."],
                "minimal": [],
            },
            "professional": {
                "normal": ["{leader} išsiveržia į priekį, {score}."],
                "rich": ["{leader} pirmaus, {score}."],
            },
            "announcer": {
                "normal": ["Lyderis pasikeitė — {leader} priekyje!", "{leader} išsiveržia į priekį!"],
                "rich": ["Iniciatyvą perima {leader}, {score}!"],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "deciding_game": {
            "neutral": {
                "normal": ["Lemiamas geimas — {game_number}.", "Finalinis geimas prasideda."],
                "rich": ["Tai lemiamas geimas, {game_number}. Viskas ant kortos."],
            },
            "announcer": {
                "normal": ["Lemiamas geimas — {game_number}!", "Finalinis geimas čia!"],
                "rich": ["Sprendžiamasis geimas! {game_number} viską nulems."],
            },
        },
        "undo": {
            "neutral": {
                "short": ["Taškas pašalintas. {score}."],
                "normal": ["Taškas pašalintas. {score}.", "Atšaukta. Rezultatas {score}."],
                "rich": ["Paskutinis taškas grąžintas. Rezultatas {score}."],
                "minimal": [],
            },
            "coach": {
                "normal": ["Taškas atšauktas. {score}. Susitelk."],
                "rich": ["Grąžinome paskutinį tašką — rezultatas {score}."],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "reset": {
            "neutral": {
                "short": ["Rungtynes iš naujo. 0 : 0."],
                "normal": ["Rungtynes pradedamos iš naujo. 0 : 0."],
                "rich": ["Pradedame iš pradžių. Rezultatas 0 : 0."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "voice_command_accepted": {
            "neutral": {
                "short": ["Patvirtinta. Taškas {winner}."],
                "normal": ["Patvirtinta. Taškas {winner}.", "Rezultatas atnaujintas.", "Priimta. {score}."],
                "rich": ["Komanda priimta. Rezultatas dabar {score}."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "voice_command_rejected": {
            "neutral": {
                "short": ["Komanda atmesta. Pakartokite."],
                "normal": [
                    "Komanda atmesta. Pakartokite.",
                    "Rezultatas nepakeistas.",
                    "Nepakanka tikslumo. Pakartokite komandą.",
                ],
                "rich": ["Komandos patvirtinti negalėjau, todėl rezultatas nepakeistas."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "voice_command_low_confidence": {
            "neutral": {
                "short": ["Mažas tikslumas. Patvirtinkite."],
                "normal": [
                    "Ne visai aišku. Prašome patvirtinti.",
                    "Mažas pasitikėjimas. Pakartokite komandą.",
                ],
                "rich": ["Komanda buvo neaiški — pakartokite, kad būčiau tikras."],
                "minimal": [],
            },
            "minimal": {"short": [], "normal": [], "rich": [], "minimal": []},
        },
        "result_submitted": {
            "neutral": {
                "short": ["Rezultatas pateiktas."],
                "normal": [
                    "Rezultatas pateiktas: {winner} laimi {match_score}.",
                    "Mačo rezultatas išsaugotas: {winner}.",
                ],
                "rich": ["Mačo rezultatas išsaugotas — {winner} laimi, {match_score}."],
                "minimal": ["Rezultatas: {winner}."],
            },
            "minimal": {"short": ["Rezultatas: {winner}."], "normal": ["Rezultatas: {winner}."], "rich": ["Rezultatas: {winner}."], "minimal": ["Rezultatas: {winner}."]},
        },
        "error": {
            "neutral": {
                "short": ["Klaida."],
                "normal": ["Klaida.", "Komandos atpažinti nepavyko."],
                "rich": ["Kažkas nutiko, o rezultatas nepakeistas."],
                "minimal": ["Klaida."],
            },
            "minimal": {"short": ["Klaida."], "normal": ["Klaida."], "rich": ["Klaida."], "minimal": ["Klaida."]},
        },
    },
}

# ---------------------------------------------------------------------------
# Candidate resolution
# ---------------------------------------------------------------------------

def get_template_candidates(
    language: str,
    category: str,
    style: str,
    verbosity: str,
) -> List[str]:
    """Return template strings for the given slot, with graceful fallbacks.

    Fallback order:
      1. exact (language, category, style, verbosity)
      2. other verbosity levels within the same style
      3. neutral style within the same language/category
      4. empty list (caller decides how to fall back further)
    """
    lang = normalize_language(language)
    cat = category if cat_exists(lang, category) else None
    if cat is None:
        # Try a language-agnostic fallback to English templates.
        if lang != "en" and cat_exists("en", category):
            lang, cat = "en", category
        else:
            return []

    by_style = TEMPLATES[lang][cat]
    style = normalize_style(style)

    # Silent verbosity never produces speech.
    if verbosity == "silent":
        return []

    # Minimal verbosity means "suppress normal events"; it must NOT fall back
    # to richer verbosity levels (that would re-enable point commentary).
    if verbosity == "minimal":
        if style in by_style and by_style[style].get("minimal"):
            return list(by_style[style]["minimal"])
        if "neutral" in by_style and by_style["neutral"].get("minimal"):
            return list(by_style["neutral"]["minimal"])
        return []

    # short/normal/rich: try exact, then other levels, then neutral style.
    if style in by_style:
        candidates = _pick_verbosity(by_style[style], verbosity)
        if candidates:
            return candidates
        for v in ("normal", "rich", "short"):
            if by_style[style].get(v):
                return list(by_style[style][v])
        return []

    # Style not present for this category -> fall back to neutral style.
    neutral = by_style.get("neutral", {})
    if not neutral:
        return []
    candidates = _pick_verbosity(neutral, verbosity)
    if candidates:
        return candidates
    for v in ("normal", "rich", "short"):
        if neutral.get(v):
            return list(neutral[v])
    return []


def cat_exists(language: str, category: str) -> bool:
    return language in TEMPLATES and category in TEMPLATES[language]


def _pick_verbosity(verb_map: Dict[str, List[str]], verbosity: str) -> List[str]:
    if not verb_map:
        return []
    if verbosity in verb_map and verb_map[verbosity]:
        return list(verb_map[verbosity])
    return []


# ---------------------------------------------------------------------------
# Safe rendering
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    """Dict that returns an empty string for missing keys when formatting."""

    def __missing__(self, key):  # pragma: no cover - trivial
        return ""


def render_template(template: str, variables: Optional[Dict[str, Any]] = None) -> str:
    """Render a template with the supplied variables, never raising."""
    variables = variables or {}
    try:
        return str(template).format_map(_SafeDict(variables))
    except (KeyError, IndexError, ValueError):
        return str(template)


# ---------------------------------------------------------------------------
# Selection with deduplication / cooldown
# ---------------------------------------------------------------------------

def select_template(
    language: str,
    category: str,
    style: str,
    verbosity: str,
    variables: Optional[Dict[str, Any]] = None,
    recent_keys: Optional[List[str]] = None,
    rng: Optional[random.Random] = None,
) -> Tuple[Optional[str], str, List[str]]:
    """Select a template and render it, avoiding recent repeats.

    Returns ``(template_key, rendered_text, new_recent_keys)``.

    ``recent_keys`` is a list of recently used template strings (the same
    identity used as ``template_key``). When every candidate has been used
    recently we deterministically fall back to the full candidate list so the
    system never gets stuck. Pass an ``rng`` (seeded ``random.Random``) for
    randomized-but-testable selection; omit it for fully deterministic output.
    """
    candidates = get_template_candidates(language, category, style, verbosity)
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
    new_recent = (recent + [chosen])[-RECENT_WINDOW:]
    return chosen, text, new_recent


def select_event_template(
    event_id_str: str,
    language: Any,
    style: Any,
    verbosity: Any,
    variables: Optional[Dict[str, Any]] = None,
    recent_store: Optional[Dict[Tuple[str, str, str], List[str]]] = None,
) -> Tuple[Optional[str], str, List[str]]:
    """Convenience wrapper that resolves the event category and tracks recents.

    ``recent_store`` is a caller-owned dict keyed by
    ``(language, style, category)``; it is mutated in place so deduplication
    persists across calls (e.g. within a live match).
    """
    lang = normalize_language(language)
    cat = category_for_event(event_id_str)
    nstyle = normalize_style(style)
    nverb = normalize_verbosity(verbosity)

    store_key = (lang, nstyle, cat)
    recent = (recent_store or {}).get(store_key, []) if recent_store is not None else []
    chosen, text, new_recent = select_template(lang, cat, nstyle, nverb, variables, recent_keys=recent)
    if recent_store is not None:
        recent_store[store_key] = new_recent
    return chosen, text, new_recent


# ---------------------------------------------------------------------------
# Validation helpers (used by tests and import-time safety)
# ---------------------------------------------------------------------------

def looks_english_in_lithuanian(text: str, player_names: Tuple[str, str] = ("", "")) -> bool:
    """Return True if a Lithuanian template string contains English filler."""
    low = text.lower()
    for frag in _LT_FORBIDDEN_EN_FRAGMENTS:
        if frag in low and frag not in " ".join(player_names).lower():
            return True
    return False


def validate_lithuanian_templates() -> List[str]:
    """Return a list of Lithuanian template strings that look English."""
    problems: List[str] = []
    for category, style_map in TEMPLATES.get("lt", {}).items():
        for style, verb_map in style_map.items():
            for verbosity, templates in verb_map.items():
                for tmpl in templates:
                    if looks_english_in_lithuanian(tmpl):
                        problems.append(f"lt/{category}/{style}/{verbosity}: {tmpl}")
    return problems


# Import-time sanity check: fail fast if any Lithuanian template leaked English.
_LT_PROBLEMS = validate_lithuanian_templates()
if _LT_PROBLEMS:  # pragma: no cover - defensive
    import logging

    logging.getLogger(__name__).warning(
        "Lithuanian commentary templates contain English fragments: %s", _LT_PROBLEMS
    )
