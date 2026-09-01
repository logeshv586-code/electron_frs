import React, { useEffect, useState } from 'react';
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
import CompaniesPanel from './components/admin/CompaniesPanel';
import Settings from './components/admin/Settings';
import BackupDashboard from './components/admin/BackupDashboard';
import MainLayout from './components/layout/MainLayout';
import useAuthStore from './store/authStore';
import { detectBackendUrl, API_BASE_URL } from './utils/apiConfig';
import HolidayCalendar from './components/HolidayCalendar';
import AttendanceReport from './components/Attendance/AttendanceReport';

const AppContent = () => {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isCheckingBackend, setIsCheckingBackend] = useState(true);
  const [backendError, setBackendError] = useState(null);
  const { isAuthenticated, getCurrentUser, isSessionExpired, logout } = useAuthStore();

  useEffect(() => {
    const checkBackend = async () => {
      setIsCheckingBackend(true);
      setBackendError(null);
      try {
        const workingUrl = await detectBackendUrl();
        const currentUrl = localStorage.getItem('api_base_url');
        if (workingUrl) {
          if (workingUrl !== currentUrl && workingUrl !== API_BASE_URL) {
            localStorage.setItem('api_base_url', workingUrl);
            window.location.reload();
            return;
          }
          setIsCheckingBackend(false);
        } else {
          setBackendError('Unable to connect to the Face Recognition backend.');
          setIsCheckingBackend(false);
        }
      } catch (error) {
        console.error('Backend detection failed:', error);
        setBackendError('Backend connection check failed.');
        setIsCheckingBackend(false);
      }
    };
    checkBackend();
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (isSessionExpired()) {
      logout();
      return;
    }
    getCurrentUser();
  }, [isAuthenticated, getCurrentUser, isSessionExpired, logout]);

  const renderActiveComponent = () => {
    if (isCheckingBackend) {
      return <div className="loading-container"><div className="loading-spinner" /><h2>Connecting to server</h2><p>Checking the configured backend endpoint.</p></div>;
    }

    if (backendError) {
      return (
        <div className="loading-container disconnected">
          <div className="error-icon">!</div>
          <h2>Server disconnected</h2>
          <p>{backendError}</p>
          <p className="hint">Expected endpoint: {API_BASE_URL}</p>
          <div className="error-actions">
            <button className="retry-button" onClick={() => window.location.reload()}>Retry</button>
            <button className="settings-button" onClick={() => {
              const newIp = window.prompt('Backend IP or URL (for example 192.168.1.50)');
              if (!newIp) return;
              const formattedUrl = newIp.startsWith('http') ? newIp : `http://${newIp}:8005`;
              localStorage.setItem('api_base_url', formattedUrl);
              window.location.reload();
            }}>Set backend</button>
          </div>
        </div>
      );
    }

    switch (activeTab) {
      case 'dashboard': return <Dashboard setActiveTab={setActiveTab} />;
      case 'companies': return <CompaniesPanel />;
      case 'gallery': return <FaceGallery />;
      case 'events': return <EventsWidget />;
      case 'registration': return <RegistrationWidget />;
      case 'matching': return <FaceMatching />;
      case 'video': return <VideoWidget />;
      case 'camera': return <CameraProvider><SimpleCameraManager /></CameraProvider>;
      case 'stream-viewer': return <StreamViewer />;
      case 'users': return <UserManagement />;
      case 'settings': return <Settings />;
      case 'backup': return <BackupDashboard />;
      case 'holiday-calendar': return <HolidayCalendar />;
      case 'attendance-report':
      case 'day-report':
      case 'week-report':
      case 'month-report':
        return <AttendanceReport reportType={activeTab} setActiveTab={setActiveTab} />;
      default: return <Dashboard setActiveTab={setActiveTab} />;
    }
  };

  if (!isAuthenticated && !isCheckingBackend) return <AnimatedLoginPage />;

  return <MainLayout activeTab={activeTab} onTabChange={setActiveTab}>{renderActiveComponent()}</MainLayout>;
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
