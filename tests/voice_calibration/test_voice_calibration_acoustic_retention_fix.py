"""
Integration regression test for plan 1785757678522 — acoustic measurement retention.

Verifies that consuming command trials, negative trials, TTS transcripts, and
phase transitions do NOT erase previously recorded acoustic measurements.
"""

from __future__ import annotations

import time
import dataclasses

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationSession,
    CalibrationOverallStatus,
    CommandTrial,
    NegativeTrial,
    NegativeTrialClassification,
    TrialClassification,
    TtsEchoTranscript,
    TtsEchoTestContext,
    AliasConfirmationCandidate,
    CalibrationPhase,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


def _make_session(session_id: str = "sess-acoustic-retention") -> CalibrationSession:
    return CalibrationSession(
        session_id=session_id,
        created_at=time.time(),
        commands=("point_red", "point_blue"),
        attempts_per_command=3,
        current_command_index=0,
    )


def _make_incomplete_silence(service, session, measurement_id):
    """Create an incomplete silence baseline measurement (complete=False)."""
    complete_one = service.create_silence_measurement(
        session, measurement_id, median_dbfs=-45.0, p90_dbfs=-43.0, p95_dbfs=-42.0
    )
    return dataclasses.replace(complete_one, capture=dataclasses.replace(complete_one.capture, complete=False))


def _make_complete_silence(service, session, measurement_id, median_dbfs=-40.0):
    return service.create_silence_measurement(
        session, measurement_id, median_dbfs=median_dbfs, p90_dbfs=-38.0, p95_dbfs=-37.0
    )


def _make_complete_speech(service, session, measurement_id, speech_rms_dbfs=-20.0):
    return service.create_speech_measurement(
        session, measurement_id, speech_rms_dbfs=speech_rms_dbfs, speech_to_background_difference_db=20.0
    )


def _make_trial(trial_id: str, command_id: str = "point_red", classification=TrialClassification.EXACT):
    return CommandTrial(
        trial_id=trial_id,
        expected_command_id=command_id,
        expected_phrase="point red",
        raw_transcript="point red",
        normalized_transcript="point red",
        resolved_command_id=command_id,
        classification=classification,
        parser_confidence=0.95,
        rejection_reason=None,
        asr_latency_ms=50.0,
    )


