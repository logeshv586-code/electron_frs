import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useCameras } from './CameraManager';
import { API_BASE_URL } from '../../utils/apiConfig';
import './CollectionManager.css';

import { Edit, Trash, Video, Monitor, Play, Square } from 'lucide-react';
import useAuthStore from '../../store/authStore';
// import DraggableVideoCell from './DraggableVideoCell'; // Temporarily disabled due to missing dependencies

// MJPEG StreamPlayer component for real camera streaming
const StreamPlayer = ({ cameraId, cameraName, rtspUrl, isStreaming, onStreamStart, onStreamError }) => {
  const [streamError, setStreamError] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [streamStarted, setStreamStarted] = useState(false);
  const [streamUrl, setStreamUrl] = useState(null);
  const imgRef = useRef(null);
  const { token } = useAuthStore();

  const startMJPEGStream = useCallback(async () => {
    try {
      console.log(`✓ Starting MJPEG stream for camera ${cameraId}`);
      setIsLoading(true);
      setStreamError(false);

      // Use the enhanced stream endpoint for camera management cameras
      // Append auth token as query parameter for <img> tag compatibility
      const enhancedStreamUrl = `${API_BASE_URL}/api/collections/cameras/${cameraId}/stream${token ? `?token=${token}` : ''}`;
      setStreamUrl(enhancedStreamUrl);
      setStreamStarted(true);
      setIsLoading(false);
      onStreamStart();
      console.log(`✓ MJPEG stream started successfully for camera ${cameraId}: ${enhancedStreamUrl}`);

    } catch (error) {
      console.error('✗ Error starting MJPEG stream:', error);
      setStreamError(true);
      setIsLoading(false);
      setStreamStarted(false);
      onStreamError();
    }
  }, [cameraId, API_BASE_URL, onStreamStart, onStreamError]);

  const stopMJPEGStream = useCallback(() => {
    console.log(`✓ Stopping MJPEG stream for camera ${cameraId}`);
    setStreamUrl(null);
    setStreamStarted(false);
    setIsLoading(false);
  }, [cameraId]);

  useEffect(() => {
    console.log(`StreamPlayer useEffect: isStreaming=${isStreaming}, streamStarted=${streamStarted}, cameraId=${cameraId}`);

    if (isStreaming && !streamStarted && !streamError) {
      console.log('Starting MJPEG stream...');
      startMJPEGStream();
    } else if (!isStreaming && streamStarted) {
      console.log('Stopping MJPEG stream...');
      stopMJPEGStream();
    }

    return () => {
      stopMJPEGStream();
    };
  }, [isStreaming, streamStarted, streamError, cameraId, startMJPEGStream, stopMJPEGStream]);

  const handleImageLoad = () => {
    console.log(`✅ MJPEG stream loaded successfully for camera ${cameraId}`);
    setIsLoading(false);
    setStreamError(false);
  };

  const handleImageError = (event) => {
    console.error(`❌ MJPEG stream error for camera ${cameraId}:`, event.target?.src);
    setStreamError(true);
    setIsLoading(false);
    
    // Auto-retry once on image error
    if (!streamUrl?.includes('retry=')) {
      console.log('Attempting auto-retry for image error...');
      setTimeout(retryStream, 1000);
    }

    if (onStreamError) {
      onStreamError('Stream connection failed');
    }
  };

  const retryStream = () => {
    console.log(`Retrying MJPEG stream for camera ${cameraId}`);
    setStreamError(false);
    setStreamStarted(false);
    
    // When retrying, we'll force a fresh URL in startMJPEGStream by adding a timestamp
    const timestamp = Date.now();
    const separator = token ? '&' : '?';
    const retryUrl = `${API_BASE_URL}/api/collections/cameras/${cameraId}/stream${token ? `?token=${token}` : ''}${separator}retry=${timestamp}`;
    
    setStreamUrl(retryUrl);
    setStreamStarted(true);
    setIsLoading(false);
  };

  if (streamError) {
    return (
      <div className="video-placeholder error">
        <Monitor size={48} />
        <p>Stream Unavailable</p>
        <small>Failed to establish stream connection</small>
        <div className="stream-error-actions">
          <button className="retry-stream-btn" onClick={retryStream}>
            Retry Connection
          </button>
        </div>
        <div className="stream-info">
          <small>{rtspUrl ? rtspUrl.replace(/admin:Admin@123@/, 'admin:***@') : 'No RTSP URL'}</small>
        </div>
      </div>
    );
  }

  if (isLoading || !streamUrl) {
    return (
      <div className="video-placeholder loading">
        <Monitor size={48} />
        <p>Connecting to Stream...</p>
        <small>Camera: {cameraName}</small>
      </div>
    );
  }

  return (
    <div className="stream-container">
      <img
        ref={imgRef}
        src={streamUrl}
        alt={`Camera ${cameraName}`}
        className="video-stream"
        onLoad={handleImageLoad}
        onError={handleImageError}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          background: '#000'
        }}
      />
      {streamStarted && (
        <div className="stream-overlay">
          <div className="stream-status-indicator live"></div>
          <span className="stream-status-text">LIVE</span>
        </div>
      )}
    </div>
  );
};

