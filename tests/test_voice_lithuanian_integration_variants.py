from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from tests.test_voice_behavioral_integration import _make_live_session_state, _apply_via_shared, _streamlit, _SessionStateProxy

@pytest.fixture(autouse=True)
def _reset_streamlit_env():
    """Ensure each test gets a clean streamlit mock."""
    _streamlit.session_state = _SessionStateProxy()
    _streamlit.rerun = MagicMock()
    # Reset other st mocks if needed, but these are minimal for scoring
    yield

class TestLithuanianIntegrationVariants:
    """Verifies that observed Deepgram variants flow through the real application scoring pipeline."""

    @pytest.mark.parametrize("transcript, expected_score", [
        ("Taškas kairėje.", "1-0"),
        ("Taškas dešinėje.", "0-1"),
        ("Taškas kairį.", "1-0"),
        ("Taškas kairi.", "1-0"),
        ("taskas kaireje", "1-0"),
        ("taskas desineje", "0-1"),
    ])
    def test_variant_updates_score(self, transcript, expected_score):
        state = _make_live_session_state()
        mm = state["match_manager"]
        assert mm.state.get_score_string() == "0-0"
        
        # Apply the variant
        result = _apply_via_shared(state, transcript, source="continuous")
        assert result.success is True, f"Failed for '{transcript}': {result.reason}"
        assert mm.state.get_score_string() == expected_score, f"After '{transcript}': expected {expected_score}, got {mm.state.get_score_string()}"

    def test_lithuanian_sequence_end_to_end(self):
        """0-0 -> Taškas kairėje. -> 1-0 -> Taškas kairį. -> 2-0 -> Taškas dešinėje. -> 2-1"""
        state = _make_live_session_state()
        mm = state["match_manager"]
        
        sequence = [
            ("Taškas kairėje.", "1-0"),
            ("Taškas kairį.", "2-0"),
            ("Taškas dešinėje.", "2-1"),
        ]
        
        for transcript, expected in sequence:
            # Reset cooldown to simulate distinct utterances
            state["voice_last_applied_event_key"] = None
            state["voice_last_applied_event_ts"] = 0.0
            
            result = _apply_via_shared(state, transcript, source="continuous")
            assert result.success is True, f"Failed at '{transcript}': {result.reason}"
            assert mm.state.get_score_string() == expected

    def test_negative_phrase_no_mutation(self):
        """Conversational phrases should not change the score."""
        state = _make_live_session_state()
        mm = state["match_manager"]
        
        phrases = [
            "Iškuštu ne likumė.",
            "šiandien kairėje žaidėjas",
            "labas vakaras",
        ]
        
        for phrase in phrases:
            result = _apply_via_shared(state, phrase, source="continuous")
            # Should either fail to parse or be rejected
            assert result.success is False or result.intent == "unknown"
            assert mm.state.get_score_string() == "0-0"
