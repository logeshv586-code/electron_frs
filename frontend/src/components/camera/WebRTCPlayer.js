import React, { useEffect, useRef, useState } from "react";
import { getAugmentUrl } from '../../utils/apiConfig';
import useAuthStore from '../../store/authStore';
import "./CameraStream.css";

const WebRTCPlayer = ({ collectionName, cameraIp, streamId, roomId, onError, onPlay }) => {
  const { token } = useAuthStore();
  const videoRef = useRef(null);
  const [isConnecting, setIsConnecting] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Support both old props (collectionName, cameraIp) and new props (streamId, roomId)
    let actualCollectionName = collectionName;
    let actualCameraIp = cameraIp;

    // If streamId and roomId are provided, extract collection and IP from roomId
    if (roomId && !collectionName) {
      const parts = roomId.split('_');
      if (parts.length >= 2) {
        actualCollectionName = parts[0];
        actualCameraIp = parts.slice(1).join('_'); // In case IP has underscores
      }
    }

    if (!actualCollectionName || !actualCameraIp) {
      setError("Missing collection name or camera IP");
      setIsConnecting(false);
      return;
    }

    const pc = new RTCPeerConnection();

    pc.ontrack = function (event) {
      if (videoRef.current) {
        videoRef.current.srcObject = event.streams[0];
        setIsConnecting(false);
        if (onPlay) onPlay();
      }
    };

    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.createOffer().then(offer => {
      return pc.setLocalDescription(offer);
    }).then(() => {
      return fetch(getAugmentUrl("api/webrtc/stream"), {
        method: 'POST',
        body: JSON.stringify({
          ...pc.localDescription,
          collection_name: actualCollectionName,
          camera_ip: actualCameraIp
        }),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });
    }).then(res => res.json())
      .then(answer => {
        if (!answer.success) {
          throw new Error(answer.error || 'Failed to establish WebRTC connection');
        }
        return pc.setRemoteDescription(answer.data);
      })
      .catch(error => {
        console.error('WebRTC error:', error);
        setError(error.message);
        setIsConnecting(false);
        if (onError) onError(error.message);
      });

    return () => {
      pc.close();
    };
  }, [collectionName, cameraIp, streamId, roomId, onError, onPlay]);

  return (
    <div className="camera-stream-container">
      {error ? (
        <div className="error-message">
          {error}
          <button className="retry-button" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      ) : isConnecting ? (
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
          <div>Connecting to stream...</div>
        </div>
      ) : (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          controls
          style={{ width: '100%', height: '100%' }}
          onError={(e) => {
            console.error('Video error:', e);
            setError('Video playback error');
            if (onError) onError('Video playback error');
          }}
        />
      )}
    </div>
  );
};

export default WebRTCPlayer;