import React, { useState } from 'react';
import TabbedCameraManager from './TabbedCameraManager';
import './SimpleCameraManager.css';

const SimpleCameraManager = () => {
  const [viewMode, setViewMode] = useState('tabbed'); // 'tabbed' or 'classic'
  const [showManager, setShowManager] = useState(true); // Changed to true to skip welcome screen

  // Directly show the tabbed manager without welcome screen
  return (
    <div className="simple-camera-manager">
      <TabbedCameraManager 
        onClose={() => setShowManager(false)}
      />
    </div>
  );
};

export default SimpleCameraManager;
