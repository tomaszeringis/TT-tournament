"""
Tests for app/utils.py cache invalidation helper.
"""

import pytest
from unittest.mock import patch, MagicMock

from tournament_platform.app.utils import invalidate_tournament_cache


def test_invalidate_tournament_cache_clears_streamlit_cache():
    with patch("tournament_platform.app.utils.st") as mock_st:
        invalidate_tournament_cache(tournament_id=1)
        mock_st.cache_data.clear.assert_called_once()
