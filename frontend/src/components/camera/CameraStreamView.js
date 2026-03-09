import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useCameraStore } from '../../store/cameraStore';
import useAuthStore from '../../store/authStore';
import WebRTCPlayer from './WebRTCPlayer';
import { API_BASE_URL } from '../../utils/apiConfig';
import { parseStreamUrl, generateCameraId } from '../../utils/cameraUtils';
import './CameraStream.css';
import './CameraStreamView.css';

const CameraStreamView = () => {
  const [streams, setStreams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { initializeCameraConfig } = useCameraStore();
  const { token } = useAuthStore();

  useEffect(() => {
    const fetchCameras = async () => {
      try {
        setLoading(true);
        // Fetch camera configuration from the backend
        const response = await axios.get(`${API_BASE_URL}/api/collections/cameras`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });

        if (response.data.error) {
          setError(response.data.error);
          return;
        }

        console.log('Camera configuration:', response.data.cameras);

        // Update the camera store with the configuration
        initializeCameraConfig(response.data.cameras);

        // Start WebRTC streams for each collection
        const streamInfoArray = [];
        for (const collection of Object.keys(response.data.cameras)) {
          console.log(`Starting WebRTC streams for collection: ${collection}`);
          try {
            // Updated endpoint to match the new backend implementation
            const collectionResponse = await axios.get(`${API_BASE_URL}/api/collections/${collection}/streams`, {
              headers: {
                'Authorization': `Bearer ${token}`
              }
            });

            if (collectionResponse.data.error) {
              console.error(`Error starting WebRTC streams for collection ${collection}:`, collectionResponse.data.error);
              continue;
            }

            console.log(`Received WebRTC streams for ${collection}:`, collectionResponse.data.streams);
            streamInfoArray.push(...collectionResponse.data.streams);
          } catch (err) {
            console.error(`Error starting WebRTC streams for collection ${collection}:`, err);
          }
        }

        console.log('All WebRTC stream info:', streamInfoArray);
        setStreams(streamInfoArray);
      } catch (error) {
        console.error('Error fetching cameras:', error);
        setError('Failed to fetch camera streams. Please check if the backend server is running.');
      } finally {
        setLoading(false);
      }
    };

    fetchCameras();
  }, [initializeCameraConfig]);

  if (loading) {
    return <div className="loading">Loading camera streams...</div>;
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  // Convert stream info to camera objects
  const streamCameras = streams.map((streamInfo, index) => {
    // Extract camera IP from the stream info
    const ip = streamInfo.camera_ip || '';
    const collectionName = streamInfo.collection_name || '';

    // Create a name for the camera
    const name = streamInfo.camera_name || (collectionName ? `${collectionName} (${ip})` : `Camera ${index + 1}`);

    // Generate a stable ID for the camera
    const cameraId = streamInfo.camera_id || (collectionName && ip
      ? generateCameraId(collectionName, ip)
      : `stream-${index}-${Date.now()}`);

    return {
      id: cameraId,
      name: name,
      streamId: streamInfo.stream_id,
      roomId: streamInfo.room_id,
      ip: ip,
      collectionName: collectionName
    };
  });

  return (
    <div className="camera-grid">
      {streams.length === 0 ? (
        <div className="no-cameras">
          <img src="/no-cameras.svg" alt="No Cameras" />
          <p>No camera streams available</p>
        </div>
      ) : (
        streamCameras.map((camera) => (
          <div key={`camera-${camera.id}`} className="camera-cell">
            <div className="camera-header">
              <span className="camera-name">{camera.name}</span>
            </div>
            <WebRTCPlayer
              streamId={camera.streamId}
              roomId={camera.roomId}
              cameraIp={camera.ip}
              collectionName={camera.collectionName}
            />
            <div className="camera-footer">
              <span className="camera-status">Live</span>
              {camera.ip && <span className="camera-ip">{camera.ip}</span>}
            </div>
          </div>
        ))
      )}
    </div>
  );
};

export default CameraStreamView;
