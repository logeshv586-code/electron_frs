import React, { useEffect, useState } from 'react';
import { ipcRenderer } from '../../services/electronService';
import PropTypes from 'prop-types';
import './CameraStream.css';

const VLCPlayer = ({ streamUrl, onError, onPlay }) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState(null);
  const [isConnecting, setIsConnecting] = useState(true);

  useEffect(() => {
    if (!streamUrl) {
      const errorMsg = "Missing stream URL";
      setError(errorMsg);
      setIsConnecting(false);
      if (onError) onError(errorMsg);
      return;
    }

    // Request the main process to start VLC with the RTSP stream
    ipcRenderer.invoke('start-vlc-stream', streamUrl)
      .then((result) => {
        if (result.success) {
          setIsPlaying(true);
          setIsConnecting(false);
          if (onPlay) onPlay();
        } else {
          throw new Error(result.error || 'Failed to start VLC stream');
        }
      })
      .catch((err) => {
        const errorMsg = `Error starting VLC stream: ${err.message}`;
        console.error(errorMsg);
        setError(errorMsg);
        setIsConnecting(false);
        if (onError) onError(errorMsg);
      });

    // Cleanup function to stop VLC when component unmounts
    return () => {
      ipcRenderer.invoke('stop-vlc-stream')
        .catch(err => console.error('Error stopping VLC stream:', err));
    };
  }, [streamUrl, onError, onPlay]);

  return (
    <div className="camera-stream-container">
      {error ? (
        <div className="error-message">{error}</div>
      ) : isConnecting ? (
        <div className="connecting-message">
          <div className="spinner"></div>
          <span>Starting VLC stream...</span>
        </div>
      ) : (
        <div className="vlc-stream-active">
          <span>VLC stream is active</span>
          <button
            onClick={() => {
              ipcRenderer.invoke('stop-vlc-stream')
                .then(() => setIsPlaying(false))
                .catch(err => console.error('Error stopping stream:', err));
            }}
            className="stop-stream-button"
          >
            Stop Stream
          </button>
        </div>
      )}
    </div>
  );
};

VLCPlayer.propTypes = {
  streamUrl: PropTypes.string.isRequired,
  onError: PropTypes.func,
  onPlay: PropTypes.func
};

export default VLCPlayer;