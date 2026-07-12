"""
Centralized API client for the Tournament Platform Streamlit frontend.

This module provides a clean interface for making API calls to the FastAPI backend,
with centralized error handling and user-friendly error messages.
"""

import logging
from typing import Any, Optional, Dict

import requests

from tournament_platform.app.settings import API_BASE_URL, API_TIMEOUT_SECONDS, SHOW_DEBUG_DETAILS

logger = logging.getLogger(__name__)


class ApiClient:
    """
    Centralized API client for the Tournament Platform.
    
    Provides methods for common API operations with consistent error handling
    and user-friendly error messages.
    """
    
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """
        Initialize the API client.
        
        Args:
            base_url: Optional override for the API base URL.
            timeout: Optional override for the request timeout in seconds.
        """
        self.base_url = base_url or API_BASE_URL
        self.timeout = timeout or API_TIMEOUT_SECONDS
    
    def _build_url(self, endpoint: str) -> str:
        """Build a full URL from an endpoint path."""
        return f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    
    def _handle_error(self, error: Exception, context: str) -> None:
        """
        Log error details and return a user-safe error message.
        
        Args:
            error: The exception that occurred.
            context: A short description of what operation failed.
        """
        logger.error(f"{context} failed: {error}", exc_info=True)
    
    def health(self) -> Optional[Dict[str, Any]]:
        """
        Check if the API is healthy.
        
        Returns:
            A dict with health status if successful, None otherwise.
        """
        try:
            response = requests.get(
                self._build_url("/health"),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            self._handle_error(None, "API health check - connection error")
            return None
        except requests.exceptions.Timeout:
            self._handle_error(None, "API health check - timeout")
            return None
        except requests.exceptions.HTTPError as e:
            self._handle_error(e, "API health check - HTTP error")
            return None
        except Exception as e:
            self._handle_error(e, "API health check")
            return None
    
    def report_match_legacy(
        self,
        match_id: int,
        score: str,
        winner: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Report a match result using the legacy /api/report endpoint.
        
        This endpoint accepts a payload for match reporting with match_id, winner, and score.
        The match must already exist in the database with player1_id and player2_id set.
        
        Args:
            match_id: The ID of the match to report.
            score: Match score (e.g., "11-9, 11-8").
            winner: Name of the winner.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        try:
            response = requests.post(
                self._build_url("/api/report"),
                json={
                    "match_id": match_id,
                    "score": score,
                    "winner": winner,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            self._handle_error(None, "Match report - connection error")
            return None
        except requests.exceptions.Timeout:
            self._handle_error(None, "Match report - timeout")
            return None
        except requests.exceptions.HTTPError as e:
            self._handle_error(e, "Match report - HTTP error")
            return None
        except Exception as e:
            self._handle_error(e, "Match report")
            return None
    
    def ask_rules(self, question: str) -> Optional[Dict[str, Any]]:
        """
        Ask a question about tournament rules.
        
        Args:
            question: The question to ask.
            
        Returns:
            A dict with the answer if successful, None otherwise.
        """
        try:
            response = requests.post(
                self._build_url("/api/rules/ask"),
                json={"question": question},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            self._handle_error(None, "Rules query - connection error")
            return None
        except requests.exceptions.Timeout:
            self._handle_error(None, "Rules query - timeout")
            return None
        except requests.exceptions.HTTPError as e:
            self._handle_error(e, "Rules query - HTTP error")
            return None
        except Exception as e:
            self._handle_error(e, "Rules query")
            return None
    
    def get(self, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Make a GET request to the API.
        
        Args:
            endpoint: API endpoint path.
            **kwargs: Additional arguments passed to requests.get.
            
        Returns:
            A dict with the response JSON if successful, None otherwise.
        """
        try:
            response = requests.get(
                self._build_url(endpoint),
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            self._handle_error(None, f"GET {endpoint} - connection error")
            return None
        except requests.exceptions.Timeout:
            self._handle_error(None, f"GET {endpoint} - timeout")
            return None
        except requests.exceptions.HTTPError as e:
            self._handle_error(e, f"GET {endpoint} - HTTP error")
            return None
        except Exception as e:
            self._handle_error(e, f"GET {endpoint}")
            return None
    
    def post(self, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Make a POST request to the API.
        
        Args:
            endpoint: API endpoint path.
            **kwargs: Additional arguments passed to requests.post.
            
        Returns:
            A dict with the response JSON if successful, None otherwise.
        """
        try:
            response = requests.post(
                self._build_url(endpoint),
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            self._handle_error(None, f"POST {endpoint} - connection error")
            return None
        except requests.exceptions.Timeout:
            self._handle_error(None, f"POST {endpoint} - timeout")
            return None
        except requests.exceptions.HTTPError as e:
            self._handle_error(e, f"POST {endpoint} - HTTP error")
            return None
        except Exception as e:
            self._handle_error(e, f"POST {endpoint}")
            return None
    
    def patch(self, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Make a PATCH request to the API.
        
        Args:
            endpoint: API endpoint path.
            **kwargs: Additional arguments passed to requests.patch.
            
        Returns:
            A dict with the response JSON if successful, None otherwise.
        """
        try:
            response = requests.patch(
                self._build_url(endpoint),
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            self._handle_error(None, f"PATCH {endpoint} - connection error")
            return None
        except requests.exceptions.Timeout:
            self._handle_error(None, f"PATCH {endpoint} - timeout")
            return None
        except requests.exceptions.HTTPError as e:
            self._handle_error(e, f"PATCH {endpoint} - HTTP error")
            return None
        except Exception as e:
            self._handle_error(e, f"PATCH {endpoint}")
            return None
    
    # ---------------------------------------------------------------------------
    # Operator Console API methods
    # ---------------------------------------------------------------------------
    
    def call_match(self, match_id: int, table: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Call a match via API.
        
        Args:
            match_id: The match ID to call.
            table: Optional table name.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.post(f"/api/operator/matches/{match_id}/call", json={"table": table} if table else {})
    
    def start_match(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Start a match via API.
        
        Args:
            match_id: The match ID to start.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.post(f"/api/operator/matches/{match_id}/start")
    
    def complete_match(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Complete a match via API.
        
        Args:
            match_id: The match ID to complete.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.post(f"/api/operator/matches/{match_id}/complete")
    
    def delay_match(self, match_id: int, delay_minutes: int = 15) -> Optional[Dict[str, Any]]:
        """
        Delay a match via API.
        
        Args:
            match_id: The match ID to delay.
            delay_minutes: Number of minutes to delay.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.post(
            f"/api/operator/matches/{match_id}/delay",
            json={"delay_minutes": delay_minutes}
        )
    
    def reschedule_match(
        self,
        match_id: int,
        scheduled_time: str,
        table: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Reschedule a match via API.
        
        Args:
            match_id: The match ID to reschedule.
            scheduled_time: New scheduled time.
            table: Optional table name.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.patch(
            f"/api/operator/matches/{match_id}/reschedule",
            json={"scheduled_time": scheduled_time, "table": table}
        )
    
    def reset_call_match(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Reset call status to pending via API.
        
        Args:
            match_id: The match ID to reset.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.post(f"/api/operator/matches/{match_id}/reset-call")

    def report_match(
        self,
        match_id: int,
        score1: int,
        score2: int,
        winner: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Report a match result via API.
        
        Args:
            match_id: The match ID to report.
            score1: Player 1's score.
            score2: Player 2's score.
            winner: Optional winner name.
            
        Returns:
            A dict with the result if successful, None otherwise.
        """
        return self.post(
            f"/api/operator/matches/{match_id}/report",
            json={"score1": score1, "score2": score2, "winner": winner}
        )

    def import_players_csv(self, csv_text: str) -> Optional[Dict[str, Any]]:
        """Bulk-import players from CSV text via the operator endpoint."""
        return self.post("/api/operator/players/import-csv", json={"csv": csv_text})

    def public_register(self, name: str, email: str) -> Optional[Dict[str, Any]]:
        """Public self-registration (flag-gated on the server)."""
        return self.post("/api/public/register", json={"name": name, "email": email})


# Default singleton instance
api_client = ApiClient()