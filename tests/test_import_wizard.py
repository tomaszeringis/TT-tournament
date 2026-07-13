"""
Tests for import wizard component.
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.app.components.import_wizard import render_import_wizard, WIZARD_STEPS


def test_render_import_wizard_initializes_state():
    with patch("tournament_platform.app.components.import_wizard.st") as mock_st:
        mock_st.session_state = {}
        mock_st.button.side_effect = [False, False]
        mock_st.file_uploader.return_value = None
        mock_st.selectbox.return_value = "players"
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]

        render_import_wizard()
        assert mock_st.session_state.get("import_wizard_step") == 1


def test_render_import_wizard_steps():
    with patch("tournament_platform.app.components.import_wizard.st") as mock_st:
        mock_st.session_state = {
            "import_wizard_step": 2,
            "import_df": None,
            "import_column_mapping": {},
            "import_entity_type": "players",
        }
        mock_st.button.side_effect = [False, False]
        mock_st.selectbox.return_value = "players"
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_st.warning = MagicMock()

        render_import_wizard()
        mock_st.warning.assert_called_once()
