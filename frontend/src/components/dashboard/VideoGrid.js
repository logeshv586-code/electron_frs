import React, { useState, useEffect } from 'react';
import './VideoGrid.css';

const VideoGrid = ({ 
  cameras = [], 
  layout = '2x2', 
  onCameraSelect, 
  selectedCamera = null,
  showControls = true 
}) => {
  const [gridCells, setGridCells] = useState([]);

  // Parse layout to get grid dimensions
  const getGridDimensions = (layout) => {
    const [cols, rows] = layout.split('x').map(Number);
    return { cols, rows, total: cols * rows };
  };

  // Initialize grid cells
  useEffect(() => {
    const { total } = getGridDimensions(layout);
    const cells = Array.from({ length: total }, (_, index) => ({
      id: index,
      camera: cameras[index] || null,
      isEmpty: !cameras[index]
    }));
    setGridCells(cells);
  }, [layout, cameras]);

  const handleCellClick = (cellIndex) => {
    const cell = gridCells[cellIndex];
    if (cell.camera && onCameraSelect) {
      onCameraSelect(cell.camera);
    }
  };

  const { cols, rows } = getGridDimensions(layout);

  return (
    <div className="video-grid-container">
      <div 
        className={`video-grid layout-${layout}`}
        style={{
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`
        }}
      >
        {gridCells.map((cell, index) => (
          <div
            key={cell.id}
            className={`video-cell ${cell.isEmpty ? 'empty' : 'occupied'} ${
              selectedCamera?.id === cell.camera?.id ? 'selected' : ''
            }`}
            onClick={() => handleCellClick(index)}
          >
            {cell.camera ? (
              <div className="camera-content">
                <div className="camera-header">
                  <span className="camera-name">{cell.camera.name}</span>
                  <span className={`camera-status ${cell.camera.is_active ? 'active' : 'inactive'}`}>
                    {cell.camera.is_active ? '🟢' : '🔴'}
                  </span>
                </div>
                <div className="camera-video">
                  {cell.camera.is_active ? (
                    <div className="video-placeholder">
                      <div className="streaming-indicator">
                        <span>📹</span>
                        <span>Live Stream</span>
                      </div>
                    </div>
                  ) : (
                    <div className="no-video">
                      <span>📹</span>
                      <span>Camera Offline</span>
                    </div>
                  )}
                </div>
                {showControls && (
                  <div className="camera-controls">
                    <button 
                      className="control-btn"
                      title="Camera Settings"
                    >
                      ⚙️
                    </button>
                    <button 
                      className="control-btn"
                      title="Full Screen"
                    >
                      ⛶
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-cell">
                <div className="empty-content">
                  <span className="empty-icon">➕</span>
                  <span className="empty-text">Add Camera</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      
      {cameras.length === 0 && (
        <div className="no-cameras-message">
          <div className="message-content">
            <span className="message-icon">📹</span>
            <h3>No Cameras Available</h3>
            <p>Add cameras to your collection to see them in the grid view</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default VideoGrid;
