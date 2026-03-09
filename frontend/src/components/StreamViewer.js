import React, { useState, useEffect } from 'react';
import axios from 'axios';
import MJPEGPlayer from './camera/MJPEGPlayer';
import useAuthStore from '../store/authStore';
import { Grid, Play, Square, RefreshCw, Settings, Monitor } from 'lucide-react';
import { API_BASE_URL } from '../utils/apiConfig';
import './StreamViewer.css';

const StreamViewer = () => {
  const [cameras, setCameras] = useState([]);
  const [activeCameras, setActiveCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [gridLayout, setGridLayout] = useState('2x2');
  const { token } = useAuthStore();
  // Auto-refresh functionality removed

  // Grid layout configurations
  const gridLayouts = {
    '1x1': { cols: 1, rows: 1, maxStreams: 1 },
    '2x1': { cols: 2, rows: 1, maxStreams: 2 },
    '2x2': { cols: 2, rows: 2, maxStreams: 4 },
    '3x2': { cols: 3, rows: 2, maxStreams: 6 },
    '3x3': { cols: 3, rows: 3, maxStreams: 9 },
    '4x3': { cols: 4, rows: 3, maxStreams: 12 },
    '4x4': { cols: 4, rows: 4, maxStreams: 16 }
  };

  // Fetch cameras from camera management system
  const fetchCameras = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await axios.get(`${API_BASE_URL}/api/collections/cameras`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      
      if (response.data.cameras) {
        const allCameras = response.data.cameras;
        setCameras(allCameras);
        
        // Filter only active cameras for streaming
        const activeOnes = allCameras.filter(camera => camera.is_active);
        setActiveCameras(activeOnes);
        
        console.log('Fetched cameras:', allCameras);
        console.log('Active cameras for streaming:', activeOnes);
      } else {
        setError('No cameras found');
      }
    } catch (err) {
      console.error('Error fetching cameras:', err);
      setError('Failed to fetch cameras. Please check if the backend server is running.');
    } finally {
      setLoading(false);
    }
  };

  // Convert camera data to format expected by MJPEGPlayer
  const convertCameraToPlayerFormat = (camera) => {
    const resolvedIp = camera.ip_address || camera.ip || extractIPFromRTSP(camera.rtsp_url);
    const resolvedCollection = camera.collection_id || camera.collectionId || camera.collection_name || 'default';

    return {
      id: camera.id,
      name: camera.name,
      ip: resolvedIp,
      streamUrl: camera.rtsp_url,
      collectionId: resolvedCollection,
      isActive: camera.is_active
    };
  };

  // Extract IP address from RTSP URL
  const extractIPFromRTSP = (rtspUrl) => {
    if (!rtspUrl) return 'Unknown';
    
    try {
      const url = new URL(rtspUrl);
      return url.hostname;
    } catch (error) {
      // Fallback: try to extract IP using regex
      const ipMatch = rtspUrl.match(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/);
      return ipMatch ? ipMatch[1] : 'Unknown';
    }
  };

  // Fetch cameras from camera management system on component mount only
  useEffect(() => {
    fetchCameras();
  }, []);

  // Handle player events
  const handlePlayerPlay = (camera) => {
    console.log(`Stream started for camera: ${camera.name}`);
  };

  const handlePlayerError = (camera, error) => {
    console.error(`Stream error for camera ${camera.name}:`, error);
    // You could add a fallback here or show error state
  };

  const currentLayout = gridLayouts[gridLayout];
  const displayCameras = activeCameras.slice(0, currentLayout.maxStreams);
  const convertedCameras = displayCameras.map(convertCameraToPlayerFormat);

  if (loading && cameras.length === 0) {
    return (
      <div className="stream-viewer">
        <div className="loading-screen">
          <div className="loading-content">
            <RefreshCw className="loading-icon" size={48} />
            <h2>Loading Stream Viewer</h2>
            <p>Fetching active camera streams...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="stream-viewer">
      {/* Header Controls */}
      <div className="stream-header">
        <div className="header-left">
          <div className="header-title">
            <Monitor size={24} />
            <h1>Stream Viewer</h1>
          </div>
          <div className="stream-stats">
            <span className="stat">
              Total Cameras: <strong>{cameras.length}</strong>
            </span>
            <span className="stat">
              Active Streams: <strong>{activeCameras.length}</strong>
            </span>
            <span className="stat">
              Displayed: <strong>{Math.min(activeCameras.length, currentLayout.maxStreams)}</strong>
            </span>
          </div>
        </div>

        <div className="header-controls">
          <div className="control-group">
            <label htmlFor="grid-layout">Layout:</label>
            <select 
              id="grid-layout"
              value={gridLayout} 
              onChange={(e) => setGridLayout(e.target.value)}
              className="layout-selector"
            >
              <option value="1x1">1×1</option>
              <option value="2x1">2×1</option>
              <option value="2x2">2×2</option>
              <option value="3x2">3×2</option>
              <option value="3x3">3×3</option>
              <option value="4x3">4×3</option>
              <option value="4x4">4×4</option>
            </select>
          </div>

          <div className="control-group">
            <button 
              onClick={fetchCameras}
              className="refresh-btn"
              disabled={loading}
              title="Refresh camera list"
            >
              <RefreshCw size={16} className={loading ? 'spinning' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
          <button onClick={fetchCameras} className="retry-btn">
            Retry
          </button>
        </div>
      )}

      {/* Stream Grid */}
      <div className="stream-content">
        {activeCameras.length === 0 ? (
          <div className="no-streams">
            <div className="no-streams-content">
              <Monitor size={64} />
              <h2>No Active Streams</h2>
              <p>No active cameras found. Please activate cameras in the Camera Management tab.</p>
              <button onClick={fetchCameras} className="refresh-btn large">
                <RefreshCw size={20} />
                Refresh
              </button>
            </div>
          </div>
        ) : (
          <div 
            className="video-grid"
            style={{
              gridTemplateColumns: `repeat(${currentLayout.cols}, 1fr)`,
              gridTemplateRows: `repeat(${currentLayout.rows}, 1fr)`
            }}
          >
            {convertedCameras.map((camera, index) => (
              <div key={camera.id} className="video-cell">
                <div className="video-header">
                  <span className="camera-name">{camera.name}</span>
                  <span className="stream-status live">● LIVE</span>
                </div>
                
                <div className="video-container">
                  <MJPEGPlayer
                    camera={camera}
                    onPlay={() => handlePlayerPlay(camera)}
                    onError={(error) => handlePlayerError(camera, error)}
                  />
                </div>
                
                <div className="video-footer">
                  <span className="camera-ip">{camera.ip}</span>
                  <span className="camera-collection">{camera.collectionId}</span>
                </div>
              </div>
            ))}

            {/* Fill empty cells */}
            {Array.from({ 
              length: Math.max(0, currentLayout.maxStreams - convertedCameras.length) 
            }).map((_, index) => (
              <div key={`empty-${index}`} className="video-cell empty">
                <div className="empty-placeholder">
                  <Monitor size={32} />
                  <span>No Camera</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Overflow Notice */}
        {activeCameras.length > currentLayout.maxStreams && (
          <div className="overflow-notice">
            <Settings size={16} />
            <span>
              Showing {currentLayout.maxStreams} of {activeCameras.length} active cameras. 
              Increase grid size to view more streams.
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default StreamViewer;
