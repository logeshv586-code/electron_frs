import React, { useState, useEffect } from 'react';
import './RecordingManager.css';

const RecordingManager = ({ camera }) => {
  const [recordings, setRecordings] = useState([]);
  const [activeRecordings, setActiveRecordings] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showRecordingDialog, setShowRecordingDialog] = useState(false);
  const [recordingDuration, setRecordingDuration] = useState(30); // minutes

  useEffect(() => {
    if (camera) {
      loadRecordings();
      loadActiveRecordings();
    }
  }, [camera]);

  const loadRecordings = async () => {
    if (!window.electronAPI || !camera) return;
    
    try {
      setLoading(true);
      const result = await window.electronAPI.getCameraRecordings(camera.id);
      if (result.success) {
        setRecordings(result.data.recordings || []);
      } else {
        setError(result.error);
      }
    } catch (err) {
      setError('Failed to load recordings');
      console.error('Error loading recordings:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadActiveRecordings = async () => {
    if (!window.electronAPI) return;
    
    try {
      const result = await window.electronAPI.getActiveRecordings();
      if (result.success) {
        setActiveRecordings(result.data || {});
      }
    } catch (err) {
      console.error('Error loading active recordings:', err);
    }
  };

  const startRecording = async () => {
    if (!window.electronAPI || !camera) return;
    
    try {
      setLoading(true);
      const result = await window.electronAPI.startCameraRecording(
        camera.id, 
        recordingDuration > 0 ? recordingDuration : null
      );
      
      if (result.success) {
        setShowRecordingDialog(false);
        loadActiveRecordings();
        setError(null);
      } else {
        setError(result.error);
      }
    } catch (err) {
      setError('Failed to start recording');
      console.error('Error starting recording:', err);
    } finally {
      setLoading(false);
    }
  };

  const stopRecording = async (recordingId) => {
    if (!window.electronAPI || !camera) return;
    
    try {
      setLoading(true);
      const result = await window.electronAPI.stopCameraRecording(camera.id, recordingId);
      
      if (result.success) {
        loadActiveRecordings();
        loadRecordings(); // Refresh recordings list
        setError(null);
      } else {
        setError(result.error);
      }
    } catch (err) {
      setError('Failed to stop recording');
      console.error('Error stopping recording:', err);
    } finally {
      setLoading(false);
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDuration = (startTime, endTime) => {
    const start = new Date(startTime);
    const end = endTime ? new Date(endTime) : new Date();
    const duration = Math.floor((end - start) / 1000); // seconds
    
    const hours = Math.floor(duration / 3600);
    const minutes = Math.floor((duration % 3600) / 60);
    const seconds = duration % 60;
    
    if (hours > 0) {
      return `${hours}h ${minutes}m ${seconds}s`;
    } else if (minutes > 0) {
      return `${minutes}m ${seconds}s`;
    } else {
      return `${seconds}s`;
    }
  };

  // Find active recording for this camera
  const cameraActiveRecording = Object.entries(activeRecordings).find(
    ([_, recording]) => recording.camera_id === camera?.id
  );

  return (
    <div className="recording-manager">
      <div className="recording-header">
        <h3>Recordings for {camera?.name}</h3>
        <div className="recording-controls">
          {cameraActiveRecording ? (
            <div className="active-recording">
              <span className="recording-indicator">🔴 Recording</span>
              <button 
                className="stop-recording-btn"
                onClick={() => stopRecording(cameraActiveRecording[0])}
                disabled={loading}
              >
                Stop Recording
              </button>
            </div>
          ) : (
            <button 
              className="start-recording-btn"
              onClick={() => setShowRecordingDialog(true)}
              disabled={loading}
            >
              Start Recording
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="error-message">
          {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {showRecordingDialog && (
        <div className="recording-dialog-overlay">
          <div className="recording-dialog">
            <h4>Start Recording</h4>
            <div className="dialog-content">
              <label>
                Duration (minutes):
                <input
                  type="number"
                  value={recordingDuration}
                  onChange={(e) => setRecordingDuration(parseInt(e.target.value) || 0)}
                  min="0"
                  placeholder="0 for continuous"
                />
                <small>Set to 0 for continuous recording</small>
              </label>
            </div>
            <div className="dialog-actions">
              <button onClick={startRecording} disabled={loading}>
                Start Recording
              </button>
              <button onClick={() => setShowRecordingDialog(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="recordings-list">
        {loading && recordings.length === 0 ? (
          <div className="loading">Loading recordings...</div>
        ) : recordings.length === 0 ? (
          <div className="no-recordings">
            <p>No recordings found for this camera</p>
          </div>
        ) : (
          <div className="recordings-grid">
            {recordings.map((recording, index) => (
              <div key={index} className="recording-item">
                <div className="recording-info">
                  <h4>{recording.filename}</h4>
                  <div className="recording-details">
                    <span>Size: {formatFileSize(recording.size_bytes)}</span>
                    <span>Created: {new Date(recording.created_at).toLocaleString()}</span>
                  </div>
                </div>
                <div className="recording-actions">
                  <button 
                    className="download-btn"
                    onClick={() => {
                      // In a real implementation, you'd handle file download
                      console.log('Download recording:', recording.path);
                    }}
                  >
                    Download
                  </button>
                  <button 
                    className="play-btn"
                    onClick={() => {
                      // In a real implementation, you'd open a video player
                      console.log('Play recording:', recording.path);
                    }}
                  >
                    Play
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default RecordingManager;
