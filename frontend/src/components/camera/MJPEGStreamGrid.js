import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './MJPEGStreamGrid.css';

import { API_BASE_URL } from '../../utils/apiConfig';

import useAuthStore from '../../store/authStore';

const MJPEGStreamGrid = ({ collectionName }) => {
  const { token } = useAuthStore();
  const [streams, setStreams] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [gridLayout, setGridLayout] = useState('2x2');
  // Per-stream bounding box toggles: { streamId: boolean } — default true
  const [bboxToggles, setBboxToggles] = useState({});
  const imgRefs = useRef({});

  // Grid layout configurations
  const gridLayouts = {
    '1x1': { cols: 1, rows: 1 },
    '2x2': { cols: 2, rows: 2 },
    '3x3': { cols: 3, rows: 3 },
    '4x4': { cols: 4, rows: 4 },
    '2x3': { cols: 2, rows: 3 },
    '3x2': { cols: 3, rows: 2 }
  };

  const startStreams = async () => {
    if (!collectionName) {
      setError('No collection selected');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Start streams for the collection
      const response = await axios.get(`${API_BASE_URL}/api/start_collection_streams/${collectionName}`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.data.started_streams) {
        setStreams(response.data.started_streams);
        console.log('Started streams:', response.data.started_streams);
      } else {
        setError('No streams started');
      }

      if (response.data.errors && response.data.errors.length > 0) {
        console.warn('Stream errors:', response.data.errors);
      }

    } catch (err) {
      console.error('Error starting streams:', err);
      setError(err.response?.data?.error || 'Failed to start streams');
    } finally {
      setLoading(false);
    }
  };

  const stopAllStreams = async () => {
    try {
      // Stop all active streams
      for (const stream of streams) {
        await axios.delete(`${API_BASE_URL}/api/stop_stream/${stream.stream_id}`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });
      }
      setStreams([]);
    } catch (err) {
      console.error('Error stopping streams:', err);
    }
  };

  const handleImageError = (streamId) => {
    console.error(`Stream error for ${streamId}`);
    // You could implement retry logic here
  };

  const handleImageLoad = (streamId) => {
    console.log(`Stream loaded for ${streamId}`);
  };

  useEffect(() => {
    return () => {
      // Cleanup streams when component unmounts
      stopAllStreams();
    };
  }, []);

  // Toggle bounding box for a specific stream
  const toggleStreamBbox = async (stream) => {
    const sid = stream.stream_id;
    const currentState = bboxToggles[sid] !== false; // default true
    const newState = !currentState;
    
    setBboxToggles(prev => ({ ...prev, [sid]: newState }));
    
    try {
      await axios.post(`${API_BASE_URL}/api/bounding-box/toggle`,
        { enabled: newState, stream_id: sid },
        { headers: { 'Authorization': `Bearer ${token}` } }
      );
    } catch (err) {
      console.error('Error toggling bounding box:', err);
      setBboxToggles(prev => ({ ...prev, [sid]: currentState }));
    }
  };

  const currentLayout = gridLayouts[gridLayout];
  const maxStreams = currentLayout.cols * currentLayout.rows;
  const displayStreams = streams.slice(0, maxStreams);

  return (
    <div className="mjpeg-stream-grid">
      <div className="stream-controls">
        <div className="control-group">
          <button
            onClick={startStreams}
            disabled={loading || !collectionName}
            className="btn btn-primary"
          >
            {loading ? 'Starting...' : 'Start Streams'}
          </button>

          <button
            onClick={stopAllStreams}
            disabled={streams.length === 0}
            className="btn btn-secondary"
          >
            Stop All Streams
          </button>


        </div>

        <div className="control-group">
          <label htmlFor="grid-layout">Grid Layout:</label>
          <select
            id="grid-layout"
            value={gridLayout}
            onChange={(e) => setGridLayout(e.target.value)}
            className="grid-selector"
          >
            <option value="1x1">1x1</option>
            <option value="2x2">2x2</option>
            <option value="2x3">2x3</option>
            <option value="3x2">3x2</option>
            <option value="3x3">3x3</option>
            <option value="4x4">4x4</option>
          </select>
        </div>

        <div className="stream-info">
          <span>Collection: {collectionName || 'None'}</span>
          <span>Active Streams: {streams.length}</span>
        </div>
      </div>

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}

      <div
        className="video-grid"
        style={{
          gridTemplateColumns: `repeat(${currentLayout.cols}, 1fr)`,
          gridTemplateRows: `repeat(${currentLayout.rows}, 1fr)`
        }}
      >
        {displayStreams.map((stream, index) => {
          const bboxOn = bboxToggles[stream.stream_id] !== false;
          return (
            <div key={stream.stream_id} className="video-cell">
              <div className="video-header">
                <span className="camera-label">
                  {stream.camera_ip}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <button
                    onClick={() => toggleStreamBbox(stream)}
                    className={`cam-bbox-toggle ${bboxOn ? 'on' : 'off'}`}
                    title={bboxOn ? 'Hide Bounding Boxes' : 'Show Bounding Boxes'}
                    style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                  >
                    {bboxOn ? '👁' : '👁‍🗨'} BOXES
                  </button>
                  <span className="stream-status">●</span>
                </div>
              </div>

              <div className="video-container">
                <img
                  ref={el => imgRefs.current[stream.stream_id] = el}
                  src={`${API_BASE_URL}${stream.feed_url}${stream.feed_url.includes('?') ? '&' : '?'}token=${token}`}
                  alt={`Camera ${stream.camera_ip}`}
                  className="video-stream"
                  onError={() => handleImageError(stream.stream_id)}
                  onLoad={() => handleImageLoad(stream.stream_id)}
                />
              </div>

              <div className="video-footer">
                <small>{stream.stream_id}</small>
              </div>
            </div>
          );
        })}

        {/* Fill empty cells */}
        {Array.from({ length: maxStreams - displayStreams.length }).map((_, index) => (
          <div key={`empty-${index}`} className="video-cell empty">
            <div className="empty-placeholder">
              <span>No Camera</span>
            </div>
          </div>
        ))}
      </div>

      {streams.length > maxStreams && (
        <div className="overflow-notice">
          <p>Showing {maxStreams} of {streams.length} streams.
            Increase grid size to see more cameras.</p>
        </div>
      )}
    </div>
  );
};

export default MJPEGStreamGrid;
