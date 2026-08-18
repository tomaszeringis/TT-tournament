"""
Live Camera component for Video Scorekeeper.

This module provides real-time video analysis for Phase 4.
"""

import streamlit as st

from tournament_platform.app.design_system import apply_global_styles

st.set_page_config(page_title="LIT_IT Video Scorekeeper Live", layout="wide")
apply_global_styles()

from typing import Any, Optional

from tournament_platform.services.video_scorekeeper import (
    CalibrationConfig,
    VideoScoreSuggestion,
    SuggestedWinner,
)
from tournament_platform.app.services.vision_worker import VisionWorker, VisionWorkerHealth
from tournament_platform.app.services.vision_calibration import (
    CalibrationState,
    compute_homography,
    validate_calibration,
)
from tournament_platform.app.services.vision_candidate import PointCandidateGenerator
from tournament_platform.app.services.vision_events import PointCandidate


def check_webrtc_availability() -> bool:
    """Check if streamlit-webrtc is available."""
    try:
        from streamlit_webrtc import webrtc_streamer, WebRtcMode
        return True
    except ImportError:
        return False


def _make_processing_callback(match_id: int):
    """Create a processing callback bound to a specific match_id."""
    generator = PointCandidateGenerator(match_id=match_id)

    def callback(frame: Any) -> Optional[list[Any]]:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None

        img = frame.to_ndarray(format="bgr24")
        calibration_state: Optional[CalibrationState] = st.session_state.get("vision_calibration_state")
        legacy_calibration = st.session_state.get("video_calibration")

        if calibration_state is None or not calibration_state.valid:
            return None

        from tournament_platform.multimodal_ai.video_analysis import HeuristicVideoAnalyzer
        analyzer = HeuristicVideoAnalyzer()
        result = analyzer.detect_ball(img)

        if result:
            x, y, confidence = result
            cv2.circle(img, (int(x), int(y)), 10, (0, 255, 0), 2)
            cv2.putText(img, f"Ball: {confidence:.2f}", (int(x) + 15, int(y)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        if legacy_calibration and legacy_calibration.net_line_y:
            cv2.line(img, (0, int(legacy_calibration.net_line_y)), (img.shape[1], int(legacy_calibration.net_line_y)),
                     (0, 0, 255), 2)

        from tournament_platform.app.services.vision_backends import HeuristicBallDetector, BallDetector
        detector: BallDetector = HeuristicBallDetector()
        observation = detector.detect(img, calibration=calibration_state)
        if observation is None:
            return None

        gen_result = generator.process_observation(observation, calibration=calibration_state)
        if gen_result.generated and gen_result.candidate is not None:
            return [gen_result.candidate]
        return None

    return callback


def _get_or_create_worker() -> Optional[VisionWorker]:
    """Return the session-scoped VisionWorker, creating it if necessary."""
    if not st.session_state.get("opencv_available", False):
        return None

    match_id = st.session_state.get("video_selected_match_id") or 0

    worker: Optional[VisionWorker] = st.session_state.get("vision_worker")
    if worker is None:
        worker = VisionWorker(
            processing_callback=_make_processing_callback(match_id=match_id),
            max_queue_size=2,
            name="video-scorekeeper-live",
        )
        st.session_state.vision_worker = worker

    health = worker.get_health()
    if not health.alive:
        worker.start()

    return worker


def _stop_worker() -> None:
    """Stop and remove the session-scoped VisionWorker."""
    worker: Optional[VisionWorker] = st.session_state.get("vision_worker")
    if worker is not None:
        worker.stop(timeout=2.0)
        st.session_state.vision_worker = None


def _drain_worker_events(worker: VisionWorker) -> None:
    """Drain worker events and update session state.

    This runs in the main Streamlit thread only.
    """
    events = worker.drain_events()
    for event in events:
        if isinstance(event, PointCandidate):
            existing = st.session_state.get("vision_active_candidate")
            if existing is None or existing.rally_id != event.rally_id:
                st.session_state.vision_active_candidate = event


def render_live_camera() -> None:
    """Render live camera UI for real-time video analysis."""
    st.subheader("📹 Live Camera Analysis")
    st.caption("Real-time point detection from camera feed (Phase 2 - infrastructure).")

    if not check_webrtc_availability():
        st.info("Live camera support requires `streamlit-webrtc`. Install with: `pip install streamlit-webrtc`")
        st.info("For now, use the video upload feature above.")
        return

    if not st.session_state.get("opencv_available", False):
        st.warning("⚠️ OpenCV not installed. Live camera analysis is unavailable.")
        return

    live_mode = st.checkbox("Enable Live Camera", key="live_camera_enabled")

    if live_mode:
        worker = _get_or_create_worker()
        if worker is None:
            st.warning("⚠️ VisionWorker could not be initialized.")
            return
        _drain_worker_events(worker)
    else:
        _stop_worker()
        return

    st.warning("⚠️ Live camera mode is experimental. Point detection may be inaccurate.")

    render_calibration_ui()

    health: VisionWorkerHealth = worker.get_health()

    if not health.healthy and health.error:
        st.error(f"Vision worker error: {health.error}")

    from streamlit_webrtc import webrtc_streamer, WebRtcMode

    webrtc_ctx = webrtc_streamer(
        key="video-scorekeeper-live",
        mode=WebRtcMode.SENDRECV,
        video_frame_callback=process_video_frame,
        media_stream_constraints={"video": True, "audio": False},
    )

    if webrtc_ctx and webrtc_ctx.video_receiver:
        if st.button("Capture Point", key="capture_point_btn"):
            st.info("Point captured! Analyzing...")

    with st.expander("Vision Worker Diagnostics", expanded=False):
        st.json({
            "alive": health.alive,
            "healthy": health.healthy,
            "error": health.error,
            "frames_received": health.frames_received,
            "frames_processed": health.frames_processed,
            "frames_dropped": health.frames_dropped,
            "inference_latency_ms": round(health.inference_latency_ms, 2),
            "started_at": health.started_at,
            "last_frame_at": health.last_frame_at,
        })


def render_calibration_ui() -> None:
    """Render table calibration UI using coordinate inputs."""
    st.subheader("📐 Table Calibration")
    st.caption("Enter the 4 table corners in camera pixel coordinates.")

    state: Optional[CalibrationState] = st.session_state.get("vision_calibration_state")
    if state is None:
        state = CalibrationState()
        st.session_state.vision_calibration_state = state

    uploaded_file = st.file_uploader("Upload a camera snapshot for calibration", type=["png", "jpg", "jpeg"])
    preview_image = None
    if uploaded_file is not None:
        import cv2
        import numpy as np
        file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
        preview_image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    cols = st.columns(2)
    corners = []
    labels = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
    for idx, label in enumerate(labels):
        with cols[idx % 2]:
            st.markdown(f"**{label}**")
            x = st.number_input(f"x{idx+1}", value=100.0 + idx * 140.0, key=f"cal_x{idx+1}")
            y = st.number_input(f"y{idx+1}", value=100.0 + (idx // 2) * 180.0, key=f"cal_y{idx+1}")
            corners.append((float(x), float(y)))

    if st.button("Apply Calibration", key="apply_calibration"):
        reason = validate_calibration(corners)
        if reason:
            state.mark_invalid(reason)
            st.error(f"Invalid calibration: {reason}")
        else:
            homography = compute_homography(corners)
            if homography is None:
                state.mark_invalid("Failed to compute homography")
                st.error("Failed to compute homography")
            else:
                state.mark_valid(homography, corners)
                st.session_state.video_calibration = CalibrationConfig(
                    table_corners=corners,
                    net_line_y=None,
                    player_a_side="top",
                    player_b_side="bottom",
                    frame_width=int(preview_image.shape[1]) if preview_image is not None else 640,
                    frame_height=int(preview_image.shape[0]) if preview_image is not None else 480,
                )
                st.success("Calibration applied")

    if state.valid and preview_image is not None:
        import cv2
        import numpy as np
        preview = preview_image.copy()
        for idx, (x, y) in enumerate(corners):
            cv2.circle(preview, (int(x), int(y)), 8, (0, 255, 0), -1)
            cv2.putText(preview, str(idx + 1), (int(x) + 12, int(y) - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        st.image(preview, channels="BGR", caption="Calibration preview")


def process_video_frame(frame):
    """
    Enqueue a frame for background processing.

    This callback is invoked from the WebRTC thread. It must return
    immediately and must not perform blocking inference.
    """
    worker: Optional[VisionWorker] = st.session_state.get("vision_worker")
    if worker is not None:
        worker.enqueue_frame(frame)

    return frame
