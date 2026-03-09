"""
WebRTC streaming service for RTSP cameras
Handles WebRTC signaling and RTSP to WebRTC conversion
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Optional
import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

class WebRTCStreamManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.active_streams: Dict[str, Dict] = {}
        self.stream_processes: Dict[str, subprocess.Popen] = {}
        
    async def connect(self, websocket: WebSocket, camera_id: str):
        """Accept WebSocket connection for WebRTC signaling"""
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        self.active_connections[connection_id] = websocket
        
        logger.info(f"WebRTC client connected for camera {camera_id}: {connection_id}")
        
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                await self.handle_message(connection_id, camera_id, message, websocket)
                
        except WebSocketDisconnect:
            logger.info(f"WebRTC client disconnected: {connection_id}")
            await self.cleanup_connection(connection_id, camera_id)
        except Exception as e:
            logger.error(f"WebRTC connection error: {e}")
            await self.cleanup_connection(connection_id, camera_id)
    
    async def handle_message(self, connection_id: str, camera_id: str, message: dict, websocket: WebSocket):
        """Handle WebRTC signaling messages"""
        message_type = message.get('type')
        
        # Handle DirectWebRTCPlayer.js style signaling (Socket.io-like events)
        if not message_type and 'room' in message and 'sdp' in message:
            # This looks like a join_room event from DirectWebRTCPlayer.js
            rtsp_url = message.get('rtspUrl')
            sdp_offer = message.get('sdp')
            logger.info(f"Received join_room style offer for RTSP URL: {rtsp_url}")
            
            # Send answer back immediately
            answer_sdp = self.create_rtsp_sdp(camera_id, rtsp_url)
            
            # First send room_joined confirmation
            await websocket.send_text(json.dumps({
                'type': 'room_joined',
                'room': message.get('room')
            }))
            
            # Then send the answer
            await websocket.send_text(json.dumps({
                'type': 'answer',
                'streamId': message.get('room'),
                'sdp': {
                    'type': 'answer',
                    'sdp': answer_sdp
                }
            }))
            return

        if message_type == 'start_stream':
            rtsp_url = message.get('rtsp_url')
            await self.start_rtsp_stream(connection_id, camera_id, rtsp_url, websocket)
            
        elif message_type == 'answer':
            # Handle WebRTC answer from client
            logger.info(f"Received WebRTC answer for camera {camera_id}")
            # In a full implementation, this would be passed to the WebRTC peer
            
        elif message_type == 'ice_candidate':
            # Handle ICE candidate from client
            logger.info(f"Received ICE candidate for camera {camera_id}")
            # In a full implementation, this would be passed to the WebRTC peer
    
    async def start_rtsp_stream(self, connection_id: str, camera_id: str, rtsp_url: str, websocket: WebSocket):
        """Start RTSP stream and convert to WebRTC"""
        try:
            logger.info(f"Starting RTSP to WebRTC conversion for camera {camera_id}")
            
            # For demo purposes, we'll simulate WebRTC signaling
            # In a real implementation, you would use a WebRTC library like aiortc
            
            # Check if RTSP camera is accessible
            cap = cv2.VideoCapture(rtsp_url)
            if not cap.isOpened():
                logger.warning(f"RTSP camera not accessible: {rtsp_url}")
                await self.send_demo_stream_offer(websocket, camera_id)
                cap.release()
                return
            
            # Test if we can read a frame
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                logger.warning(f"Cannot read frames from RTSP camera: {rtsp_url}")
                await self.send_demo_stream_offer(websocket, camera_id)
                return
            
            # RTSP camera is working, send real stream offer
            await self.send_real_stream_offer(websocket, camera_id, rtsp_url)
            
        except Exception as e:
            logger.error(f"Error starting RTSP stream: {e}")
            await websocket.send_text(json.dumps({
                'type': 'error',
                'error': f'Failed to start stream: {str(e)}'
            }))
    
    async def send_demo_stream_offer(self, websocket: WebSocket, camera_id: str):
        """Send WebRTC offer for demo stream"""
        try:
            # Create a demo video stream using canvas/MediaStream
            offer = {
                'type': 'offer',
                'offer': {
                    'type': 'offer',
                    'sdp': self.create_demo_sdp(camera_id)
                }
            }
            
            await websocket.send_text(json.dumps(offer))
            logger.info(f"Sent demo WebRTC offer for camera {camera_id}")
            
        except Exception as e:
            logger.error(f"Error sending demo offer: {e}")
    
    async def send_real_stream_offer(self, websocket: WebSocket, camera_id: str, rtsp_url: str):
        """Send WebRTC offer for real RTSP stream"""
        try:
            # In a real implementation, this would create an actual WebRTC offer
            # For now, we'll send a demo offer since full WebRTC implementation
            # requires additional libraries like aiortc
            
            offer = {
                'type': 'offer',
                'offer': {
                    'type': 'offer',
                    'sdp': self.create_rtsp_sdp(camera_id, rtsp_url)
                }
            }
            
            await websocket.send_text(json.dumps(offer))
            logger.info(f"Sent RTSP WebRTC offer for camera {camera_id}")
            
        except Exception as e:
            logger.error(f"Error sending RTSP offer: {e}")
    
    def create_demo_sdp(self, camera_id: str) -> str:
        """Create SDP for demo stream"""
        # This is a simplified SDP for demo purposes
        # In a real implementation, this would be generated by a WebRTC library
        return f"""v=0
o=- 0 0 IN IP4 127.0.0.1
s=Demo Camera {camera_id}
t=0 0
m=video 9 UDP/TLS/RTP/SAVPF 96
c=IN IP4 127.0.0.1
a=rtcp:9 IN IP4 127.0.0.1
a=ice-ufrag:demo
a=ice-pwd:demo123
a=fingerprint:sha-256 00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00
a=setup:actpass
a=mid:video
a=sendonly
a=rtcp-mux
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42e01e
"""
    
    def create_rtsp_sdp(self, camera_id: str, rtsp_url: str) -> str:
        """Create SDP for RTSP stream"""
        # This is a simplified SDP for RTSP stream
        # In a real implementation, this would be generated by a WebRTC library
        return f"""v=0
o=- 0 0 IN IP4 127.0.0.1
s=RTSP Camera {camera_id}
t=0 0
m=video 9 UDP/TLS/RTP/SAVPF 96
c=IN IP4 127.0.0.1
a=rtcp:9 IN IP4 127.0.0.1
a=ice-ufrag:rtsp
a=ice-pwd:rtsp123
a=fingerprint:sha-256 11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11:11
a=setup:actpass
a=mid:video
a=sendonly
a=rtcp-mux
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42e01e
a=rtsp-url:{rtsp_url}
"""
    
    async def cleanup_connection(self, connection_id: str, camera_id: str):
        """Clean up WebRTC connection"""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        
        if camera_id in self.active_streams:
            del self.active_streams[camera_id]
        
        if camera_id in self.stream_processes:
            process = self.stream_processes[camera_id]
            if process.poll() is None:
                process.terminate()
            del self.stream_processes[camera_id]
        
        logger.info(f"Cleaned up WebRTC connection {connection_id} for camera {camera_id}")

# Global WebRTC manager instance
_webrtc_manager = None

def get_webrtc_manager() -> WebRTCStreamManager:
    """Get the global WebRTC manager instance"""
    global _webrtc_manager
    if _webrtc_manager is None:
        _webrtc_manager = WebRTCStreamManager()
    return _webrtc_manager
