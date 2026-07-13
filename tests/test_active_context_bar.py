"""
Tests for active context bar component.
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.app.components.active_context_bar import render_active_context_bar


def test_render_active_context_bar_returns_tournament_id():
    with patch("tournament_platform.app.components.active_context_bar._load_tournaments") as mock_load:
        mock_load.return_value = [
            {"id": 1, "name": "Tournament A", "tournament_type": "knockout"},
            {"id": 2, "name": "Tournament B", "tournament_type": "round_robin"},
        ]
        with patch("tournament_platform.app.components.active_context_bar.get_tournament_health") as mock_health:
            mock_health.return_value = {
                "issues": [],
                "match_counts": {"active": 1},
            }
            with patch("tournament_platform.app.components.active_context_bar.st") as mock_st:
                mock_st.session_state = {}
                mock_st.sidebar = MagicMock()
                mock_st.sidebar.selectbox.return_value = "Tournament A"
                mock_st.sidebar.caption = MagicMock()
                mock_st.sidebar.markdown = MagicMock()

                result = render_active_context_bar()
                assert result == 1
                assert mock_st.session_state.get("active_tournament_id") == 1


def test_render_active_context_bar_initializes_session_state():
    with patch("tournament_platform.app.components.active_context_bar._load_tournaments") as mock_load:
        mock_load.return_value = [
            {"id": 5, "name": "Only One", "tournament_type": "knockout"},
        ]
        with patch("tournament_platform.app.components.active_context_bar.get_tournament_health") as mock_health:
            mock_health.return_value = {"issues": [], "match_counts": {"active": 0}}
            with patch("tournament_platform.app.components.active_context_bar.st") as mock_st:
                mock_st.session_state = {}
                mock_st.sidebar = MagicMock()
                mock_st.sidebar.selectbox.return_value = "Only One"
                mock_st.sidebar.caption = MagicMock()
                mock_st.sidebar.markdown = MagicMock()

                result = render_active_context_bar()
                assert result == 5
                assert mock_st.session_state.get("active_tournament_id") == 5
