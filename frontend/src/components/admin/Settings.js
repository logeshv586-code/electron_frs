import React, { useState, useEffect } from 'react';
import useAuthStore from '../../store/authStore';
import { 
  Settings as SettingsIcon, 
  Save, 
  ShieldCheck, 
  Mail, 
  ShieldAlert,
  Server,
  Zap,
  Target,
  Maximize,
  Shield,
  ChevronDown
} from 'lucide-react';
import { API_BASE_URL } from '../../utils/apiConfig';
import './Settings.css';

const CustomDropdown = ({ options, value, onChange, placeholder = 'Select...', openUp = false }) => {
  const [isOpen, setIsOpen] = useState(false);
  const selectedOption = options.find(o => o.value === value);

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = () => setIsOpen(false);
    if (isOpen) {
      document.addEventListener('click', handleClickOutside);
    }
    return () => document.removeEventListener('click', handleClickOutside);
  }, [isOpen]);

  return (
    <div className="custom-dropdown-container" onClick={(e) => e.stopPropagation()}>
      <div className={`custom-dropdown-header ${isOpen ? 'active' : ''}`} onClick={() => setIsOpen(!isOpen)}>
        <span>{selectedOption ? selectedOption.label : placeholder}</span>
        <ChevronDown size={18} className={`arrow ${isOpen ? 'rotated' : ''}`} />
      </div>
      {isOpen && (
        <div className={`custom-dropdown-list ${openUp ? 'open-up' : ''}`}>
          {options.map(option => (
            <div 
              key={option.value} 
              className={`custom-dropdown-item ${value === option.value ? 'selected' : ''}`}
              onClick={() => {
                onChange({ target: { value: option.value } });
                setIsOpen(false);
              }}
            >
              {option.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Settings = () => {
  const { user } = useAuthStore(); // Removed 'token' from here as it's now fetched from localStorage
  const [settings, setSettings] = useState({
    max_cameras_per_admin: 10,
    max_cameras_per_supervisor: 5,
    require_approval_for_new_users: false,
    smtp_host: '',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    smtp_use_tls: true,
    email_from: '',
    face_recognition_enabled: true,
    show_bounding_boxes: true,
    unknown_detection_enabled: true,
    long_distance_detection_enabled: true,
    min_face_size: 40,
    attendance: {
      punch_in: '09:30',
      punch_out: '18:00',
      working_hours: 8,
      grace_minutes: 15,
      min_hours_present: 4.0,
      overtime_after: 9.0
    }
  });

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null); // Changed initial state to null
  const [companies, setCompanies] = useState([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState('');

  const fetchCompanies = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/companies/`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` }
      });
      if (response.ok) {
        const data = await response.json();
        const activeCompanies = data.companies || [];
        setCompanies(activeCompanies);
        setSelectedCompanyId(prev => {
          if (!prev) return '';
          return activeCompanies.some(company => company.id === prev) ? prev : '';
        });
      }
    } catch (error) {
      console.error('Error fetching companies:', error);
    }
  };

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const query = (user?.role === 'SuperAdmin' && selectedCompanyId) ? `?cid=${selectedCompanyId}` : '';
      const response = await fetch(`${API_BASE_URL}/api/users/settings/system${query}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
        }
      });
      const data = await response.json();
      if (response.ok) {
        const incomingSettings = data.settings || {};
        // Merge with defaults to ensure all keys exist
        setSettings(prev => ({
          ...prev,
          ...incomingSettings,
          attendance: {
            ...prev.attendance,
            ...(incomingSettings.attendance || {})
          }
        }));
      } else {
        setMessage({ type: 'error', text: data.detail || 'Failed to fetch settings' });
        if (response.status === 404 && user?.role === 'SuperAdmin') {
          setSelectedCompanyId('');
          fetchCompanies();
        }
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Error connecting to server' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === 'SuperAdmin') {
      fetchCompanies();
    }
    fetchSettings();
  }, [user]);

  useEffect(() => {
    if (user?.role === 'SuperAdmin' && selectedCompanyId) { // Only fetch if selectedCompanyId is set for SuperAdmin
      fetchSettings();
    }
  }, [selectedCompanyId, user]); // Added user to dependency array for consistency

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;

    if (name.startsWith('attendance.')) {
      const field = name.split('.')[1];
      setSettings(prev => ({
        ...prev,
        attendance: {
          ...prev.attendance,
          [field]: type === 'number' ? parseFloat(value) || 0 : value
        }
      }));
    } else {
      setSettings(prev => ({
        ...prev,
        [name]: type === 'checkbox' ? checked : (type === 'number' ? parseInt(value) || 0 : value)
      }));
    }
  };

  const handleToggleChange = (e) => {
    const { name, checked } = e.target;
    setSettings(prev => ({
      ...prev,
      [name]: checked
    }));
  };

  /* 
     Activity History: Stores the last 5 operations (Success or Error)
     Each entry: { id, type, message, timestamp }
  */
  const [history, setHistory] = useState(() => {
    const saved = localStorage.getItem('settings_history');
    return saved ? JSON.parse(saved) : [];
  });

  useEffect(() => {
    localStorage.setItem('settings_history', JSON.stringify(history));
  }, [history]);

  const addLogEntry = (type, text) => {
    const newEntry = {
      id: Date.now(),
      type,
      message: text,
      timestamp: new Date().toLocaleTimeString()
    };
    setHistory(prev => [newEntry, ...prev].slice(0, 5));
    setMessage({ type, text });
  };

  const calculateWindow = () => {
    const { punch_in, punch_out } = settings.attendance || {};
    if (!punch_in || !punch_out) return 0;
    
    const [h1, m1] = punch_in.split(':').map(Number);
    const [h2, m2] = punch_out.split(':').map(Number);
    
    const d1 = new Date(); d1.setHours(h1, m1, 0);
    const d2 = new Date(); d2.setHours(h2, m2, 0);
    
    let diff = (d2 - d1) / (1000 * 60 * 60);
    if (diff < 0) diff += 24; // Handle overnight shifts if needed
    return diff;
  };

  const humanizeError = (detail) => {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map(err => {
        // Last part of the location is the field name
        let field = err.loc[err.loc.length - 1];
        if (field === 'body' || field === 'attendance') {
           field = err.loc[err.loc.length - 2] || field;
        }
        
        // Clean up field name: max_cameras_per_admin -> Max Cameras Per Admin
        const displayField = field.toString().replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        
        let msg = err.msg;
        // Strip technical prefixes added by backend or pydantic
        if (msg.includes('Value error, ')) msg = msg.split('Value error, ')[1];
        
        return `${displayField}: ${msg}`;
      }).join('. ');
    }
    return JSON.stringify(detail);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      setMessage({ type: '', text: '' });
      
      // Client-side validation for attendance window
      const windowHours = calculateWindow();
      const workingHours = settings.attendance?.working_hours || 0;
      
      if (workingHours > windowHours) {
        throw new Error(`Invalid Configuration: Target Working Hours (${workingHours}h) cannot exceed the time window between Punch In and Punch Out (${windowHours.toFixed(1)}h).`);
      }

      const query = (user?.role === 'SuperAdmin' && selectedCompanyId) ? `?cid=${selectedCompanyId}` : '';
      const response = await fetch(`${API_BASE_URL}/api/users/settings/system${query}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
        },
        body: JSON.stringify(settings)
      });

      const data = await response.json();
      if (response.ok) {
        addLogEntry('success', 'System settings saved successfully');
      } else {
        if (response.status === 422 && data.detail) {
          throw new Error(humanizeError(data.detail));
        }
        throw new Error(data.detail || 'Failed to update settings');
      }
    } catch (err) {
      addLogEntry('error', err.message);
    } finally {
      setLoading(false);
    }
  };

  if (user?.role !== 'SuperAdmin' && user?.role !== 'Admin') {
    return <div className="settings-container">Access Denied</div>;
  }

  return (
    <div className="settings-container">
      <div className="settings-header">
        <h2><SettingsIcon size={24} /> System Settings</h2>
        <p>Configure global system parameters and email notifications</p>
      </div>


      <form onSubmit={handleSubmit} className="settings-form">
        {user?.role === 'SuperAdmin' && (
          <div className="settings-section" style={{ borderLeft: '4px solid var(--primary-color)' }}>
            <div className="section-title">
              <ShieldCheck size={18} />
              <h3>Configuration Target</h3>
            </div>
            <p className="section-desc">Select which organization's settings you want to manage. Leave as "System Default" for global settings.</p>
            <div className="form-group" style={{ maxWidth: '400px' }}>
              <label>Organization / Company</label>
              <CustomDropdown
                value={selectedCompanyId}
                onChange={(e) => setSelectedCompanyId(e.target.value)}
                options={[
                  { value: '', label: 'System Default (Global)' },
                  ...companies.map(c => ({ value: c.id, label: `${c.name} (${c.id})` }))
                ]}
              />
            </div>
          </div>
        )}

        {user?.role === 'SuperAdmin' && (
          <>
            <div className="settings-section">
              <div className="section-title">
                <Shield size={18} />
                <h3>General Limits</h3>
              </div>
              <div className="settings-grid">
                <div className="form-group">
                  <label>Max Cameras per Admin</label>
                  <input
                    type="number"
                    name="max_cameras_per_admin"
                    value={settings.max_cameras_per_admin}
                    onChange={handleInputChange}
                    min="1"
                  />
                </div>
                <div className="form-group">
                  <label>Max Cameras per Supervisor</label>
                  <input
                    type="number"
                    name="max_cameras_per_supervisor"
                    value={settings.max_cameras_per_supervisor}
                    onChange={handleInputChange}
                    min="1"
                  />
                </div>
              </div>
            </div>

            <div className="settings-section">
              <div className="section-title">
                <Mail size={18} />
                <h3>Email Configuration (SMTP)</h3>
              </div>
              <p className="section-desc">Configure SMTP settings to send license expiry notifications to Admins.</p>
              <div className="settings-grid">
                <div className="form-group">
                  <label>SMTP Host</label>
                  <input
                    type="text"
                    name="smtp_host"
                    value={settings.smtp_host}
                    onChange={handleInputChange}
                    placeholder="e.g. smtp.gmail.com"
                  />
                </div>
                <div className="form-group">
                  <label>SMTP Port</label>
                  <input
                    type="number"
                    name="smtp_port"
                    value={settings.smtp_port}
                    onChange={handleInputChange}
                  />
                </div>
                <div className="form-group">
                  <label>SMTP User</label>
                  <input
                    type="text"
                    name="smtp_user"
                    value={settings.smtp_user}
                    onChange={handleInputChange}
                    placeholder="your-email@example.com"
                  />
                </div>
                <div className="form-group">
                  <label>SMTP Password</label>
                  <input
                    type="password"
                    name="smtp_password"
                    value={settings.smtp_password}
                    onChange={handleInputChange}
                    placeholder="••••••••"
                  />
                </div>
                <div className="form-group">
                  <label>Email From Address</label>
                  <input
                    type="text"
                    name="email_from"
                    value={settings.email_from}
                    onChange={handleInputChange}
                    placeholder="noreply@example.com"
                  />
                </div>
                <div className="form-group checkbox-group">
                  <label>
                    <input
                      type="checkbox"
                      name="smtp_use_tls"
                      checked={settings.smtp_use_tls}
                      onChange={handleInputChange}
                    />
                    Use TLS/SSL
                  </label>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Face Recognition Master Toggle */}
        <div className="settings-section master-toggle-section">
          <div className="section-header-row">
            <div className="section-title">
              <Shield size={20} />
              <h3>Face Recognition System</h3>
            </div>
            <label className="switch">
              <input
                type="checkbox"
                name="face_recognition_enabled"
                checked={settings.face_recognition_enabled}
                onChange={handleToggleChange}
              />
              <span className="slider round"></span>
            </label>
          </div>
          <p className="section-desc">Enable or disable the core face recognition pipeline and detection features.</p>
          
          
          <div className={`settings-grid sub-settings ${!settings.face_recognition_enabled ? 'greyed-out' : ''}`}>
          </div>
        </div>

        {/* Attendance Settings - Visible to SuperAdmin and Admin */}
        <div className="settings-section">
          <div className="section-title">
            <Server size={18} />
            <h3>Attendance Configuration</h3>
          </div>
          <p className="section-desc">Set global thresholds for punch-in, punch-out, and daily targets.</p>
          <div className="settings-grid">
            <div className="form-group">
              <label>Punch In Time (Late Threshold)</label>
              <input
                type="time"
                name="attendance.punch_in"
                value={settings.attendance?.punch_in || '09:30'}
                onChange={handleInputChange}
              />
            </div>
            <div className="form-group">
              <label>Punch Out Time</label>
              <input
                type="time"
                name="attendance.punch_out"
                value={settings.attendance?.punch_out || '18:00'}
                onChange={handleInputChange}
              />
            </div>
            <div className="form-group">
              <label>Target Working Hours</label>
              <input
                type="number"
                name="attendance.working_hours"
                value={settings.attendance?.working_hours || 8}
                onChange={handleInputChange}
                min="1"
                max="24"
              />
            </div>
            <div className="form-group">
              <label>Grace Period (Minutes)</label>
              <input
                type="number"
                name="attendance.grace_minutes"
                value={settings.attendance?.grace_minutes || 0}
                onChange={handleInputChange}
                min="0"
                max="120"
              />
            </div>
            <div className="form-group">
              <label>Min Hours Present (Threshold)</label>
              <input
                type="number"
                name="attendance.min_hours_present"
                value={settings.attendance?.min_hours_present || 0}
                onChange={handleInputChange}
                min="0"
                max="24"
                step="0.5"
              />
            </div>
            <div className="form-group">
              <label>Overtime After (Hours)</label>
              <input
                type="number"
                name="attendance.overtime_after"
                value={settings.attendance?.overtime_after || 0}
                onChange={handleInputChange}
                min="1"
                max="24"
                step="0.5"
              />
            </div>
          </div>
        </div>

        {user?.role === 'Admin' && (
          <div className="settings-section">
            <div className="section-title">
              <Shield size={18} />
              <h3>Account Info</h3>
            </div>
            <p>Email settings can only be configured by SuperAdmin.</p>
          </div>
        )}

        <div className="settings-actions">
          <button type="submit" className="save-btn" disabled={loading}>
            <Save size={18} />
            {loading ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </form>

      {/* Settings Activity Log - Persistent History */}
      <div className="settings-section history-section" style={{ marginTop: '30px', borderTop: '2px solid var(--border-color)' }}>
        <div className="section-title">
          <Server size={18} />
          <h3>Settings Activity Log</h3>
        </div>
        <p className="section-desc">History of recent configuration changes and validation status.</p>
        
        <div className="history-list">
          {history.length === 0 ? (
            <p style={{ textAlign: 'center', padding: '20px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
              No recent activity recorded.
            </p>
          ) : (
            history.map(entry => (
              <div key={entry.id} className={`history-entry ${entry.type}`}>
                <div className="entry-header">
                  <span className={`entry-status ${entry.type}`}>
                    {entry.type === 'success' ? '✓ SUCCESS' : '⚠ FAILED'}
                  </span>
                  <span className="entry-time">{entry.timestamp}</span>
                </div>
                <div className="entry-message">{entry.message}</div>
              </div>
            ))
          )}
        </div>
        
        {history.length > 0 && (
          <button 
            className="clear-history-btn"
            onClick={() => setHistory([])}
            style={{ 
              marginTop: '15px', 
              background: 'transparent', 
              border: 'none', 
              color: 'var(--text-secondary)', 
              fontSize: '11px', 
              cursor: 'pointer',
              textDecoration: 'underline'
            }}
          >
            Clear Log History
          </button>
        )}
      </div>
    </div>
  );
};

export default Settings;
