import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { getAugmentUrl } from '../../utils/apiConfig';
import useAuthStore from '../../store/authStore';

const RTSPWebRTCPlayer = ({ rtspUrl, onError, onPlay }) => {
  const { token } = useAuthStore();
  const videoRef = useRef(null);
  const peerConnectionRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const maxRetries = 3;

  const handleError = (error) => {
    console.error('RTSPWebRTC error:', error);
    if (onError) onError(error);
  };

  const setupWebRTCConnection = async () => {
    try {
      // Create a new RTCPeerConnection
      const configuration = {
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' }
        ]
      };
      
      const pc = new RTCPeerConnection(configuration);
      peerConnectionRef.current = pc;

      // Set up video element when track is received
      pc.ontrack = (event) => {
        if (videoRef.current) {
          videoRef.current.srcObject = event.streams[0];
          videoRef.current.play()
            .then(() => {
              setIsPlaying(true);
              if (onPlay) onPlay();
            })
            .catch((error) => handleError('Failed to play video: ' + error.message));
        }
      };

      // Create and send offer to the server
      const offer = await pc.createOffer({
        offerToReceiveVideo: true,
        offerToReceiveAudio: true
      });
      await pc.setLocalDescription(offer);

      // Send the offer to the backend and get answer
      const response = await fetch(getAugmentUrl('api/webrtc/connect'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          rtspUrl: rtspUrl,
          offer: pc.localDescription
        })
      });

      if (!response.ok) {
        throw new Error('Failed to connect to RTSP stream');
      }

      const { answer } = await response.json();
      await pc.setRemoteDescription(new RTCSessionDescription(answer));

    } catch (error) {
      if (retryCount < maxRetries) {
        setRetryCount(prev => prev + 1);
        setTimeout(setupWebRTCConnection, 2000);
      } else {
        handleError(error);
      }
    }
  };

  useEffect(() => {
    if (rtspUrl) {
      setupWebRTCConnection();
    }

    return () => {
      if (peerConnectionRef.current) {
        peerConnectionRef.current.close();
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };
  }, [rtspUrl]);

  return (
    <div className="rtsp-webrtc-player">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        style={{ width: '100%', height: '100%' }}
      />
      {!isPlaying && (
        <div className="loading-overlay">
          <div className="loading-spinner" />
          <div className="loading-text">Connecting to stream...</div>
        </div>
      )}
    </div>
  );
};

RTSPWebRTCPlayer.propTypes = {
  rtspUrl: PropTypes.string.isRequired,
  onError: PropTypes.func,
  onPlay: PropTypes.func
};

export default RTSPWebRTCPlayer;
