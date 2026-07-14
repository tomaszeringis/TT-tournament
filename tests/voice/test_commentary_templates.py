"""
Tests for the canonical commentary phrase-bank module.

These validate the requirements from the Voice Scorekeeper commentary
redesign: natural templates, language purity (no English in Lithuanian),
style/verbosity support, safe rendering, and repetition avoidance.
"""

import random

import pytest

from tournament_platform.services import commentary_templates as ct


# ---------------------------------------------------------------------------
# 1. English point template renders without missing variables
# ---------------------------------------------------------------------------

def test_en_point_renders_without_missing_vars():
    v = {"winner": "Tomas Z", "score": "7-5"}
    chosen, text, _ = ct.select_template("en", "point_won", "neutral", "normal", v)
    assert chosen is not None
    assert "Tomas Z" in text
    assert "7-5" in text
    assert "{" not in text  # no leftover placeholder


# ---------------------------------------------------------------------------
# 2. Lithuanian point template renders without English filler
# ---------------------------------------------------------------------------

def test_lt_point_has_no_english_filler():
    v = {"winner": "Tomas Z", "score": "7-5"}
    chosen, text, _ = ct.select_template("lt", "point_won", "neutral", "normal", v)
    assert "Tomas Z" in text
    assert ct.looks_english_in_lithuanian(text, ("Tomas Z",)) is False
    # common English connectors must not appear
    for frag in (" and ", " now ", " score ", " point "):
        assert frag not in text.lower(), text


# ---------------------------------------------------------------------------
# 3. Deuce template renders correctly (both languages)
# ---------------------------------------------------------------------------

def test_deuce_renders():
    en = ct.render_template(ct.TEMPLATES["en"]["deuce"]["neutral"]["normal"][0], {"score": "10-10"})
    assert "Deuce" in en
    lt = ct.render_template(ct.TEMPLATES["lt"]["deuce"]["neutral"]["normal"][0], {})
    assert lt in ("Lygiosios.", "Rezultatas lygus.", "Lygiųjų būsena.")


# ---------------------------------------------------------------------------
# 4. Advantage template renders correctly
# ---------------------------------------------------------------------------

def test_advantage_renders():
    en = ct.render_template(ct.TEMPLATES["en"]["advantage"]["neutral"]["normal"][0], {"winner": "Juozas"})
    assert "Advantage Juozas" in en
    lt = ct.render_template(ct.TEMPLATES["lt"]["advantage"]["neutral"]["normal"][0], {"winner": "Juozas"})
    assert "Pranašumas Juozas" in lt


# ---------------------------------------------------------------------------
# 5. Game point template uses correct player
# ---------------------------------------------------------------------------

def test_game_point_uses_correct_player():
    en = ct.render_template(ct.TEMPLATES["en"]["game_point"]["neutral"]["normal"][0], {"winner": "Juozas", "score": "10-8"})
    assert "Juozas" in en
    lt = ct.render_template(ct.TEMPLATES["lt"]["game_point"]["neutral"]["normal"][0], {"winner": "Juozas"})
    assert "Juozas" in lt


# ---------------------------------------------------------------------------
# 6. Match point template uses correct player
# ---------------------------------------------------------------------------

def test_match_point_uses_correct_player():
    en = ct.render_template(ct.TEMPLATES["en"]["match_point"]["neutral"]["normal"][0], {"winner": "Juozas"})
    assert "Juozas" in en
    lt = ct.render_template(ct.TEMPLATES["lt"]["match_point"]["neutral"]["normal"][0], {"winner": "Juozas"})
    assert "Juozas" in lt


# ---------------------------------------------------------------------------
# 7. Game won template includes winner and game score
# ---------------------------------------------------------------------------

def test_game_won_includes_winner_and_score():
    en = ct.render_template(
        ct.TEMPLATES["en"]["game_won"]["neutral"]["normal"][0],
        {"winner": "Tomas", "game_score": "11-6", "game_number": 1},
    )
    assert "Tomas" in en and "11-6" in en
    lt = ct.render_template(
        ct.TEMPLATES["lt"]["game_won"]["neutral"]["normal"][0],
        {"winner": "Tomas", "game_score": "11-6", "game_number": "1-ą"},
    )
    assert "Tomas" in lt and "11-6" in lt


# ---------------------------------------------------------------------------
# 8. Match won template includes winner
# ---------------------------------------------------------------------------

def test_match_won_includes_winner():
    en = ct.render_template(
        ct.TEMPLATES["en"]["match_won"]["neutral"]["normal"][0],
        {"winner": "Juozas", "sets_a": 3, "sets_b": 1},
    )
    assert "Juozas" in en
    lt = ct.render_template(
        ct.TEMPLATES["lt"]["match_won"]["neutral"]["normal"][0],
        {"winner": "Juozas", "match_score": "3 : 1"},
    )
    assert "Juozas" in lt


