"""
Voice Calibration — Pure measurement domain functions.

Import-safe: no Streamlit, WebRTC, ASR, session state, or scoring imports.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from tournament_platform.app.services.voice_audio import (
    SAMPLE_FORMAT_FLOAT32,
    SAMPLE_FORMAT_INT16,
)
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticRecommendationCode,
    CalibrationMeasurementKind,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
)


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #
NEAR_CLIPPING_THRESHOLD = 0.98
HARD_CLIPPING_THRESHOLD = 0.999
SPEECH_CONTAMINATION_MIN_DURATION_MS = 150.0
SPEECH_CONTAMINATION_MIN_FRAMES = 3
SPEECH_START_WARNING_THRESHOLD_MS = 50.0
TRAILING_SILENCE_WARNING_THRESHOLD_MS = 2000.0
MINIMUM_THRESHOLD_DBFS = -60.0
MARGIN_DB = 10.0

# dBFS uses a finite floor of -120 dBFS (RMS ≈ 1e-6) so that zero-signal
# captures produce JSON-safe, UI-friendly values instead of -inf.
DBFS_EPSILON = 1e-6
DBFS_FLOOR_DBFS = 20.0 * math.log10(DBFS_EPSILON)  # -120.0 dBFS


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class InvalidFrameFormat(Exception):
    """Raised when an audio frame has an unsupported sample format."""


# --------------------------------------------------------------------------- #
# PCM Normalization                                                           #
# --------------------------------------------------------------------------- #
def normalize_pcm(frame_bytes: bytes, sample_format: str, channel_count: int) -> np.ndarray:
    if sample_format == SAMPLE_FORMAT_FLOAT32:
        samples = np.frombuffer(frame_bytes, dtype=np.float32)
        if samples.size > 0 and (np.any(np.isnan(samples)) or np.any(np.isinf(samples))):
            raise InvalidFrameFormat("Float PCM contains NaN or infinity")
    elif sample_format == SAMPLE_FORMAT_INT16:
        samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float64) / 32768.0
    elif sample_format == "int32":
        samples = np.frombuffer(frame_bytes, dtype=np.int32).astype(np.float64) / 2147483648.0
    else:
        raise InvalidFrameFormat(f"Unsupported sample format: {sample_format}")

    if channel_count > 1:
        usable = (samples.size // channel_count) * channel_count
        if usable != samples.size:
            samples = samples[:usable]
        samples = samples.reshape(-1, channel_count)

    return samples


# --------------------------------------------------------------------------- #
# Acoustic Accumulator                                                         #
# --------------------------------------------------------------------------- #
@dataclass
class AcousticAccumulator:
    measurement_id: str
    calibration_session_id: str
    kind: CalibrationMeasurementKind
    sample_rate_hz: int
    channel_count: int
    target_sample_frame_count: int
    """Target number of sample frames (frames, not scalar samples).

    Duration = target_sample_frame_count / sample_rate_hz.
    """
    armed_at: float
    timeout_ms: float = 10000.0
    frame_rms_values: List[float] = field(default_factory=list)
    _sum_of_squares: float = 0.0
    _peak: float = 0.0
    _frame_count: int = 0
    _scalar_sample_count: int = 0
    _sample_frame_count: int = 0
    _near_clipping_count: int = 0
    _hard_clipping_count: int = 0
    _speech_frame_count: int = 0
    _is_speech_flags: List[bool] = field(default_factory=list)
    _first_speech_timestamp: Optional[float] = None
    _last_speech_timestamp: Optional[float] = None
    _last_timestamp: Optional[float] = None
    _sample_rate_changed: bool = False
    _first_sample_rate: Optional[int] = None
    _invalid_frame_count: int = 0

    def observe(
        self,
        normalized_samples: np.ndarray,
        is_speech: bool,
        timestamp: float,
    ) -> None:
        if normalized_samples.size == 0:
            self._invalid_frame_count += 1
            return

        if self._first_sample_rate is None:
            self._first_sample_rate = self.sample_rate_hz
        elif self._first_sample_rate != self.sample_rate_hz:
            self._sample_rate_changed = True

        channel_power = np.mean(normalized_samples ** 2, axis=0)
        combined_rms = float(np.sqrt(np.mean(channel_power)))
        peak = float(np.max(np.abs(normalized_samples)))

        self._sum_of_squares += float(np.sum(normalized_samples ** 2))
        self._peak = max(self._peak, peak)
        self.frame_rms_values.append(combined_rms)
        self._frame_count += 1
        self._scalar_sample_count += int(normalized_samples.size) // max(self.channel_count, 1)
        self._sample_frame_count = self._scalar_sample_count

        self._near_clipping_count += int(np.sum(np.abs(normalized_samples) >= NEAR_CLIPPING_THRESHOLD))
        self._hard_clipping_count += int(np.sum(np.abs(normalized_samples) >= HARD_CLIPPING_THRESHOLD))

        self._is_speech_flags.append(is_speech)

        if is_speech:
            self._speech_frame_count += 1
            if self._first_speech_timestamp is None:
                self._first_speech_timestamp = timestamp
            self._last_speech_timestamp = timestamp

        self._last_timestamp = timestamp

    @property
    def is_complete(self) -> bool:
        return self._sample_frame_count >= self.target_sample_frame_count

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.armed_at) * 1000.0 > self.timeout_ms

    def finalize(self) -> AcousticCaptureSummary:
        total_samples = self._scalar_sample_count * self.channel_count
        rms = math.sqrt(self._sum_of_squares / total_samples) if total_samples > 0 else None
        rms_dbfs = 20 * math.log10(max(rms, DBFS_EPSILON)) if rms is not None else None
        peak_dbfs = 20 * math.log10(max(self._peak, DBFS_EPSILON)) if self._peak > 0 else None

        duration_ms = self._sample_frame_count / self.sample_rate_hz * 1000.0 if self.sample_rate_hz else 0.0
        speech_duration_ms = self._speech_frame_count / self.sample_rate_hz * 1000.0

        warning_codes: List[str] = []
        if self._sample_rate_changed:
            warning_codes.append(AcousticRecommendationCode.SAMPLE_RATE_CHANGED)

        return AcousticCaptureSummary(
            measurement_id=self.measurement_id,
            calibration_session_id=self.calibration_session_id,
            kind=self.kind,
            sample_rate_hz=self.sample_rate_hz,
            channel_count=self.channel_count,
            frame_count=self._frame_count,
            scalar_sample_count=self._scalar_sample_count,
            target_duration_ms=self.target_sample_frame_count / self.sample_rate_hz * 1000.0 if self.sample_rate_hz else 0.0,
            captured_duration_ms=duration_ms,
            valid_frame_count=self._frame_count,
            invalid_frame_count=self._invalid_frame_count,
            rms=rms,
            rms_dbfs=rms_dbfs,
            peak=self._peak if self._peak > 0 else None,
            peak_dbfs=peak_dbfs if self._peak > 0 else None,
            near_clipping_count=self._near_clipping_count,
            hard_clipping_count=self._hard_clipping_count,
            speech_frame_count=self._speech_frame_count,
            speech_duration_ms=speech_duration_ms,
            complete=self.is_complete,
            warning_codes=tuple(warning_codes),
            created_at=self.armed_at,
        )


# --------------------------------------------------------------------------- #
# Silence Baseline Metrics                                                    #
# --------------------------------------------------------------------------- #
def compute_silence_baseline_metrics(
    accumulator: AcousticAccumulator,
) -> SilenceBaselineMetrics:
    capture = accumulator.finalize()
    frame_rms_values = np.array(accumulator.frame_rms_values)

    if len(frame_rms_values) == 0:
        return SilenceBaselineMetrics(
            capture=capture,
            median_rms=None,
            median_dbfs=None,
            p90_rms=None,
            p90_dbfs=None,
            p95_rms=None,
            p95_dbfs=None,
            mad_rms=None,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=accumulator._speech_frame_count,
            speech_duration_ms=accumulator._speech_frame_count / accumulator.sample_rate_hz * 1000.0,
        )

    median_rms = float(np.median(frame_rms_values))
    median_dbfs = 20 * math.log10(max(median_rms, DBFS_EPSILON))

    p90_rms = float(np.percentile(frame_rms_values, 90))
    p90_dbfs = 20 * math.log10(max(p90_rms, DBFS_EPSILON))

    p95_rms = float(np.percentile(frame_rms_values, 95))
    p95_dbfs = 20 * math.log10(max(p95_rms, DBFS_EPSILON))

    mad_rms = float(np.median(np.abs(frame_rms_values - median_rms)))

    speech_duration_ms = accumulator._speech_frame_count / accumulator.sample_rate_hz * 1000.0
    contaminated = (
        speech_duration_ms >= SPEECH_CONTAMINATION_MIN_DURATION_MS
        or accumulator._speech_frame_count >= SPEECH_CONTAMINATION_MIN_FRAMES
    )

    return SilenceBaselineMetrics(
        capture=capture,
        median_rms=median_rms,
        median_dbfs=median_dbfs,
        p90_rms=p90_rms,
        p90_dbfs=p90_dbfs,
        p95_rms=p95_rms,
        p95_dbfs=p95_dbfs,
        mad_rms=mad_rms,
        transient_count=0,
        contaminated_by_speech=contaminated,
        speech_frame_count=accumulator._speech_frame_count,
        speech_duration_ms=speech_duration_ms,
    )


# --------------------------------------------------------------------------- #
# Speech Level Metrics                                                        #
# --------------------------------------------------------------------------- #
def compute_speech_level_metrics(
    accumulator: AcousticAccumulator,
    silence_baseline: SilenceBaselineMetrics | None = None,
) -> SpeechLevelMetrics:
    capture = accumulator.finalize()

    if capture.skipped:
        return SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=None,
            trailing_silence_ms=None,
            speech_rms=None,
            speech_rms_dbfs=None,
            speech_to_background_difference_db=None,
        )

    frame_rms_values = np.array(accumulator.frame_rms_values)
    is_speech_flags = np.array(accumulator._is_speech_flags)

    if len(frame_rms_values) == 0 or accumulator._speech_frame_count == 0:
        return SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=None,
            trailing_silence_ms=None,
            speech_rms=None,
            speech_rms_dbfs=None,
            speech_to_background_difference_db=None,
        )

    speech_rms_values = frame_rms_values[is_speech_flags]
    if len(speech_rms_values) == 0:
        return SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=None,
            trailing_silence_ms=None,
            speech_rms=None,
            speech_rms_dbfs=None,
            speech_to_background_difference_db=None,
        )

    speech_rms = float(np.mean(speech_rms_values))
    speech_rms_dbfs = 20 * math.log10(max(speech_rms, DBFS_EPSILON))

    speech_start_offset_ms = (
        (accumulator._first_speech_timestamp - accumulator.armed_at) * 1000.0
        if accumulator._first_speech_timestamp is not None
        else None
    )

    trailing_silence_ms = (
        (accumulator._last_timestamp - accumulator._last_speech_timestamp) * 1000.0
        if accumulator._last_speech_timestamp is not None
        else None
    )

    speech_to_background_difference_db = None
    if silence_baseline is not None and silence_baseline.median_dbfs is not None:
        speech_to_background_difference_db = speech_rms_dbfs - silence_baseline.median_dbfs

    return SpeechLevelMetrics(
        capture=capture,
        speech_start_offset_ms=speech_start_offset_ms,
        trailing_silence_ms=trailing_silence_ms,
        speech_rms=speech_rms,
        speech_rms_dbfs=speech_rms_dbfs,
        speech_to_background_difference_db=speech_to_background_difference_db,
    )
