import React from 'react';
import { CameraProvider } from './camera/CameraManager';
import EnhancedCameraDashboard from './camera/EnhancedCameraDashboard';

const EnhancedApp = () => {
  return (
    <CameraProvider>
      <div className="app">
        <EnhancedCameraDashboard />
      </div>
    </CameraProvider>
  );
};

export default EnhancedApp;