const CollectionManager = ({ onClose, onViewChange }) => {
  const {
    collections,
    createCollection,
    renameCollection,
    deleteCollection,
    activeCollection,
    setCollectionActive,
    initialize,
    loading
  } = useCameras();

  const [newCollectionName, setNewCollectionName] = useState('');
  const [selectedCollection, setSelectedCollection] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [currentLayout, setCurrentLayout] = useState('2x2');
  const [error, setError] = useState('');
  const [editingCollection, setEditingCollection] = useState(null);
  const [editCollectionName, setEditCollectionName] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(null);
  const [cameraStreams, setCameraStreams] = useState({});
  const [allCameras, setAllCameras] = useState([]);
  const [streamsLoading, setStreamsLoading] = useState(false);
  const [streamingCameras, setStreamingCameras] = useState(new Set());


  // Fetch cameras from enhanced camera management system
  const fetchCameraStreams = async () => {
    setStreamsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/cameras`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (response.ok) {
        const data = await response.json();
        setAllCameras(data.cameras || []);

        // Convert enhanced cameras to stream format for compatibility
        const streamData = {};
        data.cameras?.forEach(camera => {
          if (camera.is_active) {
            streamData[camera.id] = camera.rtsp_url;
          }
        });
        setCameraStreams(streamData);
      } else {
        console.error('Failed to fetch camera streams');
      }
    } catch (error) {
      console.error('Error fetching camera streams:', error);
    } finally {
      setStreamsLoading(false);
    }
  };

  // Initialize data on mount
  useEffect(() => {
    if (initialize) {
      initialize();
    }
    fetchCameraStreams();
  }, [initialize]);

  // Listen for camera stream refresh events
  useEffect(() => {
    const handleRefreshStreams = () => {
      fetchCameraStreams();
    };

    window.addEventListener('refreshCameraStreams', handleRefreshStreams);

    return () => {
      window.removeEventListener('refreshCameraStreams', handleRefreshStreams);
    };
  }, []);

  // Clear selected collection when collections change
  useEffect(() => {
    if (selectedCollection && collections && !collections.find(c => c.id === selectedCollection)) {
      setSelectedCollection(null);
      setCollectionActive(null);
    }
  }, [collections, selectedCollection, setCollectionActive]);

  // Sync selected collection with active collection
  useEffect(() => {
    setSelectedCollection(activeCollection);
  }, [activeCollection]);

  const handleCreateCollection = (e) => {
    e.preventDefault();
    setError('');

    if (!newCollectionName.trim()) {
      setError('Please enter an area name');
      return;
    }

    // Check if collection with same name already exists
    const existingCollection = collections && collections.find(
      c => c.name.toLowerCase() === newCollectionName.trim().toLowerCase()
    );

    if (existingCollection) {
      setError('An area with this name already exists');
      return;
    }

    try {
      const newCollectionId = createCollection(newCollectionName.trim());
      setNewCollectionName('');
      setShowCreateForm(false);
      // Select the newly created collection
      setSelectedCollection(newCollectionId);
      setCollectionActive(newCollectionId);
    } catch (err) {
      setError('Failed to create area. Please try again.');
    }
  };

  const handleSelectCollection = (collectionId) => {
    setSelectedCollection(collectionId);
    setCollectionActive(collectionId);
  };

  const handleCloseCollection = () => {
    setSelectedCollection(null);
    setCollectionActive(null);
    setShowCreateForm(false);
  };

  const handleStartRename = (collectionId, e) => {
    e.stopPropagation(); // Prevent collection selection
    const collection = collections && collections.find(c => c.id === collectionId);
    if (collection) {
      setEditingCollection(collectionId);
      setEditCollectionName(collection.name);
    }
  };

  const handleRenameSubmit = (e) => {
    e.preventDefault();
    e.stopPropagation(); // Prevent collection selection

    if (!editCollectionName.trim()) {
      setError('Please enter an area name');
      return;
    }

    try {
      renameCollection(editingCollection, editCollectionName);
      setEditingCollection(null);
      setEditCollectionName('');
      setError('');
    } catch (err) {
      setError(err.message || 'Failed to rename area. Please try again.');
    }
  };

  const handleCancelRename = (e) => {
    e.stopPropagation(); // Prevent collection selection
    setEditingCollection(null);
    setEditCollectionName('');
    setError('');
  };

  const handleDeleteClick = (collectionId, e) => {
    e.stopPropagation(); // Prevent collection selection
    setShowDeleteConfirm(collectionId);
  };

  const handleConfirmDelete = (collectionId) => {
    deleteCollection(collectionId);
    setShowDeleteConfirm(null);
  };

  const handleCancelDelete = () => {
    setShowDeleteConfirm(null);
  };

  // Stream control handlers for WebRTC
  const handleStartStream = async (cameraId) => {
    try {
      console.log(`Starting WebRTC stream for camera ${cameraId}...`);
      // Set streaming state immediately for WebRTC
      setStreamingCameras(prev => new Set([...prev, cameraId]));
    } catch (error) {
      console.error('✗ Error starting WebRTC stream:', error);
    }
  };

  const handleStopStream = async (cameraId) => {
    try {
      console.log(`Stopping WebRTC stream for camera ${cameraId}`);
      setStreamingCameras(prev => {
        const newSet = new Set(prev);
        newSet.delete(cameraId);
        return newSet;
      });
    } catch (error) {
      console.error('Error stopping WebRTC stream:', error);
    }
  };

  // Filter cameras by selected collection
  const getFilteredCameras = () => {
    if (!selectedCollection || !allCameras) return [];

    return allCameras.filter(camera => {
      const cameraCollectionId = camera.collection_id || camera.collectionId || camera.collection;
      return cameraCollectionId === selectedCollection && camera.is_active;
    });
  };

  const filteredCameras = getFilteredCameras();





  return (
    <div className="collection-manager">
      {/* Left Sidebar */}
      <div className="collections-sidebar">
        <div className="collections-header">
          <div className="header-with-close">
            <h3>Manage Areas</h3>
            <button
              className="close-manager-button"
              onClick={onClose}
              title="Close Area Manager"
            >
              ✕
            </button>
          </div>
          <button
            className="create-collection-button"
            onClick={() => setShowCreateForm(true)}
          >
            Create New Area
          </button>
        </div>

        {showCreateForm && (
          <form onSubmit={handleCreateCollection} className="collection-form">
            {error && <div className="error-message">{error}</div>}
            <input
              type="text"
              value={newCollectionName}
              onChange={(e) => setNewCollectionName(e.target.value)}
              placeholder="Enter area name (e.g., Anna Nagar)"
              className="collection-input"
              autoFocus
            />
            <div className="form-actions">
              <button type="submit" className="save-button">Create</button>
              <button
                type="button"
                className="cancel-button"
                onClick={() => {
                  setShowCreateForm(false);
                  setError('');
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        <div className="collections-container">
          {!collections || collections.length === 0 ? (
            <div className="no-collections">
              <p>No areas created yet</p>
              <p>Click "Create New Area" to get started</p>
            </div>
          ) : (
            collections.map(collection => (
              <div
                key={collection.id}
                className={`collection-item ${selectedCollection === collection.id ? 'selected' : ''}`}
                onClick={() => handleSelectCollection(collection.id)}
              >
                {editingCollection === collection.id ? (
                  <form
                    className="collection-edit-form"
                    onSubmit={handleRenameSubmit}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {error && <div className="error-message">{error}</div>}
                    <input
                      type="text"
                      value={editCollectionName}
                      onChange={(e) => setEditCollectionName(e.target.value)}
                      className="collection-input"
                      autoFocus
                    />
                    <div className="form-actions">
                      <button type="submit" className="save-button">Save</button>
                      <button
                        type="button"
                        className="cancel-button"
                        onClick={handleCancelRename}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <span className="collection-name">{collection.name}</span>
                    <div className="collection-actions">
                      <span className="collection-count">{collection.camera_count || 0} cameras</span>
                      <button
                        className="collection-action-button rename-button"
                        onClick={(e) => handleStartRename(collection.id, e)}
                        title="Rename Area"
                      >
                        <Edit size={16} />
                      </button>
                      <button
                        className="collection-action-button delete-button"
                        onClick={(e) => handleDeleteClick(collection.id, e)}
                        title="Delete Area"
                      >
                        <Trash size={16} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Delete Area</h3>
            <p>Are you sure you want to delete this area? All cameras in this area will also be deleted.</p>
            <div className="modal-actions">
              <button
                className="confirm-button"
                onClick={() => handleConfirmDelete(showDeleteConfirm)}
              >
                Delete
              </button>
              <button
                className="cancel-button"
                onClick={handleCancelDelete}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Panel */}
      <div className="collection-details">
        {selectedCollection ? (
          <>
            <div className="collection-header">
              <div className="collection-title">
                <h3>{collections && collections.find(c => c.id === selectedCollection)?.name}</h3>
              </div>
              <div className="collection-header-actions">
                <button
                  className="rtsp-stream-button"
                  onClick={() => onViewChange && onViewChange('rtsp-stream')}
                  style={{ display: 'flex', alignItems: 'center', marginRight: '10px' }}
                >
                  <Video size={16} style={{ marginRight: '5px' }} />
                  <span>Live</span>
                </button>
                <button
                  onClick={handleCloseCollection}
                  className="close-collection-button"
                >
                  Close Area
                </button>
              </div>
            </div>
            <div className="collection-content">
              <div className="streams-section">
                <div className="streams-header">
                  <div className="streams-title">
                    <h4>Camera Streams</h4>
                    <span className="collection-name">{collections?.find(c => c.id === selectedCollection)?.name}</span>
                  </div>
                  <div className="streams-actions">
                    <button className="refresh-btn" onClick={fetchCameraStreams}>
                      <Monitor size={16} />
                      Refresh
                    </button>
                  </div>
                </div>

                <div className="streams-container">
                  {streamsLoading ? (
                    <div className="streams-loading">
                      <Monitor size={48} />
                      <p>Loading camera streams...</p>
                    </div>
                  ) : filteredCameras.length === 0 ? (
                    <div className="no-streams">
                      <Monitor size={64} />
                      <h3>No Active Cameras in This Collection</h3>
                      <p>No active cameras found in the selected collection. Add cameras to this collection or activate existing ones.</p>
                    </div>
                  ) : (
                    <div className="camera-streams-grid">
                      {filteredCameras.map((camera) => (
                        <div key={camera.id} className="stream-card">
                          <div className="stream-header">
                            <div className="camera-info">
                              <h5>{camera.name}</h5>
                              <span className="camera-location">IP: {camera.ip_address}</span>
                            </div>
                            <div className="stream-status">
                              <div className={`status-indicator ${streamingCameras.has(camera.id) ? 'live' : 'active'}`}></div>
                              <span>{streamingCameras.has(camera.id) ? 'Streaming' : 'Active'}</span>
                            </div>
                          </div>

                          <div className="stream-video">
                            {camera.is_active ? (
                              <StreamPlayer
                                cameraId={camera.id}
                                cameraName={camera.name}
                                rtspUrl={camera.rtsp_url}
                                isStreaming={streamingCameras.has(camera.id)}
                                onStreamStart={() => {
                                  console.log(`✓ Stream started successfully for camera ${camera.id}`);
                                  // Stream state is already set by handleStartStream
                                }}
                                onStreamError={() => {
                                  console.log(`✗ Stream error for camera ${camera.id}`);
                                  setStreamingCameras(prev => {
                                    const newSet = new Set(prev);
                                    newSet.delete(camera.id);
                                    return newSet;
                                  });
                                }}
                              />
                            ) : (
                              <div className="video-placeholder inactive">
                                <Monitor size={48} />
                                <p>Camera Inactive</p>
                                <small>Activate camera to view stream</small>
                              </div>
                            )}
                          </div>

                          <div className="stream-controls">
                            <button
                              className="stream-btn play"
                              title="Start Stream"
                              onClick={() => handleStartStream(camera.id)}
                            >
                              <Play size={14} />
                            </button>
                            <button
                              className="stream-btn stop"
                              title="Stop Stream"
                              onClick={() => handleStopStream(camera.id)}
                            >
                              <Square size={14} />
                            </button>
                            <button className="stream-btn fullscreen" title="Fullscreen">
                              <Monitor size={14} />
                            </button>
                          </div>

                          <div className="stream-info">
                            <span className="stream-id">ID: {camera.id}</span>
                            <span className="stream-protocol">RTSP</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="no-collection-selected">
            <h3>Select an Area</h3>
            <p>Choose an area from the sidebar or create a new one</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default CollectionManager;