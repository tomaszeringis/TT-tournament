"""
Tests for the centralized API client.

These tests use mocking to avoid making actual HTTP requests.
"""

import pytest
from unittest.mock import patch, MagicMock
import requests

from tournament_platform.app.api_client import ApiClient


class TestApiClient:
    """Test cases for the ApiClient class."""

    def test_init_default(self):
        """Test ApiClient initialization with default values."""
        client = ApiClient()
        assert client.base_url == "http://localhost:8000"
        assert client.timeout == 10

    def test_init_custom(self):
        """Test ApiClient initialization with custom values."""
        client = ApiClient(base_url="http://custom.api.com", timeout=30)
        assert client.base_url == "http://custom.api.com"
        assert client.timeout == 30

    def test_build_url(self):
        """Test URL building from endpoint path."""
        client = ApiClient()
        assert client._build_url("/health") == "http://localhost:8000/health"
        assert client._build_url("health") == "http://localhost:8000/health"
        assert client._build_url("/api/report") == "http://localhost:8000/api/report"

    def test_build_url_trailing_slash(self):
        """Test URL building handles trailing slashes correctly."""
        client = ApiClient(base_url="http://localhost:8000/")
        assert client._build_url("/health") == "http://localhost:8000/health"

    @patch("tournament_platform.app.api_client.requests.get")
    def test_health_success(self, mock_get):
        """Test health check with successful response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "healthy"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = ApiClient()
        result = client.health()

        assert result == {"status": "healthy"}
        mock_get.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.get")
    def test_health_connection_error(self, mock_get):
        """Test health check with connection error."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        client = ApiClient()
        result = client.health()

        assert result is None

    @patch("tournament_platform.app.api_client.requests.get")
    def test_health_timeout(self, mock_get):
        """Test health check with timeout."""
        mock_get.side_effect = requests.exceptions.Timeout()

        client = ApiClient()
        result = client.health()

        assert result is None

    @patch("tournament_platform.app.api_client.requests.post")
    def test_report_match_legacy_success(self, mock_post):
        """Test report_match_legacy with successful response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success", "match_id": 123}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.report_match_legacy(
            match_id=123,
            score="11-9, 11-8",
            winner="Alice",
        )

        assert result == {"status": "success", "match_id": 123}
        # Verify the correct payload format is sent
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {
            "match_id": 123,
            "score": "11-9, 11-8",
            "winner": "Alice",
        }
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_ask_rules_success(self, mock_post):
        """Test ask_rules with successful response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success", "answer": "Test answer"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.ask_rules("What are the rules?")

        assert result == {"status": "success", "answer": "Test answer"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_call_match(self, mock_post):
        """Test call_match method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.call_match(123, "Table 1")

        assert result == {"status": "success"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_start_match(self, mock_post):
        """Test start_match method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.start_match(123)

        assert result == {"status": "success"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_complete_match(self, mock_post):
        """Test complete_match method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.complete_match(123)

        assert result == {"status": "success"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_delay_match(self, mock_post):
        """Test delay_match method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.delay_match(123, 15)

        assert result == {"status": "success"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.patch")
    def test_reschedule_match(self, mock_patch):
        """Test reschedule_match method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_patch.return_value = mock_response

        client = ApiClient()
        result = client.reschedule_match(123, "2024-01-01T10:00:00", "Table 1")

        assert result == {"status": "success"}
        mock_patch.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_reset_call_match(self, mock_post):
        """Test reset_call_match method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.reset_call_match(123)

        assert result == {"status": "success"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.get")
    def test_get_success(self, mock_get):
        """Test generic GET method with successful response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = ApiClient()
        result = client.get("/api/test")

        assert result == {"data": "test"}
        mock_get.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.post")
    def test_post_success(self, mock_post):
        """Test generic POST method with successful response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        result = client.post("/api/test", json={"key": "value"})

        assert result == {"data": "test"}
        mock_post.assert_called_once()

    @patch("tournament_platform.app.api_client.requests.patch")
    def test_patch_success(self, mock_patch):
        """Test generic PATCH method with successful response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = MagicMock()
        mock_patch.return_value = mock_response

        client = ApiClient()
        result = client.patch("/api/test", json={"key": "value"})

        assert result == {"data": "test"}
        mock_patch.assert_called_once()


class TestOperatorConsoleApiFunctions:
    """Test cases for operator console API helper functions."""

    @patch("tournament_platform.app.api_client.requests.post")
    def test_call_match_function(self, mock_post):
        """Test call_match function in operator_console module."""
        from tournament_platform.app.pages.operator_console import call_match

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = call_match(123, "Table 1")
        assert result == {"status": "success"}

    @patch("tournament_platform.app.api_client.requests.post")
    def test_start_match_function(self, mock_post):
        """Test start_match function in operator_console module."""
        from tournament_platform.app.pages.operator_console import start_match

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = start_match(123)
        assert result == {"status": "success"}

    @patch("tournament_platform.app.api_client.requests.post")
    def test_complete_match_function(self, mock_post):
        """Test complete_match function in operator_console module."""
        from tournament_platform.app.pages.operator_console import complete_match

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = complete_match(123)
        assert result == {"status": "success"}

    @patch("tournament_platform.app.api_client.requests.post")
    def test_delay_match_function(self, mock_post):
        """Test delay_match function in operator_console module."""
        from tournament_platform.app.pages.operator_console import delay_match

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = delay_match(123, 15)
        assert result == {"status": "success"}

    @patch("tournament_platform.app.api_client.requests.patch")
    def test_reschedule_match_function(self, mock_patch):
        """Test reschedule_match function in operator_console module."""
        from tournament_platform.app.pages.operator_console import reschedule_match

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_patch.return_value = mock_response

        result = reschedule_match(123, "2024-01-01T10:00:00", "Table 1")
        assert result == {"status": "success"}

    @patch("tournament_platform.app.api_client.requests.post")
    def test_reset_call_match_function(self, mock_post):
        """Test reset_call_match function in operator_console module."""
        from tournament_platform.app.pages.operator_console import reset_call_match

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = reset_call_match(123)
        assert result == {"status": "success"}

    @patch("tournament_platform.app.api_client.requests.post")
    def test_api_error_returns_error_dict(self, mock_post):
        """Test that API errors return error dict with message."""
        from tournament_platform.app.pages.operator_console import call_match

        mock_post.side_effect = requests.exceptions.ConnectionError()

        result = call_match(123)
        assert result == {"status": "error", "message": "API request failed"}


class TestReportMatchLegacyStreamlitIntegration:
    """Test that report_match_legacy works with the current Streamlit score payload."""

    @patch("tournament_platform.app.api_client.requests.post")
    def test_report_match_legacy_streamlit_payload_format(self, mock_post):
        """
        Simulate the current Streamlit score payload through ApiClient.report_match_legacy().
        
        This test verifies that the method sends the correct payload format expected by /api/report.
        The Streamlit UI (voice_scorekeeper.py) uses this to report match results.
        """
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success", "match_id": 456}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ApiClient()
        
        # Simulate a match result from the Streamlit UI
        # The UI would have selected a match and entered score/winner
        result = client.report_match_legacy(
            match_id=456,
            score="11-9, 11-8, 11-7",
            winner="Alice",
        )

        assert result == {"status": "success", "match_id": 456}
        
        # Verify the payload matches what /api/report expects
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {
            "match_id": 456,
            "score": "11-9, 11-8, 11-7",
            "winner": "Alice",
        }
        
        # Verify the endpoint is correct
        assert "/api/report" in call_args[0][0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])