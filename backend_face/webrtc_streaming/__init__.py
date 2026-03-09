"""
WebRTC streaming module for RTSP camera streams
"""

from .webrtc_service import get_webrtc_manager, WebRTCStreamManager
from .routes import router

__all__ = ['get_webrtc_manager', 'WebRTCStreamManager', 'router']
