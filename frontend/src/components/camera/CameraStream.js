import React, { useState, useEffect, useCallback } from 'react';
import WebRTCPlayer from './WebRTCPlayer';
import './CameraStream.css';

const CameraStream = ({ streamUrl }) => {
  const [collectionName, setCollectionName] = useState(null);
  const [cameraIp, setCameraIp] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // Extract collection and camera IP from the stream URL
  useEffect(() => {
    if (!streamUrl) {
      setError("No stream URL provided");
      setIsLoading(false);
      return;
    }

    try {
      // Parse the stream URL to extract collection and camera IP
      const urlParts = streamUrl.split('/');

      // Format is typically: http://192.168.1.209:8005/collection_name_ip/stream
      const collectionAndIp = urlParts[urlParts.length - 2];

      // Split by underscore to separate collection name and IP
      // The last parts are the IP (which may contain underscores if it was encoded)
      const parts = collectionAndIp.split('_');

      // Assume the last 4 parts are the IP (e.g., 192_168_1_100)
      const ipParts = parts.slice(-4);
      const ip = ipParts.join('.');

      // The rest is the collection name
      const collection = parts.slice(0, -4).join('_');

      console.log(`Parsed stream URL: collection=${collection}, ip=${ip}`);

      setCollectionName(collection);
      setCameraIp(ip);
      setIsLoading(false);
    } catch (err) {
      console.error("Error parsing stream URL:", err);
      setError("Failed to parse stream URL");
      setIsLoading(false);
    }
  }, [streamUrl]);

  // Handle retry
  const handleRetry = useCallback(() => {
    setError(null);
    setIsLoading(true);
    setCollectionName(null);
    setCameraIp(null);

    // Re-trigger the effect by updating the dependency
    window.location.reload();
  }, []);

  return (
    <div className="camera-stream-container">
      {error ? (
        <div className="error-message">
          {error}
          <button className="retry-button" onClick={handleRetry}>
            Retry
          </button>
        </div>
      ) : isLoading ? (
        <div className="loading-message">
          <div className="spinner"></div>
          <span>Connecting to camera...</span>
        </div>
      ) : collectionName && cameraIp ? (
        <WebRTCPlayer
          collectionName={collectionName}
          cameraIp={cameraIp}
          onError={(err) => setError(err)}
        />
      ) : (
        <div className="error-message">
          No stream available
          <button className="retry-button" onClick={handleRetry}>
            Retry
          </button>
        </div>
      )}
    </div>
  );
};

export default React.memo(CameraStream);