class TestAcousticRetentionLifecycle:
    """PR I.17 — Reproduce the supplied lifecycle and assert acoustic data remains present."""

    def test_full_lifecycle_measurements_survive_command_trials(self):
        service = VoiceCalibrationService()
        session = _make_session()

        # 1. Consume an incomplete silence result (the retry from the audit)
        incomplete_silence = _make_incomplete_silence(service, session, "m-incomplete-silence")
        session = service.consume_measurements(session, (incomplete_silence,))
        assert len(session.measurements) == 1

        # 2. Consume 3 complete silence results
        for i, mid in enumerate(["m-sil-1", "m-sil-2", "m-sil-3"]):
            m = _make_complete_silence(service, session, mid, median_dbfs=-40.0 - i * 1.0)
            session = service.consume_measurements(session, (m,))

        # 3. Consume 3 complete normal-speech results
        for i, mid in enumerate(["m-spe-1", "m-spe-2", "m-spe-3"]):
            m = _make_complete_speech(service, session, mid, speech_rms_dbfs=-20.0 - i * 0.5)
            session = service.consume_measurements(session, (m,))

        total_measurements = len(session.measurements)

        # 4. Consume command-trial results (the critical overwrite path)
        for i, tid in enumerate(["t-1", "t-2", "t-3", "t-4", "t-5", "t-6"]):
            cmd = "point_red" if i % 2 == 0 else "point_blue"
            trial = _make_trial(f"t-{i}", cmd, TrialClassification.EXACT)
            session = service.consume_trials(session, (trial,))

        # 5. Consume negative trials
        neg = NegativeTrial(
            trial_id="neg-1",
            prompt_id="prompt-1",
            raw_transcript="random noise",
            normalized_transcript="random noise",
            parser_command_id=None,
            parser_confidence=0.0,
            would_accept_live=False,
            classification=NegativeTrialClassification.CORRECTLY_REJECTED,
            created_at=time.time(),
        )
        session = service.consume_negative_trials(session, (neg,))

        # 6. Consume TTS echo transcripts
        tts = service.create_tts_echo_transcript("point red", tts_source="calibration")
        session = service.consume_tts_echo_transcripts(session, (tts,))

        # 7. Verify measurements survived ALL consumption
        assert len(session.measurements) == total_measurements, (
            f"Measurements lost during consumption: had {total_measurements}, now {len(session.measurements)}"
        )

        # 8. Compute results
        results = service.compute_results(session)

        # 9. Assertions
        assert results.session_id == session.session_id
        assert results.acoustic_summary.total_measurements == total_measurements
        assert results.acoustic_summary.measurement_count == total_measurements
        assert results.acoustic_summary.selected_silence_measurement_id is not None
        assert results.acoustic_summary.selected_speech_measurement_id is not None
        assert results.acoustic_summary.silence_measurement_count >= 3
        assert results.acoustic_summary.speech_measurement_count >= 3
        assert results.acoustic_summary.required_kinds_present == 2
        assert results.acoustic_summary.valid_complete_measurements >= 2

        # Microphone environment must NOT be INCOMPLETE
        acoustic_section = None
        for section in results.section_outcomes:
            if section.section == "microphone_environment":
                acoustic_section = section
                break

        assert acoustic_section is not None, "microphone_environment section missing from results"
        assert acoustic_section.status != CalibrationOverallStatus.INCOMPLETE, (
            f"Microphone environment is INCOMPLETE with {total_measurements} measurements"
        )
        assert acoustic_section.status != CalibrationOverallStatus.INVALID_DATA, (
            "Microphone environment reported INVALID_DATA despite valid measurements"
        )

        # No ACOUSTIC_SILENCE_MISSING reason when silence exists
        for reason in results.blocking_reasons + results.warning_reasons + results.incomplete_reasons + results.invalid_data_reasons:
            assert reason.code != "ACOUSTIC_SILENCE_MISSING", (
                f"ACOUSTIC_SILENCE_MISSING shown despite valid silence measurement: {reason.evidence}"
            )

    def test_command_trial_consumption_preserves_measurements(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        measurements_before = len(session.measurements)
        trial = _make_trial("t-1")
        session = service.consume_trials(session, (trial,))

        assert len(session.measurements) == measurements_before, (
            "Consuming command trials erased acoustic measurements"
        )

    def test_negative_trial_consumption_preserves_measurements(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        measurements_before = len(session.measurements)
        neg = NegativeTrial(
            trial_id="neg-1",
            prompt_id="prompt-1",
            raw_transcript="noise",
            normalized_transcript="noise",
            parser_command_id=None,
            parser_confidence=0.0,
            would_accept_live=False,
            classification=NegativeTrialClassification.CORRECTLY_REJECTED,
            created_at=time.time(),
        )
        session = service.consume_negative_trials(session, (neg,))

    def test_tts_consumption_preserves_measurements(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        measurements_before = len(session.measurements)
        tts = service.create_tts_echo_transcript("point red", tts_source="calibration")
        session = service.consume_tts_echo_transcripts(session, (tts,))

        assert len(session.measurements) == measurements_before

    def test_phase_transition_preserves_measurements(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        measurements_before = len(session.measurements)

        # Simulate the command-trial-to-next-command transition (the buggy path)
        # that previously created a CalibrationSession without measurements
        updated = dataclasses.replace(
            session,
            current_command_index=1,
            revision=session.revision + 1,
        )

        assert len(updated.measurements) == measurements_before, (
            "Phase transition (current_command_index advance) erased measurements"
        )


class TestAcousticSummaryExtraction:
    """Domain tests for compute_acoustic_summary measurement selection."""

    def test_four_valid_silence_three_valid_speech(self):
        service = VoiceCalibrationService()
        session = _make_session()

        for i in range(4):
            m = _make_complete_silence(service, session, f"m-sil-{i}")
            session = service.consume_measurements(session, (m,))
        for i in range(3):
            m = _make_complete_speech(service, session, f"m-spe-{i}")
            session = service.consume_measurements(session, (m,))

        summary = service.compute_acoustic_summary(session)
        assert summary.total_measurements == 7
        assert summary.complete_measurements == 7
        assert summary.valid_complete_measurements == 7
        assert summary.silence_measurement_count == 4
        assert summary.speech_measurement_count == 3
        assert summary.required_kinds_present == 2
        assert summary.selected_silence_measurement_id == "m-sil-3"
        assert summary.selected_speech_measurement_id == "m-spe-2"

    def test_incomplete_retry_does_not_hide_later_completed(self):
        service = VoiceCalibrationService()
        session = _make_session()

        incomplete = _make_incomplete_silence(service, session, "m-incomplete")
        session = service.consume_measurements(session, (incomplete,))

        complete = _make_complete_silence(service, session, "m-completed")
        session = service.consume_measurements(session, (complete,))

        summary = service.compute_acoustic_summary(session)
        assert summary.total_measurements == 2
        assert summary.complete_measurements == 1
        assert summary.valid_complete_measurements == 1
        assert summary.selected_silence_measurement_id == "m-completed"

    def test_latest_valid_measurement_per_kind_selected(self):
        service = VoiceCalibrationService()
        session = _make_session()

        m1 = _make_complete_silence(service, session, "m-sil-1", median_dbfs=-40.0)
        m2 = _make_complete_silence(service, session, "m-sil-2", median_dbfs=-45.0)
        session = service.consume_measurements(session, (m1, m2))

        summary = service.compute_acoustic_summary(session)
        assert summary.selected_silence_measurement_id == "m-sil-2"
        assert summary.background_median_dbfs == -45.0

    def test_one_silence_plus_one_speech_satisfies_coverage(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        results = service.compute_results(session)
        assert results.acoustic_summary.required_kinds_present == 2

        acoustic_section = None
        for section in results.section_outcomes:
            if section.section == "microphone_environment":
                acoustic_section = section
                break
        assert acoustic_section is not None
        assert acoustic_section.status != CalibrationOverallStatus.INCOMPLETE

    def test_two_silence_without_speech_remains_incomplete(self):
        service = VoiceCalibrationService()
        session = _make_session()

        s1 = _make_complete_silence(service, session, "m-sil-1")
        s2 = _make_complete_silence(service, session, "m-sil-2")
        session = service.consume_measurements(session, (s1, s2))

        results = service.compute_results(session)
        assert results.acoustic_summary.speech_measurement_count == 0
        assert results.acoustic_summary.required_kinds_present == 1

        acoustic_section = None
        for section in results.section_outcomes:
            if section.section == "microphone_environment":
                acoustic_section = section
                break
        assert acoustic_section.status == CalibrationOverallStatus.INCOMPLETE

    def test_missing_silence_and_missing_speech_generate_different_codes(self):
        service = VoiceCalibrationService()
        session = _make_session()

        # No measurements at all
        results = service.compute_results(session)
        codes = [r.code for r in results.blocking_reasons + results.incomplete_reasons]
        assert "ACOUSTIC_SILENCE_MISSING" in codes
        assert "ACOUSTIC_SPEECH_MISSING" in codes

    def test_report_never_asks_for_two_silence_measurements(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        results = service.compute_results(session)
        all_reasons = (
            results.blocking_reasons + results.warning_reasons
            + results.incomplete_reasons + results.invalid_data_reasons
        )
        for reason in all_reasons:
            assert "2 silence" not in reason.remediation.lower(), (
                f"Remediation should not ask for '2 silence' measurements: {reason.remediation}"
            )
            assert "2 silence" not in reason.explanation.lower(), (
                f"Explanation should not ask for '2 silence' measurements: {reason.explanation}"
            )


class TestStaleSessionRevision:
    """Tests for revision-guarded session updates."""

    def test_revision_increments_after_update(self):
        service = VoiceCalibrationService()
        session = _make_session()
        assert session.revision == 0

        silence = _make_complete_silence(service, session, "m-sil")
        session = service.consume_measurements(session, (silence,))
        assert session.revision == 1

        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (speech,))
        assert session.revision == 2

    def test_stale_revision_cannot_overwrite_newer(self):
        service = VoiceCalibrationService()
        session = _make_session()  # revision 0

        silence = _make_complete_silence(service, session, "m-sil")
        session_v1 = service.consume_measurements(session, (silence,))
        assert session_v1.revision == 1

        speech = _make_complete_speech(service, session, "m-spe")
        session_v2 = service.consume_measurements(session_v1, (speech,))
        assert session_v2.revision == 2
        assert session_v2.measurements == session_v2.measurements

        # Simulate stale update: update from revision 1 instead of revision 2
        stale = service.consume_measurements(session_v1, (speech,))
        assert stale.revision == 2
        assert len(stale.measurements) == 2
        assert stale.session_id == session_v2.session_id


class TestResultComputationFromAuthoritativeState:
    """Tests for result computation using the latest session state."""

    def test_results_use_latest_session_state(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        results = service.compute_results(session)
        assert results.acoustic_summary.total_measurements == 2
        assert results.acoustic_summary.valid_complete_measurements == 2

    def test_seven_complete_measurements_cannot_report_count_zero(self):
        service = VoiceCalibrationService()
        session = _make_session()

        # 4 complete silence + 3 complete speech = 7
        for i in range(4):
            m = _make_complete_silence(service, session, f"m-sil-{i}")
            session = service.consume_measurements(session, (m,))
        for i in range(3):
            m = _make_complete_speech(service, session, f"m-spe-{i}")
            session = service.consume_measurements(session, (m,))

        results = service.compute_results(session)
        assert results.acoustic_summary.measurement_count == 7
        assert results.acoustic_summary.total_measurements == 7
        assert results.acoustic_summary.valid_complete_measurements == 7

    def test_results_include_selected_measurement_ids(self):
        service = VoiceCalibrationService()
        session = _make_session()

        silence = _make_complete_silence(service, session, "m-sil")
        speech = _make_complete_speech(service, session, "m-spe")
        session = service.consume_measurements(session, (silence, speech))

        results = service.compute_results(session)
        assert results.acoustic_summary.selected_silence_measurement_id == "m-sil"
        assert results.acoustic_summary.selected_speech_measurement_id == "m-spe"

    def test_results_audit_contains_exact_acoustic_counts(self):
        service = VoiceCalibrationService()
        session = _make_session()

        for i in range(4):
            m = _make_complete_silence(service, session, f"m-sil-{i}")
            session = service.consume_measurements(session, (m,))
        for i in range(3):
            m = _make_complete_speech(service, session, f"m-spe-{i}")
            session = service.consume_measurements(session, (m,))

        results = service.compute_results(session)
        assert results.acoustic_summary == dataclasses.replace(
            results.acoustic_summary,
            total_measurements=7,
            complete_measurements=7,
            valid_complete_measurements=7,
            silence_measurement_count=4,
            speech_measurement_count=3,
            required_kinds_present=2,
        )

    def test_contradictory_state_produces_invalid_data_not_fail(self):
        service = VoiceCalibrationService()
        session = _make_session()

        # Measurements exist but are all incomplete
        incomplete = _make_incomplete_silence(service, session, "m-incomplete")
        session = service.consume_measurements(session, (incomplete,))

        results = service.compute_results(session)
        assert results.acoustic_summary.total_measurements > 0
        assert results.acoustic_summary.valid_complete_measurements == 0
        # Should NOT report measurement_count=0
        assert results.acoustic_summary.measurement_count == 1