# ---------------------------------------------------------------------------
# 9. Voice command accepted is short
# ---------------------------------------------------------------------------

def test_voice_command_accepted_is_short():
    chosen, text, _ = ct.select_template("en", "voice_command_accepted", "neutral", "normal", {"winner": "Tomas", "score": "5-3"})
    assert len(text.split()) <= 6
    assert "Confirmed" in text or "Accepted" in text or "updated" in text.lower()


# ---------------------------------------------------------------------------
# 10. Voice command rejected does not update score
# ---------------------------------------------------------------------------

def test_voice_command_rejected_does_not_update_score():
    chosen, text, _ = ct.select_template("en", "voice_command_rejected", "neutral", "normal", {})
    assert "not" in text.lower() or "unchanged" in text.lower() or "repeat" in text.lower()
    lt = ct.render_template(ct.TEMPLATES["lt"]["voice_command_rejected"]["neutral"]["normal"][0], {})
    assert "nepakeistas" in lt.lower() or "pakartokite" in lt.lower()


# ---------------------------------------------------------------------------
# 11. Minimal style produces short output
# ---------------------------------------------------------------------------

def test_minimal_style_short_output():
    chosen, text, _ = ct.select_template("en", "point_won", "minimal", "minimal", {"winner": "Tomas", "score": "1-0"})
    # Minimal verbosity suppresses normal points entirely.
    assert text == ""
    deuce = ct.select_template("en", "deuce", "minimal", "minimal", {"score": "10-10"})[1]
    assert deuce == "Deuce."


# ---------------------------------------------------------------------------
# 12. Announcer style is more expressive only for important events
# ---------------------------------------------------------------------------

def test_announcer_more_expressive_for_important_events():
    # Important event (game point) should carry energetic phrasing.
    gp = ct.select_template("en", "game_point", "announcer", "normal", {"winner": "Tomas", "score": "10-8"})[1]
    assert "Big point" in gp or "!" in gp
    # Normal point stays short and calm.
    pt = ct.select_template("en", "point_won", "announcer", "normal", {"winner": "Tomas", "score": "1-0"})[1]
    assert "!" not in pt
    assert len(pt.split()) <= 6


# ---------------------------------------------------------------------------
# 13. Lithuanian templates contain no English connector words
# ---------------------------------------------------------------------------

def test_lt_templates_have_no_english_connectors():
    problems = ct.validate_lithuanian_templates()
    assert problems == [], f"Lithuanian templates leaked English: {problems}"


# ---------------------------------------------------------------------------
# 14. Repetition avoidance selects different templates over repeated calls
# ---------------------------------------------------------------------------

def test_repetition_avoidance_rotates_templates():
    recent = []
    seen = set()
    v = {"winner": "Tomas", "score": "3-1"}
    for _ in range(4):
        chosen, text, recent = ct.select_template("en", "point_won", "neutral", "normal", v, recent_keys=recent)
        seen.add(chosen)
    # With >=2 candidates, repeated calls should surface more than one.
    assert len(seen) >= 2


def test_repetition_avoidance_deterministic_when_exhausted():
    # When all candidates were recently used, it deterministically reuses one
    # (no crash, always returns text).
    all_candidates = ct.get_template_candidates("en", "point_won", "neutral", "normal")
    recent = list(all_candidates)
    chosen, text, _ = ct.select_template("en", "point_won", "neutral", "normal", {"winner": "Tomas", "score": "1-0"}, recent_keys=recent)
    assert text


# ---------------------------------------------------------------------------
# 15. Existing commentary tests still pass (regression smoke test)
# ---------------------------------------------------------------------------

def test_event_category_mapping():
    assert ct.category_for_event("point_scored") == "point_won"
    assert ct.category_for_event("set_win") == "game_won"
    assert ct.category_for_event("match_win") == "match_won"
    assert ct.category_for_event("error_or_uncertain_command") == "voice_command_rejected"


def test_normalization_handles_enum_members():
    from tournament_platform.services.commentary_service import CommentaryVerbosity

    assert ct.normalize_verbosity(CommentaryVerbosity.MINIMAL) == "minimal"
    assert ct.normalize_verbosity(CommentaryVerbosity.STANDARD) == "normal"
    assert ct.normalize_verbosity(CommentaryVerbosity.EXPRESSIVE) == "rich"
    assert ct.normalize_verbosity(CommentaryVerbosity.SILENT) == "silent"


def test_safe_rendering_never_raises():
    # Missing variables fall back to empty rather than raising.
    text = ct.render_template("Score {score} by {missing}", {"score": "5"})
    assert "5" in text
    assert "{" not in text
