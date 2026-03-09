import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import useAuthStore from '../../store/authStore';
import './MJPEGPlayer.css';

import { API_BASE_URL } from '../../utils/apiConfig';

const MJPEGPlayer = ({ camera, onPlay, onError }) => {
  const [streamUrl, setStreamUrl] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [streamId, setStreamId] = useState(null);
  const imgRef = useRef(null);
  const retryTimeoutRef = useRef(null);
  const [retryCount, setRetryCount] = useState(0);
  const maxRetries = 3;
  const isStartingRef = useRef(false);
  const { token } = useAuthStore();

  // Generate stream ID from camera info
  const generateStreamId = (camera) => {
    if (camera.ip) {
      // Try to extract collection name from camera name or use a default
      let collectionName = 'default';

      if (camera.name && camera.name.includes('(')) {
        // Extract collection name from camera name format "CollectionName (IP)"
        collectionName = camera.name.split('(')[0].trim();
      } else if (camera.collectionId) {
        collectionName = camera.collectionId;
      }

      return `${collectionName}_${camera.ip}`;
    }
    return `camera_${camera.id}_${Date.now()}`;
  };

  // Start MJPEG stream
  const startStream = async () => {
    // Prevent multiple simultaneous requests
    if (isStartingRef.current) {
      console.log(`Stream already starting, skipping...`);
      return;
    }

    const newStreamId = generateStreamId(camera);

    // Check if stream already exists and is working
    if (streamId === newStreamId && streamUrl && !hasError) {
      console.log(`Stream ${newStreamId} already exists and working, reusing...`);
      setIsLoading(false);
      return;
    }

    try {
      isStartingRef.current = true;
      setIsLoading(true);
      setHasError(false);
      setStreamId(newStreamId);

      // CHECK 1: If camera has an ID, it's from camera management - use enhanced stream
      if (camera.id) {
        console.log(`Camera ${camera.id} is from camera management, using enhanced stream endpoint`);
        const enhancedStreamUrl = `${API_BASE_URL}/api/collections/cameras/${camera.id}/stream${token ? `?token=${token}` : ''}`;
        setStreamUrl(enhancedStreamUrl);
        setRetryCount(0);
        console.log(`Using enhanced stream: ${enhancedStreamUrl}`);
        return;
      }

      // CHECK 2: For non-camera-management cameras, check if legacy stream exists
      let collectionName = 'default';
      if (camera.name && camera.name.includes('(')) {
        collectionName = camera.name.split('(')[0].trim();
      } else if (camera.collectionId) {
        collectionName = camera.collectionId;
      }

      try {
        const existingStreamResponse = await axios.get(`${API_BASE_URL}/api/get_stream_for_camera`, {
          params: {
            camera_ip: camera.ip,
            collection_name: collectionName
          },
          headers: {
            'Authorization': `Bearer ${token}`
          },
          timeout: 5000
        });

        if (existingStreamResponse.data.success && existingStreamResponse.data.exists && existingStreamResponse.data.is_running) {
          // Use existing stream
          let feedUrl = `${API_BASE_URL}${existingStreamResponse.data.feed_url}`;

          // Append auth token as query parameter
          if (token) {
            feedUrl += (feedUrl.includes('?') ? '&' : '?') + `token=${token}`;
          }

          setStreamUrl(feedUrl);
          setStreamId(existingStreamResponse.data.stream_id);
          console.log(`Using existing MJPEG stream: ${feedUrl}`);
          setRetryCount(0);
          return;
        }
      } catch (error) {
        console.log('Could not check for existing stream, proceeding with new stream creation');
      }

      // CHECK 3: Only create new legacy stream if camera doesn't have ID
      // Check if we have an RTSP URL
      let rtspUrl = camera.streamUrl;

      // If no RTSP URL, try to construct one from IP
      if (!rtspUrl && camera.ip) {
        rtspUrl = `rtsp://admin:Admin@123@${camera.ip}:554`;
      }

      if (!rtspUrl) {
        throw new Error('No RTSP URL available for camera');
      }

      console.log(`Starting MJPEG stream for camera ${camera.name} (${newStreamId}) with RTSP URL: ${rtspUrl}`);

      // Start the stream on the backend
      const response = await axios.post(`${API_BASE_URL}/api/start_stream`, {
        rtsp_url: rtspUrl,
        stream_id: newStreamId
      }, {
        headers: {
          'Authorization': `Bearer ${token}`
        },
        timeout: 10000 // 10 second timeout
      });

      if (response.data.success) {
        const feedUrl = `${API_BASE_URL}${response.data.feed_url}${response.data.feed_url.includes('?') ? '&' : '?'}token=${token}`;
        console.log(`Setting stream URL to: ${feedUrl}`);
        setStreamUrl(feedUrl);

        if (response.data.reused) {
          console.log(`MJPEG stream reused: ${feedUrl}`);
        } else {
          console.log(`MJPEG stream started: ${feedUrl}`);
        }

        // Reset retry count on success
        setRetryCount(0);
      } else {
        throw new Error(response.data.error || 'Failed to start stream');
      }

    } catch (error) {
      console.error('Error starting MJPEG stream:', error);
      setHasError(true);
      setIsLoading(false);

      if (onError) {
        onError(error.message);
      }

      // Retry logic with exponential backoff
      if (retryCount < maxRetries) {
        const backoffTime = Math.min(3000 * Math.pow(2, retryCount), 15000); // Max 15 seconds
        console.log(`Retrying stream start (${retryCount + 1}/${maxRetries}) in ${backoffTime / 1000} seconds...`);
        retryTimeoutRef.current = setTimeout(() => {
          setRetryCount(prev => prev + 1);
          startStream();
        }, backoffTime);
      }
    } finally {
      isStartingRef.current = false;
    }
  };

  // Stop stream
  const stopStream = async () => {
    if (streamId) {
      try {
        await axios.delete(`${API_BASE_URL}/api/stop_stream/${streamId}`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });
        console.log(`Stopped MJPEG stream: ${streamId}`);
      } catch (error) {
        console.error('Error stopping stream:', error);
      }
    }

    setStreamUrl(null);
    setStreamId(null);
    setIsLoading(true);
    setHasError(false);

    // Clear retry timeout
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }
  };

  // Handle image load
  const handleImageLoad = () => {
    console.log(`✅ MJPEG stream loaded successfully for camera ${camera.name}`);
    setIsLoading(false);
    setHasError(false);

    if (onPlay) {
      onPlay();
    }
  };

  // Handle image error
  const handleImageError = (event) => {
    console.error(`❌ MJPEG stream error for camera ${camera.name}:`, event.target?.src);
    setHasError(true);
    setIsLoading(false);

    if (onError) {
      onError('Stream connection failed');
    }

    // Retry logic for image errors
    if (retryCount < maxRetries) {
      console.log(`Retrying stream connection (${retryCount + 1}/${maxRetries}) in 2 seconds...`);
      retryTimeoutRef.current = setTimeout(() => {
        setRetryCount(prev => prev + 1);
        // Try to reload the image
        if (imgRef.current) {
          const timestamp = Date.now();
          const separator = streamUrl.includes('?') ? '&' : '?';
          imgRef.current.src = `${streamUrl}${separator}t=${timestamp}`;
        }
      }, 2000);
    }
  };

  // Start stream when component mounts or camera changes
  useEffect(() => {
    let isMounted = true;

    const initializeStream = async () => {
      if (isMounted) {
        await startStream();
      }
    };

    initializeStream();

    // Cleanup function
    return () => {
      isMounted = false;
      stopStream();
    };
  }, [camera.id]); // Only depend on camera.id to prevent unnecessary restarts

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
    };
  }, []);

  if (hasError && retryCount >= maxRetries) {
    return (
      <div className="mjpeg-error">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#FF4444" strokeWidth="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>Stream unavailable</span>
        <button
          className="retry-button"
          onClick={() => {
            setRetryCount(0);
            startStream();
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  // Always show the image if we have a stream URL, even if loading
  // This allows the browser to handle the MJPEG stream loading

  return (
    <div className="mjpeg-player">
      {/* Show loading state if no stream URL or still loading */}
      {(!streamUrl || isLoading) && (
        <div className="mjpeg-loading">
          <div className="loading-spinner"></div>
          <span>Connecting to stream...</span>
          {retryCount > 0 && (
            <small>Retry {retryCount}/{maxRetries}</small>
          )}
        </div>
      )}

      {/* Always show image if we have a stream URL */}
      {streamUrl && (
        <img
          ref={imgRef}
          src={streamUrl}
          alt={`Camera ${camera.name}`}
          className="mjpeg-stream"
          onLoad={handleImageLoad}
          onError={handleImageError}
          style={{
            maxWidth: '100%',
            maxHeight: '100%',
            display: isLoading ? 'none' : 'block'
          }}
        />
      )}


    </div>
  );
};

export default MJPEGPlayer;
