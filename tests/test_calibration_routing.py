"""Calibration routing contract tests for PR 2.

Covers:
* Calibration event validation (missing fields, stale session)
* Dedup of calibration event IDs
* Success path (trial appended, counter incremented)
* Exception path (rejected, not accepted)
* Calibration events bypass voice-scoring and match-won guards
* Calibration events do not enter _process_voice_transcript
* Calibration events do not trigger apply_score_event_and_refresh_ui
* Defense-in-depth: apply_score_event_and_refresh_ui rejects calibration source
* Delayed event retains immutable trial context
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _clear_calibration_processed_ids():
    from tournament_platform.app.services.voice_scorekeeper.event_drain import (
        _CALIBRATION_PROCESSED_IDS,
        _CALIBRATION_PROCESSED_TRIAL_IDS,
    )
    _CALIBRATION_PROCESSED_IDS.clear()
    _CALIBRATION_PROCESSED_TRIAL_IDS.clear()
    yield
    _CALIBRATION_PROCESSED_IDS.clear()
    _CALIBRATION_PROCESSED_TRIAL_IDS.clear()


def _make_calibration_event(
    session_id="cal-session-1",
    trial_id="cal-trial-1",
    expected_command_id="serve",
    expected_phrase="serve to the left",
    source="calibration",
):
    evt = MagicMock()
    evt.source = source
    evt.calibration_session_id = session_id
    evt.calibration_trial_id = trial_id
    evt.expected_command_id = expected_command_id
    evt.expected_phrase = expected_phrase
    evt.event_id = "cal-evt-1"
    evt.timestamp = 0.0
    evt.session_id = None
    return evt


def _setup_session_state(monkeypatch, **overrides):
    default_state = {
        "voice_scoring_enabled": True,
        "quick_voice_mode": "full",
        "voice_selected_match_id": 1,
        "match_complete": False,
        "match_manager": MagicMock(),
        "voice_continuous_session_id": "current-session",
        "voice_continuous_session_start": 1000.0,
        "voice_listening": True,
        "voice_webrtc_streamer_state": {"playing": True},
        "voice_calibration_active_session_id": "cal-session-1",
        "voice_events_enabled": True,
    }
    default_state.update(overrides)
    default_state["match_manager"].engine.match_status = "in_progress"
    default_state["match_manager"].state.score_a = 0
    default_state["match_manager"].state.score_b = 0
    mock_state = MagicMock()
    mock_state.get.side_effect = lambda key, default=None: default_state.get(key, default)
    mock_state.pop.return_value = None
    import streamlit as st
    monkeypatch.setattr(st, "session_state", mock_state)
    return default_state


class TestCalibrationValidation:
    def test_missing_calibration_session_id_rejected(self):
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
        )

        evt = VoiceTranscriptEvent(
            transcript="serve",
            raw_transcript="serve",
            event_id="e1",
            source="calibration",
            expected_command_id="serve",
            expected_phrase="serve now",
        )
        assert _validate_calibration_event(evt) == "missing_calibration_session_id"

    def test_missing_calibration_trial_id_rejected(self):
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
        )

        evt = VoiceTranscriptEvent(
            transcript="serve",
            raw_transcript="serve",
            event_id="e1",
            source="calibration",
            calibration_session_id="cal-session-1",
            expected_command_id="serve",
            expected_phrase="serve now",
        )
        assert _validate_calibration_event(evt) == "missing_calibration_trial_id"

    def test_missing_expected_command_id_rejected(self):
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
        )

        evt = VoiceTranscriptEvent(
            transcript="serve",
            raw_transcript="serve",
            event_id="e1",
            source="calibration",
            calibration_session_id="cal-session-1",
            calibration_trial_id="cal-trial-1",
            expected_phrase="serve now",
        )
        assert _validate_calibration_event(evt) == "missing_expected_command_id"

    def test_missing_expected_phrase_rejected(self):
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
        )

        evt = VoiceTranscriptEvent(
            transcript="serve",
            raw_transcript="serve",
            event_id="e1",
            source="calibration",
            calibration_session_id="cal-session-1",
            calibration_trial_id="cal-trial-1",
            expected_command_id="serve",
        )
        assert _validate_calibration_event(evt) == "missing_expected_phrase"

    def test_stale_session_rejected(self, monkeypatch):
        import streamlit as st
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
        )

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_calibration_active_session_id": "different-session",
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)

        evt = VoiceTranscriptEvent(
            transcript="serve",
            raw_transcript="serve",
            event_id="e1",
            source="calibration",
            calibration_session_id="cal-session-1",
            calibration_trial_id="cal-trial-1",
            expected_command_id="serve",
            expected_phrase="serve now",
        )
        assert _validate_calibration_event(evt) == "stale_or_replaced_calibration_session"


class TestCalibrationDedup:
    def test_duplicate_event_id_skipped(self, monkeypatch):
        import streamlit as st
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
            _get_calibration_processed_ids,
        )

        _get_calibration_processed_ids("cal-session-1").clear()
        state = _setup_session_state(monkeypatch)

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False
        state["voice_webrtc_ctx"] = {"processor": mock_processor}

        mock_service = MagicMock()
        trial = MagicMock()
        trial.classification.value = "exact"
        mock_service.evaluate_transcript.return_value = trial

        result = _process_voice_events(calibration_service=mock_service)
        assert result.calibration_events_evaluated == 1

        _get_calibration_processed_ids("cal-session-1").add("cal-evt-1")
        result2 = _process_voice_events(calibration_service=mock_service)
        assert result2.calibration_events_evaluated == 0
        _get_calibration_processed_ids("cal-session-1").clear()


class TestCalibrationSuccessPath:
    def test_success_appends_trial_and_increments_counter(self, monkeypatch):
        import streamlit as st

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_events_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        mock_state.match_manager.engine.match_status = "in_progress"

        mock_service = MagicMock()
        trial = MagicMock()
        trial.classification.value = "exact"
        mock_service.evaluate_transcript.return_value = trial

        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        result = _process_voice_events(calibration_service=mock_service)

        assert result.calibration_events_evaluated == 1
        assert len(result.calibration_trials) == 1
        assert result.calibration_trials[0].classification.value == "exact"


class TestCalibrationExceptionPath:
    def test_exception_increments_rejected_not_accepted(self, monkeypatch):
        import streamlit as st

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_events_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        mock_state.match_manager.engine.match_status = "in_progress"

        mock_service = MagicMock()
        mock_service.evaluate_transcript.side_effect = RuntimeError("grammar error")

        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        result = _process_voice_events(calibration_service=mock_service)

        assert result.calibration_events_rejected == 1
        assert result.calibration_events_evaluated == 0


class TestCalibrationBypassesLiveGuards:
    def test_processed_when_voice_scoring_disabled(self, monkeypatch):
        import streamlit as st

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": False,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": False,
            "voice_webrtc_streamer_state": {"playing": False},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_events_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        mock_state.match_manager.engine.match_status = "in_progress"

        mock_service = MagicMock()
        trial = MagicMock()
        trial.classification.value = "exact"
        mock_service.evaluate_transcript.return_value = trial

        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        result = _process_voice_events(calibration_service=mock_service)

        assert result.calibration_events_evaluated == 1

    def test_processed_when_match_is_won(self, monkeypatch):
        import streamlit as st

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_events_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        mock_state.match_manager.engine.match_status = "match_won"

        mock_service = MagicMock()
        trial = MagicMock()
        trial.classification.value = "exact"
        mock_service.evaluate_transcript.return_value = trial

        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        result = _process_voice_events(calibration_service=mock_service)

        assert result.calibration_events_evaluated == 1


class TestCalibrationDoesNotMutateScore:
    def test_does_not_enter_process_voice_transcript(self, monkeypatch):
        import streamlit as st

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_events_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        mock_state.match_manager.engine.match_status = "in_progress"

        mock_service = MagicMock()
        trial = MagicMock()
        trial.classification.value = "exact"
        mock_service.evaluate_transcript.return_value = trial

        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper._process_voice_transcript"
        ) as mock_transcript:
            result = _process_voice_events(calibration_service=mock_service)
            assert result.calibration_events_evaluated == 1
            mock_transcript.assert_not_called()

    def test_does_not_trigger_apply_score_event_and_refresh_ui(self, monkeypatch):
        import streamlit as st

        mock_processor = MagicMock()
        mock_processor.get_events.return_value = [
            ("serve", "serve", _make_calibration_event())
        ]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_events_enabled": True,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        mock_state.match_manager.engine.match_status = "in_progress"

        mock_service = MagicMock()
        trial = MagicMock()
        trial.classification.value = "exact"
        mock_service.evaluate_transcript.return_value = trial

        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.apply_score_event_and_refresh_ui"
        ) as mock_apply:
            result = _process_voice_events(calibration_service=mock_service)
            assert result.calibration_events_evaluated == 1
            mock_apply.assert_not_called()


class TestDefenseInDepth:
    def test_apply_score_event_and_refresh_ui_rejects_calibration_source(self, monkeypatch):
        from tournament_platform.app.pages.voice_scorekeeper import (
            apply_score_event_and_refresh_ui,
        )
        from tournament_platform.app.services.voice_scorekeeper.scoring_actions import (
            ScoreApplyResult,
        )

        mock_mm = MagicMock()
        mock_mm.state.get_score_string.return_value = "0-0"

        import streamlit as st
        monkeypatch.setattr(st, "session_state", MagicMock())
        st.session_state.get.return_value = mock_mm

        result = apply_score_event_and_refresh_ui(
            transcript="serve",
            source="calibration",
            enable_confirmation=False,
        )
        assert result.success is False
        assert result.reason == "calibration_source_cannot_mutate_score"
        assert result.previous_score == "0-0"
        assert result.new_score == "0-0"


class TestImmutableTrialContext:
    def test_delayed_event_retains_calibration_fields(self):
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
        )

        evt = VoiceTranscriptEvent(
            transcript="serve",
            raw_transcript="serve",
            event_id="cal-evt-1",
            source="calibration",
            calibration_session_id="cal-session-1",
            calibration_trial_id="cal-trial-1",
            expected_command_id="serve",
            expected_phrase="serve to the left",
        )
        assert evt.calibration_session_id == "cal-session-1"
        assert evt.calibration_trial_id == "cal-trial-1"
        assert evt.expected_command_id == "serve"
        assert evt.expected_phrase == "serve to the left"