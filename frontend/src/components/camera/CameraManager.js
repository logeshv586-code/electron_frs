import React, { createContext, useContext } from 'react';
import { useCameraStore } from '../../store/cameraStore';

const CameraContext = createContext();

export function CameraProvider({ children }) {
  const store = useCameraStore();

  return (
    <CameraContext.Provider value={store}>
      {children}
    </CameraContext.Provider>
  );
}

export function useCameras() {
  const context = useContext(CameraContext);
  if (!context) {
    throw new Error('useCameras must be used within a CameraProvider');
  }
  return context;
}

// For backward compatibility
export default function CameraManager({ children }) {
  return <CameraProvider>{children}</CameraProvider>;
}