"""
Tests for the tour framework.

Verifies the TOUR_CONTENT registry, step schema, session-state key naming,
and public API callables.
"""

import pytest

import streamlit as st

from tournament_platform.app.components.tour import (
    TOUR_CONTENT,
    _get_tour_state_keys,
    is_tour_completed,
    render_tour,
    render_tour_dialog,
    render_tour_expander,
    reset_tour,
)

EXPECTED_TOUR_KEYS = {
    "home",
    "tournament",
    "voice_scorekeeper",
    "ai_assistant",
    "admin",
    "dataset_catalog",
    "coaching_lab",
    "experiment_dashboard",
    "public_board",
    "schedule_board",
    "video_scorekeeper",
}


def test_tour_content_has_all_keys():
    assert set(TOUR_CONTENT.keys()) == EXPECTED_TOUR_KEYS


def test_tour_steps_have_required_fields():
    for tour_key, content in TOUR_CONTENT.items():
        assert "title" in content, f"Missing title in {tour_key}"
        assert "intro" in content, f"Missing intro in {tour_key}"
        assert "steps" in content, f"Missing steps in {tour_key}"
        assert isinstance(content["steps"], list)
        assert len(content["steps"]) > 0
        for step in content["steps"]:
            assert "title" in step, f"Missing step title in {tour_key}"
            assert "icon" in step, f"Missing step icon in {tour_key}"
            assert "content" in step, f"Missing step content in {tour_key}"
            assert isinstance(step.get("danger", False), bool)
            assert isinstance(step.get("example", ""), str)


def test_state_keys_use_gs_tour_prefix():
    for key in EXPECTED_TOUR_KEYS:
        show_key, step_key, done_key = _get_tour_state_keys(key)
        assert show_key.startswith("gs_tour_"), f"show key missing prefix: {show_key}"
        assert step_key.startswith("gs_tour_"), f"step key missing prefix: {step_key}"
        assert done_key.startswith("gs_tour_"), f"done key missing prefix: {done_key}"
        assert show_key == f"gs_tour_{key}_show"
        assert step_key == f"gs_tour_{key}_step"
        assert done_key == f"gs_tour_{key}_done"


def test_render_tour_is_callable():
    assert callable(render_tour)


def test_render_tour_expander_is_callable():
    assert callable(render_tour_expander)


def test_render_tour_dialog_is_callable():
    assert callable(render_tour_dialog)


def test_is_tour_completed_defaults_false():
    for key in EXPECTED_TOUR_KEYS:
        reset_tour(key)
        assert is_tour_completed(key) is False


def test_reset_tour_clears_completed():
    for key in EXPECTED_TOUR_KEYS:
        reset_tour(key)
        st_key = _get_tour_state_keys(key)[0]
        st.session_state[st_key] = True
        st.session_state[_get_tour_state_keys(key)[2]] = True
        reset_tour(key)
        assert is_tour_completed(key) is False
        assert st.session_state.get(_get_tour_state_keys(key)[0]) is False
        assert st.session_state.get(_get_tour_state_keys(key)[1]) == 1
