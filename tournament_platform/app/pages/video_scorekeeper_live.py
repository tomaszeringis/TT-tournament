"""
Live Camera component for Video Scorekeeper.

This module provides real-time video analysis for Phase 4.
"""

import streamlit as st

st.set_page_config(page_title="Video Scorekeeper Live - TT Platform", layout="wide")
from typing import Optional

from tournament_platform.services.video_scorekeeper import (
    CalibrationConfig,
    VideoScoreSuggestion,
    SuggestedWinner,
)


def check_webrtc_availability() -> bool:
    """Check if streamlit-webrtc is available."""
    try:
        from streamlit_webrtc import webrtc_streamer, WebRtcMode
        return True
    except ImportError:
        return False


def process_video_frame(frame):
    """
    Process a single video frame for real-time analysis.
    
    This is a placeholder for Phase 4 implementation.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return frame
    
    # Convert to numpy array
    img = frame.to_ndarray(format="bgr24")
    
    # Get calibration from session state
    calibration = st.session_state.get("video_calibration")
    
    # Detect ball in frame
    from tournament_platform.multimodal_ai.video_analysis import HeuristicVideoAnalyzer
    analyzer = HeuristicVideoAnalyzer()
    result = analyzer.detect_ball(img)
    
    if result:
        x, y, confidence = result
        # Draw ball position on frame
        cv2.circle(img, (int(x), int(y)), 10, (0, 255, 0), 2)
        cv2.putText(img, f"Ball: {confidence:.2f}", (int(x) + 15, int(y)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
    # Draw net line if calibration exists
    if calibration and calibration.net_line_y:
        cv2.line(img, (0, int(calibration.net_line_y)), (img.shape[1], int(calibration.net_line_y)),
                 (0, 0, 255), 2)
    
    return img


def render_live_camera() -> None:
    """Render live camera UI for real-time video analysis."""
    st.subheader("📹 Live Camera Analysis")
    st.caption("Real-time point detection from camera feed (Phase 4 - optional).")
    
    # Check if streamlit-webrtc is available
    if not check_webrtc_availability():
        st.info("Live camera support requires `streamlit-webrtc`. Install with: `pip install streamlit-webrtc`")
        st.info("For now, use the video upload feature above.")
        return
    
    if not st.session_state.get("opencv_available", False):
        st.warning("⚠️ OpenCV not installed. Live camera analysis is unavailable.")
        return
    
    # Live camera mode toggle
    live_mode = st.checkbox("Enable Live Camera", key="live_camera_enabled")
    
    if not live_mode:
        return
    
    st.warning("⚠️ Live camera mode is experimental. Point detection may be inaccurate.")
    
    # WebRTC streamer
    from streamlit_webrtc import webrtc_streamer, WebRtcMode
    
    webrtc_ctx = webrtc_streamer(
        key="video-scorekeeper-live",
        mode=WebRtcMode.SENDRECV,
        video_frame_callback=process_video_frame,
        media_stream_constraints={"video": True, "audio": False},
    )
    
    if webrtc_ctx and webrtc_ctx.video_receiver:
        # Process frames in real-time
        if st.button("Capture Point", key="capture_point_btn"):
            st.info("Point captured! Analyzing...")