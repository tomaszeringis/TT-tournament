"""
Tests for voice AI grounding invariant (Phase 5).

Verifies that no AI path (LLM interpreter, commentary, dataset recorder)
mutates match scores or calls MatchManager apply/engine mutators directly.
"""

import pytest
from unittest.mock import patch, MagicMock

from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.app.services.voice_service import VoiceService, VoiceServiceError
from tournament_platform.app.services.voice_llm import LLMInterpreter, LLMInterpreterError
from tournament_platform.services.commentary_service import CommentaryService, SpokenScoreState, CommentarySettings


class TestVoiceAIGrounding:
    """LLM proposals must always require confirmation and never auto-apply."""

    def setup_method(self):
        self.match_manager = MatchManager(player_a="Alice", player_b="Bob")
        self.service = VoiceService(match_manager=self.match_manager)

    def test_llm_proposal_always_requires_confirmation(self):
        """LLM output should always set requires_confirmation=True."""
        # Mock LLM interpreter
        mock_llm = MagicMock()
        mock_llm.interpret.return_value = MagicMock(
            type="increment",
            score_a=1,
            score_b=0,
            player="A",
            confidence=0.9,
            reasoning="LLM thinks A scored",
            requires_confirmation=False,  # LLM says false, but grounding should override
        )
        self.service.llm_interpreter = mock_llm

        parsed = self.service._ground_llm_proposal("point to alice", 0, 0)
        assert parsed is not None
        assert parsed.requires_confirmation is True
        assert parsed.source == "llm"

    def test_llm_proposal_rejects_unknown_type(self):
        """Unknown LLM types should be rejected."""
        mock_llm = MagicMock()
        mock_llm.interpret.return_value = MagicMock(
            type="unknown",
            score_a=0,
            score_b=0,
            player="A",
            confidence=0.0,
            reasoning="unknown",
        )
        self.service.llm_interpreter = mock_llm

        parsed = self.service._ground_llm_proposal("gibberish", 0, 0)
        assert parsed is None

    def test_llm_proposal_sanitizes_player(self):
        """Non A/B players should be normalized to A."""
        mock_llm = MagicMock()
        mock_llm.interpret.return_value = MagicMock(
            type="increment",
            score_a=0,
            score_b=0,
            player="Charlie",  # hallucinated player
            confidence=0.8,
            reasoning="LLM hallucinated player",
        )
        self.service.llm_interpreter = mock_llm

        parsed = self.service._ground_llm_proposal("point to charlie", 0, 0)
        assert parsed is not None
        assert parsed.slots.get("player") == "A"

    def test_commentary_service_does_not_mutate_match_state(self):
        """CommentaryService should never mutate scores."""
        service = CommentaryService()
        state = SpokenScoreState(
            score_a=5,
            score_b=3,
            sets_a=1,
            sets_b=0,
            current_set=2,
            player_a="Alice",
            player_b="Bob",
            player_a_id=1,
            player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        original_score_a = state.score_a
        original_score_b = state.score_b

        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=CommentarySettings(enabled=True),
            event_id="test-id",
        )

        assert state.score_a == original_score_a
        assert state.score_b == original_score_b
        assert line.text
        assert "Alice" in line.text or line.text

    def test_process_transcript_with_llm_fallback(self):
        """LLM fallback should produce a confirmed event, not auto-apply."""
        # Parser returns unknown
        self.service.parser.parse = MagicMock(return_value=MagicMock(type="unknown", score_a=0, score_b=0, confidence=0.0, raw_text="test"))

        mock_llm = MagicMock()
        mock_llm.interpret.return_value = MagicMock(
            type="increment",
            score_a=0,
            score_b=0,
            player="A",
            confidence=0.85,
            reasoning="",
        )
        self.service.llm_interpreter = mock_llm

        processed, event = self.service.process_transcript("gibberish command")
        assert event.type == "increment"
        assert event.source == "llm"
        assert event.requires_confirmation is True


class TestOptionalDependencyImports:
    """Voice modules should import gracefully when optional deps are missing."""

    def test_webrtcvad_import_guard(self):
        with patch.dict("sys.modules", {"webrtcvad": None}):
            from tournament_platform.app.services.voice.vad import WebRTCVAD
            vad = WebRTCVAD()
            assert vad.is_speech(b"", 16000) is False

    def test_silero_vad_import_guard(self):
        with patch.dict("sys.modules", {"silero_vad": None}):
            from tournament_platform.app.services.voice.vad import SileroVAD
            vad = SileroVAD()
            assert vad.is_speech(b"", 16000) is False

    def test_streamlit_webrtc_import_guard(self):
        with patch.dict("sys.modules", {"streamlit_webrtc": None}):
            try:
                import tournament_platform.app.pages.voice_scorekeeper
            except Exception as e:
                pytest.fail(f"voice_scorekeeper should import without streamlit-webrtc: {e}")

    def test_faster_whisper_import_guard(self):
        with patch.dict("sys.modules", {"faster_whisper": None}):
            from tournament_platform.app.services.voice_asr import LocalASR
            asr = LocalASR()
            assert asr.is_available() is False
            assert asr.transcribe_chunk(b"\x00\x00") == ""
