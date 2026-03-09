import React, { useState, useEffect } from 'react';
import MJPEGStreamPlayer from './MJPEGStreamPlayer';
import { useCameraStore } from '../../store/cameraStore';
import { useArchiveStore } from '../../store/archiveStore';
import { API_BASE_URL } from '../../utils/apiConfig';
import './CameraCard.css';

const CameraCard = ({
  camera,
  onCameraClick,
  onEdit,
  onActivate,
  onDeactivate,
  onStartStream,
  onStopStream,
  onShowRecordings
}) => {
  // Early return if camera is not provided
  if (!camera) {
    return <div className="camera-card error">Camera data not available</div>;
  }

  // Initialize stores with try-catch for safety
  let store, archiveStore, toggleBookmark, isBookmarked, getRecordingStatus;

  try {
    store = useCameraStore();
    archiveStore = useArchiveStore();

    if (store) {
      toggleBookmark = store.toggleBookmark;
      isBookmarked = store.isBookmarked;
    }

    if (archiveStore) {
      getRecordingStatus = archiveStore.getRecordingStatus;
    }
  } catch (error) {
    console.error('Error accessing stores:', error);
    return <div className="camera-card error">Unable to load camera data</div>;
  }

  const [isBookmarkedCamera, setIsBookmarkedCamera] = useState(false);
  const [showActions, setShowActions] = useState(false);

  // Initialize bookmark state safely
  useEffect(() => {
    try {
      if (isBookmarked && typeof isBookmarked === 'function' && camera?.id) {
        setIsBookmarkedCamera(isBookmarked(camera.id));
      }
    } catch (error) {
      console.error('Error checking initial bookmark status:', error);
    }
  }, [isBookmarked, camera?.id]);

  // Generate stream ID for recording status safely
  let recordingStatus = null;
  try {
    const collectionName = camera?.collection || camera?.collectionId || camera?.collection_name;
    const streamId = collectionName && camera?.ip_address ? `${collectionName}_${camera.ip_address}` : null;

    if (streamId && getRecordingStatus && typeof getRecordingStatus === 'function') {
      recordingStatus = getRecordingStatus(streamId);
    }
  } catch (error) {
    console.error('Error getting recording status:', error);
  }

  // Update bookmark state when it changes in the store
  useEffect(() => {
    try {
      if (isBookmarked && typeof isBookmarked === 'function' && camera?.id) {
        setIsBookmarkedCamera(isBookmarked(camera.id));
      }
    } catch (error) {
      console.error('Error updating bookmark status:', error);
    }
  }, [camera?.id, isBookmarked]);

  const handleBookmarkToggle = (e) => {
    e.stopPropagation();
    console.log('Toggling bookmark for camera:', camera.id, camera.name);
    try {
      if (toggleBookmark && typeof toggleBookmark === 'function') {
        toggleBookmark(camera.id);
        // Update local state immediately for better UI responsiveness
        setIsBookmarkedCamera(!isBookmarkedCamera);
      }
    } catch (error) {
      console.error('Error toggling bookmark:', error);
    }
  };

  const handleCardClick = () => {
    if (onCameraClick) {
      onCameraClick(camera);
    }
  };

  const handleActionClick = (e, action) => {
    e.stopPropagation();
    switch (action) {
      case 'edit':
        onEdit && onEdit(camera);
        break;
      case 'activate':
        onActivate && onActivate(camera.id);
        break;
      case 'deactivate':
        onDeactivate && onDeactivate(camera.id);
        break;
      case 'startStream':
        onStartStream && onStartStream(camera.id);
        break;
      case 'stopStream':
        onStopStream && onStopStream(camera.id);
        break;
      case 'showRecordings':
        onShowRecordings && onShowRecordings(camera);
        break;
      default:
        break;
    }
    setShowActions(false);
  };

  return (
    <div
      className={`camera-card ${isBookmarkedCamera ? 'bookmarked' : ''}`}
      onClick={handleCardClick}
    >
      <div className="camera-card-header">
        <div className="camera-title-section">
          <h3 className="camera-name">{camera.name}</h3>
          <div className="camera-status-badges">
            <span className={`status-badge ${camera.is_active ? 'active' : 'inactive'}`}>
              {camera.is_active ? 'Active' : 'Inactive'}
            </span>
            {camera.collection_name && (
              <span className="collection-badge">{camera.collection_name}</span>
            )}
          </div>
        </div>

        <div className="camera-controls">
          {/* Recording status indicator */}
          {recordingStatus && (
            <div
              className={`recording-status-dot ${recordingStatus.status}`}
              title={`Recording Status: ${
                recordingStatus.status === 'recording' ? 'Recording' :
                recordingStatus.status === 'stopped' ? 'Not Recording' :
                recordingStatus.status === 'backend_unavailable' ? 'Backend Unavailable' :
                recordingStatus.status === 'stale' ? 'Connection Lost' :
                'Unknown'
              }`}
            >
              <div className={`status-indicator ${
                recordingStatus.status === 'recording' ? 'recording' :
                recordingStatus.status === 'backend_unavailable' ? 'backend-unavailable' :
                'stopped'
              }`} />
            </div>
          )}

          {/* Actions menu */}
          <div className="actions-menu">
            <button
              className="actions-button"
              onClick={(e) => {
                e.stopPropagation();
                setShowActions(!showActions);
              }}
              title="Camera Actions"
            >
              ⋮
            </button>

            {showActions && (
              <div className="actions-dropdown">
                <button onClick={(e) => handleActionClick(e, 'edit')}>
                  Edit Camera
                </button>
                {camera.is_active ? (
                  <button onClick={(e) => handleActionClick(e, 'deactivate')}>
                    Deactivate
                  </button>
                ) : (
                  <button onClick={(e) => handleActionClick(e, 'activate')}>
                    Activate
                  </button>
                )}
                <button onClick={(e) => handleActionClick(e, 'startStream')}>
                  Start Stream
                </button>
                <button onClick={(e) => handleActionClick(e, 'stopStream')}>
                  Stop Stream
                </button>
                <button onClick={(e) => handleActionClick(e, 'showRecordings')}>
                  Recordings
                </button>
              </div>
            )}
          </div>

          {/* Bookmark button */}
          <button
            className={`bookmark-button ${isBookmarkedCamera ? 'bookmarked' : ''}`}
            onClick={handleBookmarkToggle}
            title={isBookmarkedCamera ? 'Remove Bookmark' : 'Add Bookmark'}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill={isBookmarkedCamera ? "#FFD700" : "none"}
              stroke={isBookmarkedCamera ? "#FFD700" : "#FFFFFF"}
              strokeWidth="2"
            >
              <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
            </svg>
          </button>
        </div>
      </div>

      <div className="camera-card-content">
        {camera.rtsp_url || camera.ip_address ? (
          // Use enhanced camera stream display
          <div className="camera-stream-container">
            {camera.is_active ? (
              <img
                src={`${API_BASE_URL}/api/collections/cameras/${camera.id}/stream`}
                alt={`${camera.name} stream`}
                className="camera-stream-image"
                onError={(e) => {
                  e.target.style.display = 'none';
                  e.target.nextSibling.style.display = 'flex';
                }}
              />
            ) : (
              <div className="camera-inactive">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#666" strokeWidth="2">
                  <rect x="3" y="3" width="18" height="12" rx="2"></rect>
                  <path d="M7 15v2"></path>
                  <path d="M17 15v2"></path>
                  <path d="M7 19h10"></path>
                </svg>
                <span>Camera Inactive</span>
              </div>
            )}
            <div className="camera-offline" style={{display: 'none'}}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#999999" strokeWidth="2">
                <path d="M10.5 15.5L3 8.5"></path>
                <path d="M21 8.5L16.5 13"></path>
                <rect x="3" y="3" width="18" height="12" rx="2"></rect>
                <path d="M7 15v2"></path>
                <path d="M17 15v2"></path>
                <path d="M7 19h10"></path>
              </svg>
              <span>Stream unavailable</span>
            </div>
          </div>
        ) : (
          // Fallback when no stream information is available
          <div className="camera-offline">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#999999" strokeWidth="2">
              <path d="M10.5 15.5L3 8.5"></path>
              <path d="M21 8.5L16.5 13"></path>
              <rect x="3" y="3" width="18" height="12" rx="2"></rect>
              <path d="M7 15v2"></path>
              <path d="M17 15v2"></path>
              <path d="M7 19h10"></path>
            </svg>
            <span>No stream configured</span>
          </div>
        )}
      </div>

      <div className="camera-card-footer">
        <div className="camera-info">
          <span className="camera-ip">{camera.ip_address || 'Unknown IP'}</span>
          <span className="camera-created">
            Added: {new Date(camera.created_at).toLocaleDateString()}
          </span>
        </div>
        <div className="camera-stats">
          {camera.last_seen && (
            <span className="last-seen">
              Last seen: {new Date(camera.last_seen).toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default CameraCard;
