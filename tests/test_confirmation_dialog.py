"""
Tests for confirmation dialog component.
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.app.components.confirmation_dialog import ConfirmationDialog


def test_confirmation_dialog_shows_warning_when_pending():
    dialog = ConfirmationDialog(key_prefix="test_dialog")
    with patch("tournament_platform.app.components.confirmation_dialog.st") as mock_st:
        mock_st.session_state = {"test_dialog_pending": {"label": "Delete match", "description": "irreversible"}}
        mock_st.button.return_value = False
        mock_st.warning = MagicMock()
        mock_st.caption = MagicMock()
        mock_st.columns.return_value = [MagicMock(), MagicMock()]

        result = dialog.confirm(
            action_label="Delete match",
            description="This cannot be undone",
            on_confirm=lambda: None,
        )
        assert result is False
        mock_st.warning.assert_called_once()
