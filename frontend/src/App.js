import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import './App.css';
import FaceGallery from './components/FaceGallery';
import EventsWidget from './components/EventsWidget';
import RegistrationWidget from './components/RegistrationWidget';
import VideoWidget from './components/VideoWidget';
import FaceMatching from './components/FaceMatching';
import Dashboard from './components/dashboard/Dashboard';
import { CameraProvider } from './components/camera/CameraManager';
import SimpleCameraManager from './components/camera/SimpleCameraManager';
import StreamViewer from './components/StreamViewer';
import AnimatedLoginPage from './components/auth/AnimatedLoginPage';
import UserManagement from './components/admin/UserManagement';
import Settings from './components/admin/Settings';
import MainLayout from './components/layout/MainLayout';
import useAuthStore from './store/authStore';
import { detectBackendUrl, API_BASE_URL } from './utils/apiConfig';

const AppContent = () => {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isCheckingBackend, setIsCheckingBackend] = useState(true);
  const { isAuthenticated, getCurrentUser } = useAuthStore();

  useEffect(() => {
    // Auto-detect backend URL and switch if necessary
    const checkBackend = async () => {
      try {
        const workingUrl = await detectBackendUrl();
        const currentUrl = localStorage.getItem('api_base_url');
        
        // If we found a working URL
        if (workingUrl) {
          // If it's different from what we have saved (or we have nothing saved)
          // AND it's different from the current runtime default (to avoid unnecessary reloads if default matches)
          if (workingUrl !== currentUrl && workingUrl !== API_BASE_URL) {
            console.log(`Switching API URL to ${workingUrl}`);
            localStorage.setItem('api_base_url', workingUrl);
            window.location.reload();
            return;
          }
        } else {
          // If no server found, and we have a stored URL that might be dead
          if (currentUrl) {
            console.warn(`Stored backend URL ${currentUrl} is not responding. Resetting to defaults.`);
            localStorage.removeItem('api_base_url');
            window.location.reload();
            return;
          }
          
          console.warn('No backend server detected.');
        }
      } catch (error) {
        console.error('Backend detection failed:', error);
      } finally {
        setIsCheckingBackend(false);
      }
    };
    
    checkBackend();
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    getCurrentUser();
  }, [isAuthenticated, getCurrentUser]);

  const renderActiveComponent = () => {
    if (isCheckingBackend) {
      return (
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <h2>Connecting to Server...</h2>
          <p>Checking available connection points...</p>
        </div>
      );
    }

    switch (activeTab) {
      case 'dashboard':
        return <Dashboard />;
      case 'gallery':
        return <FaceGallery />;
      case 'events':
        return <EventsWidget />;
      case 'registration':
        return <RegistrationWidget />;
      case 'matching':
        return <FaceMatching />;
      case 'video':
        return <VideoWidget />;
      case 'camera':
        return (
          <CameraProvider>
            <SimpleCameraManager />
          </CameraProvider>
        );
      case 'stream-viewer':
        return <StreamViewer />;
      case 'users':
        return <UserManagement />;
      case 'settings':
        return <Settings />;
      default:
        return <Dashboard />;
    }
  };

  // If not authenticated, show login page
  if (!isAuthenticated && !isCheckingBackend) {
    return <AnimatedLoginPage />;
  }

  return (
    <MainLayout activeTab={activeTab} onTabChange={setActiveTab}>
      {renderActiveComponent()}
    </MainLayout>
  );
};

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<AnimatedLoginPage />} />
        <Route path="/*" element={<AppContent />} />
      </Routes>
    </Router>
  );
}

export default App;
