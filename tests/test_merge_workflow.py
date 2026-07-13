"""
Tests for merge workflow component.
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.app.components.merge_workflow import render_merge_workflow


def test_render_merge_workflow_shows_no_candidates():
    with patch("tournament_platform.app.components.merge_workflow.st") as mock_st:
        mock_st.session_state = {}
        mock_st.button.return_value = False
        mock_st.info = MagicMock()

        render_merge_workflow()
        mock_st.info.assert_called_once()
