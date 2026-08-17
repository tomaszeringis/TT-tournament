"""
Integration tests for voice calibration acoustic measurement reconciliation.

Tests the complete flow:
  processor completes → measurement drained → session consumed → UI resolves
"""

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice_audio import SAMPLE_FORMAT_FLOAT32
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    SilenceBaselineMetrics,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)
from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
    AcousticUiState,
    resolve_acoustic_ui_state,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    AcousticCaptureRuntimeSnapshot,
)


class TestAcousticMeasurementReconciliation:
    """Test that completed acoustic measurements reconcile correctly.
    
    These tests verify the fix for the bug where processor completes a
    measurement, drains it, consumes it into the session, but the UI still
    shows FAILED: active_measurement_missing_from_processor.
    """

    def setup_method(self):
        self.service = VoiceCalibrationService()
        self.session_id = str(uuid.uuid4())
        self.measurement_id = str(uuid.uuid4())

    def _make_silence_baseline_result(
        self,
        measurement_id: str,
        session_id: str,
        complete: bool = True,
        frame_count: int = 144000,
    ) -> SilenceBaselineMetrics:
        """Create a realistic silence baseline measurement result."""
        capture = AcousticCaptureSummary(
            measurement_id=measurement_id,
            calibration_session_id=session_id,
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=frame_count,
            scalar_sample_count=frame_count,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=frame_count,
            invalid_frame_count=0,
            rms=-40.0,
            rms_dbfs=-40.0,
            peak=-30.0,
            peak_dbfs=-30.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=complete,
            warning_codes=(),
            created_at=time.time(),
            skipped=False,
        )
        return SilenceBaselineMetrics(
            capture=capture,
            median_rms=-40.0,
            median_dbfs=-40.0,
            p90_rms=-35.0,
            p90_dbfs=-35.0,
            p95_rms=-32.0,
            p95_dbfs=-32.0,
            mad_rms=2.0,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )

    def test_consume_acoustic_measurement_renders_complete_state(self):
        """
        INTEGRATION TEST: Main bug reproduction and fix verification.
        
        Given:
          - Active calibration session
          - Active measurement (armed, measuring)
          - Processor completes measurement with complete=True
          - Processor becomes inactive (normal)
        
        When:
          - Measurement is drained from processor
          - Measurement is reconciled using reconcile_acoustic_measurements()
          - Session is updated in state
          - CompletedMeasurementRef is stored
          - Active keys are cleared AFTER reference is stored
        
        Then:
          - Renderer receives updated session AND completed_ref
          - Terminal result is found via CompletedMeasurementRef
          - Resolver returns COMPLETE (not FAILED)
        """
        # Setup: Create a calibration session and arm a measurement
        session = self.service.start_session(self.session_id)
        assert session.session_id == self.session_id

        # Simulate processor completing a measurement
        terminal_result = self._make_silence_baseline_result(
            measurement_id=self.measurement_id,
            session_id=self.session_id,
            complete=True,
        )

        # === PART 1: VERIFY BUG (WITHOUT FIX) ===
        # Show that without CompletedMeasurementRef, lookup fails
        updated_session = self.service.consume_measurements(
            session=session,
            measurements=(terminal_result,),
        )

        # Verify session was updated with measurement
        assert len(updated_session.measurements) == 1
        assert updated_session.measurements[0] == terminal_result
        assert updated_session.session_id == self.session_id

        # Simulate processor snapshot showing inactive (normal after completion)
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=12345,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        # BUG PATH: Without CompletedMeasurementRef, active keys cleared, lookup fails
        active_measurement_id = self.measurement_id
        active_measurement_kind = CalibrationMeasurementKind.SILENCE_BASELINE
        terminal_result_from_failed_lookup = None  # Lookup fails

        resolution_buggy = resolve_acoustic_ui_state(
            active_measurement_id=active_measurement_id,
            active_measurement_kind=active_measurement_kind,
            terminal_result=terminal_result_from_failed_lookup,  # Lookup failed
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id=self.session_id,
            reconciliation_error=None,
        )

        # Verify bug is reproducible
        assert resolution_buggy.state == AcousticUiState.FAILED
        assert resolution_buggy.reason == "active_measurement_missing_from_processor"
        print("[PASS] BUG REPRODUCED: Got FAILED with active_measurement_missing_from_processor")

        # === PART 2: VERIFY FIX (WITH RECONCILIATION) ===
        # Now use the new reconciliation flow to get CompletedMeasurementRef
        from tournament_platform.app.services.voice_calibration.models import (
            CompletedMeasurementRef,
        )
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            find_rendered_terminal_result,
        )

        # Step 1: Use reconcile_acoustic_measurements (simulating voice_scorekeeper.py flow)
        reconciliation = self.service.reconcile_acoustic_measurements(
            session=session,
            measurements=(terminal_result,),
            active_measurement_id=active_measurement_id,
            active_measurement_kind=active_measurement_kind,
        )
        updated_session2 = reconciliation.session
        completed_measurement = reconciliation.completed_ref
        error = reconciliation.rejection_reasons[0] if reconciliation.rejection_reasons else None

        # Verify reconciliation succeeded
        assert error is None
        assert completed_measurement is not None
        assert completed_measurement.measurement_id == self.measurement_id
        assert completed_measurement.kind == CalibrationMeasurementKind.SILENCE_BASELINE
        print("[PASS] Reconciliation completed successfully")

        # Step 2: Create CompletedMeasurementRef (as voice_scorekeeper would store)
        completed_ref = CompletedMeasurementRef(
            calibration_session_id=updated_session2.session_id,
            measurement_id=completed_measurement.measurement_id,
            kind=completed_measurement.kind,
        )
        print("[PASS] CompletedMeasurementRef created: " + str(completed_ref.measurement_id[:8]))

        # Step 3: Use pure lookup helper with the ref (simulating _render_silence_baseline_step)
        # Note: At this point, active_measurement_id would be cleared by voice_scorekeeper
        # But we still have the reference!
        terminal_result_found = find_rendered_terminal_result(
            session=updated_session2,
            completed_ref=completed_ref,
            active_measurement_id=None,  # Cleared (as per bug scenario)
            active_measurement_kind=None,  # Cleared (as per bug scenario)
        )

        # Verify lookup succeeds via CompletedMeasurementRef
        assert terminal_result_found is not None
        assert terminal_result_found.capture.measurement_id == self.measurement_id
        assert terminal_result_found.capture.complete is True
        print("[PASS] Terminal result found via CompletedMeasurementRef")

        # Step 4: Resolver uses the found result -> COMPLETE (not FAILED)
        resolution_fixed = resolve_acoustic_ui_state(
            active_measurement_id=None,  # Cleared
            active_measurement_kind=None,  # Cleared
            terminal_result=terminal_result_found,  # Found via ref!
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id=self.session_id,
            reconciliation_error=None,
        )

        # Verify FIX: should return COMPLETE, not FAILED
        assert resolution_fixed.state == AcousticUiState.COMPLETE
        assert resolution_fixed.reason is None
        print("[PASS] FIX VERIFIED: Resolver correctly returns COMPLETE")


    def test_incomplete_measurement_renders_failed(self):
        """Verify FAILED state is returned for incomplete captures."""
        session = self.service.start_session(self.session_id)

        # Create incomplete measurement (frame_count=0)
        result = self._make_silence_baseline_result(
            measurement_id=self.measurement_id,
            session_id=self.session_id,
            complete=False,
            frame_count=0,
        )

        updated_session = self.service.consume_measurements(
            session=session,
            measurements=(result,),
        )

        found_result = updated_session.measurements[0] if updated_session.measurements else None
        assert found_result is not None

        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=found_result,
            snapshot=None,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id=self.session_id,
            reconciliation_error=None,
        )

        assert resolution.state == AcousticUiState.FAILED

    def test_measurement_with_warnings_renders_warning(self):
        """Verify WARNING state is returned for complete but problematic captures."""
        session = self.service.start_session(self.session_id)

        # Create measurement with warning codes
        capture = AcousticCaptureSummary(
            measurement_id=self.measurement_id,
            calibration_session_id=self.session_id,
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=144000,
            scalar_sample_count=144000,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=144000,
            invalid_frame_count=0,
            rms=-40.0,
            rms_dbfs=-40.0,
            peak=-20.0,
            peak_dbfs=-20.0,
            near_clipping_count=100,  # Issue
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=("clipping",),  # Has warning
            created_at=time.time(),
            skipped=False,
        )
        result = SilenceBaselineMetrics(
            capture=capture,
            median_rms=-40.0,
            median_dbfs=-40.0,
            p90_rms=-35.0,
            p90_dbfs=-35.0,
            p95_rms=-32.0,
            p95_dbfs=-32.0,
            mad_rms=2.0,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )

        updated_session = self.service.consume_measurements(
            session=session,
            measurements=(result,),
        )

        found_result = updated_session.measurements[0] if updated_session.measurements else None

        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=found_result,
            snapshot=None,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id=self.session_id,
            reconciliation_error=None,
        )

        assert resolution.state == AcousticUiState.WARNING

    def test_consume_measurements_idempotent(self):
        """Verify consuming the same measurement twice is safe."""
        session = self.service.start_session(self.session_id)

        result = self._make_silence_baseline_result(
            measurement_id=self.measurement_id,
            session_id=self.session_id,
        )

        # First consumption
        updated1 = self.service.consume_measurements(
            session=session,
            measurements=(result,),
        )
        assert len(updated1.measurements) == 1

        # Second consumption of same measurement
        updated2 = self.service.consume_measurements(
            session=updated1,
            measurements=(result,),
        )

        # Should be idempotent: no duplicate
        assert len(updated2.measurements) == 1
        assert updated2.measurements[0] == result

    def test_consume_measurements_rejects_different_session(self):
        """Verify measurements from different sessions are rejected."""
        session = self.service.start_session(self.session_id)
        different_session_id = str(uuid.uuid4())

        # Create result from different session
        result = self._make_silence_baseline_result(
            measurement_id=self.measurement_id,
            session_id=different_session_id,  # Different session
        )

        updated = self.service.consume_measurements(
            session=session,
            measurements=(result,),
        )

        # Should be ignored
        assert len(updated.measurements) == 0

    def test_resolver_processor_inactive_without_terminal_returns_failed(self):
        """Verify processor inactive state returns FAILED when no terminal result."""
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=12345,
            active=False,
            measurement_id=None,
            calibration_session_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        resolution = resolve_acoustic_ui_state(
            active_measurement_id=self.measurement_id,
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,  # No terminal result
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id=self.session_id,
            reconciliation_error=None,
        )

        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "active_measurement_missing_from_processor"

    def test_resolver_active_processor_returns_measuring(self):
        """Verify active processor with matching measurement_id returns MEASURING."""
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=12345,
            active=True,
            measurement_id=self.measurement_id,
            calibration_session_id=self.session_id,
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=72000,
            sample_count=72000,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )

        resolution = resolve_acoustic_ui_state(
            active_measurement_id=self.measurement_id,
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id=self.session_id,
            reconciliation_error=None,
        )

        assert resolution.state == AcousticUiState.MEASURING
        assert resolution.show_elapsed is True
