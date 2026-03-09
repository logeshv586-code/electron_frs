import React, { useState, useRef } from 'react';
import './VideoWidget.css';

import { API_BASE_URL as BASE_URL } from '../utils/apiConfig';

const VideoWidget = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [results, setResults] = useState(null);
  const [taskId, setTaskId] = useState(null);
  const fileInputRef = useRef(null);
  const progressIntervalRef = useRef(null);

  // Helper function to format time in seconds to MM:SS format
  const formatTime = (seconds) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
  };

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      // Validate file type
      const validTypes = ['.mp4', '.avi', '.mov', '.mkv', '.wmv'];
      const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
      
      if (!validTypes.includes(fileExtension)) {
        alert('Please select a valid video file (MP4, AVI, MOV, MKV, WMV)');
        return;
      }

      // Check file size (100MB limit)
      const maxSize = 100 * 1024 * 1024; // 100MB
      if (file.size > maxSize) {
        alert('File size must be less than 100MB');
        return;
      }

      setSelectedFile(file);
      setResults(null);
      setProgress(0);
      setStatusMessage('');
    }
  };

  const startProcessing = async () => {
    if (!selectedFile) {
      alert('Please select a video file first');
      return;
    }

    setIsProcessing(true);
    setProgress(0);
    setStatusMessage('Uploading video...');
    setResults(null);

    try {
      // Step 1: Upload video
      const formData = new FormData();
      formData.append('file', selectedFile);

      const uploadResponse = await fetch(`${BASE_URL}/api/video/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!uploadResponse.ok) {
        throw new Error(`Upload failed! status: ${uploadResponse.status}`);
      }

      const uploadResult = await uploadResponse.json();
      const videoId = uploadResult.filename; // The API returns filename as the video ID

      setStatusMessage('Video uploaded successfully. Starting processing...');

      // Step 2: Start processing
      const processResponse = await fetch(`${BASE_URL}/api/video/process/async`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          video_id: videoId,
          options: {
            detect_faces: true,
            recognize_faces: true,
            min_confidence: 60.0,
            detect_motion: false
          }
        }),
      });

      if (!processResponse.ok) {
        throw new Error(`Processing failed! status: ${processResponse.status}`);
      }

      const processResult = await processResponse.json();

      if (processResult.task_id) {
        setTaskId(processResult.task_id);
        setStatusMessage('Processing started...');
        startProgressTracking(processResult.task_id);
      } else {
        throw new Error('No task ID received from server');
      }
    } catch (error) {
      console.error('Video processing error:', error);
      setStatusMessage(`Error: ${error.message}`);
      setIsProcessing(false);
    }
  };

  const startProgressTracking = (taskId) => {
    progressIntervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(`${BASE_URL}/api/video/process/${taskId}/status`);
        const progressData = await response.json();

        setProgress(progressData.progress || 0);
        setStatusMessage(progressData.message || 'Processing...');

        if (progressData.status === 'completed') {
          clearInterval(progressIntervalRef.current);
          setIsProcessing(false);

          // Get the full results
          try {
            const resultResponse = await fetch(`${BASE_URL}/api/video/process/${taskId}/result`);
            if (resultResponse.ok) {
              const resultData = await resultResponse.json();
              setResults(resultData);
              setStatusMessage('Processing completed successfully!');
            } else {
              setStatusMessage('Processing completed but results could not be retrieved');
            }
          } catch (resultError) {
            console.error('Error getting results:', resultError);
            setStatusMessage('Processing completed but results could not be retrieved');
          }
        } else if (progressData.status === 'failed') {
          clearInterval(progressIntervalRef.current);
          setIsProcessing(false);
          setStatusMessage(`Processing failed: ${progressData.message || 'Unknown error'}`);
        }
      } catch (error) {
        console.error('Progress tracking error:', error);
        clearInterval(progressIntervalRef.current);
        setIsProcessing(false);
        setStatusMessage('Error tracking progress');
      }
    }, 2000); // Check every 2 seconds
  };

  const resetWidget = () => {
    if (progressIntervalRef.current) {
      clearInterval(progressIntervalRef.current);
    }
    setSelectedFile(null);
    setIsProcessing(false);
    setProgress(0);
    setStatusMessage('');
    setResults(null);
    setTaskId(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const downloadResults = async () => {
    if (!taskId) return;

    try {
      // For now, just download the results as JSON since the backend doesn't provide processed video download
      const response = await fetch(`${BASE_URL}/api/video/process/${taskId}/result`);
      if (response.ok) {
        const resultData = await response.json();
        const dataStr = JSON.stringify(resultData, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });

        const url = window.URL.createObjectURL(dataBlob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `video_analysis_results_${taskId}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      } else {
        alert('Failed to download results');
      }
    } catch (error) {
      console.error('Download error:', error);
      alert('Error downloading results');
    }
  };

  return (
    <div className="video-widget">
      <div className="video-header">
        <h2>Video Processing</h2>
        <p>Upload a video file to detect and track faces</p>
      </div>

      <div className="video-upload-section">
        <div className="file-selection">
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            onChange={handleFileSelect}
            style={{ display: 'none' }}
            disabled={isProcessing}
          />
          <div
            className="upload-area"
            onClick={() => {
              console.log('Upload area clicked');
              fileInputRef.current?.click();
            }}
            style={{ cursor: 'pointer' }}
          >
            {selectedFile ? (
              <div className="file-info">
                <div className="file-icon">🎥</div>
                <div className="file-details">
                  <h3>{selectedFile.name}</h3>
                  <p>Size: {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</p>
                  <p>Type: {selectedFile.type}</p>
                </div>
              </div>
            ) : (
              <div className="upload-placeholder">
                <div className="upload-icon">📁</div>
                <p>Click to select a video file</p>
                <small>Supported: MP4, AVI, MOV, MKV, WMV (Max: 100MB)</small>
              </div>
            )}
          </div>
        </div>

        <div className="video-controls">
          <button
            className="btn-primary"
            onClick={startProcessing}
            disabled={!selectedFile || isProcessing}
          >
            {isProcessing ? 'Processing...' : 'Start Processing'}
          </button>
          <button
            className="btn-secondary"
            onClick={resetWidget}
            disabled={isProcessing}
          >
            Reset
          </button>
        </div>
      </div>

      {(isProcessing || statusMessage) && (
        <div className="processing-section">
          <div className="status-message">
            <h3>Status</h3>
            <p>{statusMessage}</p>
          </div>
          
          {isProcessing && (
            <div className="progress-section">
              <div className="progress-bar">
                <div 
                  className="progress-fill" 
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              <span className="progress-text">{progress.toFixed(1)}%</span>
            </div>
          )}
        </div>
      )}

      {results && (
        <div className="results-section">
          <h3>Processing Results</h3>
          <div className="results-summary">
            <div className="result-item">
              <span className="label">Total Faces Detected:</span>
              <span className="value">{results.total_faces || 0}</span>
            </div>
            <div className="result-item">
              <span className="label">Known Faces:</span>
              <span className="value">{results.known_faces || 0}</span>
            </div>
            <div className="result-item">
              <span className="label">Unknown Faces:</span>
              <span className="value">{results.unknown_faces || 0}</span>
            </div>
            <div className="result-item">
              <span className="label">Processing Time:</span>
              <span className="value">{results.processing_time || 'N/A'}</span>
            </div>
          </div>

          {results.detected_persons && results.detected_persons.length > 0 && (
            <div className="detected-persons">
              <h4>Detected Persons</h4>
              <div className="persons-list">
                {results.detected_persons.map((person, index) => (
                  <div key={index} className="person-item">
                    <div className="person-header">
                      <span className="person-name">{person.name}</span>
                      <span className="person-count">{person.count} detections</span>
                      {person.total_duration && (
                        <span className="person-duration">
                          Duration: {person.total_duration.toFixed(1)}s
                        </span>
                      )}
                    </div>
                    
                    {/* Show appearance intervals if available */}
                    {results.person_tracking && results.person_tracking[person.name] && 
                     results.person_tracking[person.name].appearances && (
                      <div className="person-appearances">
                        <h5>Appearances:</h5>
                        {results.person_tracking[person.name].appearances.map((appearance, idx) => (
                          <div key={idx} className="appearance-item">
                            <span className="appearance-time">
                              {formatTime(appearance.start_time)} - {formatTime(appearance.end_time)}
                            </span>
                            <span className="appearance-confidence">
                              Confidence: {appearance.confidence.toFixed(1)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                    
                    {/* Show face detections if available */}
                    {results.face_detections && (
                      <div className="face-detections">
                        <h5>Face Detections:</h5>
                        <div className="detection-list">
                          {results.face_detections
                            .filter(detection => 
                              detection.faces.some(face => face.name === person.name)
                            )
                            .slice(0, 5) // Show first 5 detections
                            .map((detection, idx) => {
                              const personFace = detection.faces.find(face => face.name === person.name);
                              return (
                                <div key={idx} className="detection-item">
                                  <div className="detection-info">
                                    <span className="detection-time">
                                      Time: {formatTime(detection.timestamp)}
                                    </span>
                                    <span className="detection-confidence">
                                      Confidence: {personFace.confidence.toFixed(1)}%
                                    </span>
                                  </div>
                                  {personFace.face_image && (
                                    <img 
                                      src={`data:image/jpeg;base64,${personFace.face_image}`}
                                      alt={`${person.name} at ${formatTime(detection.timestamp)}`}
                                      className="face-thumbnail"
                                      style={{ width: '50px', height: '50px', objectFit: 'cover' }}
                                    />
                                  )}
                                </div>
                              );
                            })
                          }
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="results-actions">
            <button
              className="btn-primary"
              onClick={downloadResults}
            >
              Download Processed Video
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default VideoWidget;
